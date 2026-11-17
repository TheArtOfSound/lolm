import test from "node:test";
import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
if(!globalThis.crypto)globalThis.crypto=webcrypto;
import {runNotificationCycle,purgeNotifications,purgeAdjustments} from "../commercial/notifications.mjs";
class FakeDB{
 constructor(){this.orders=[{session_id:"cs_live_qira000001",status:"paid",updated_at:1794821000}];this.intakes=[{session_id:"cs_live_qira000001",submitted_at:1794821000}];this.adjustments=[];this.notifications=new Map();this.failSend=false;}
 prepare(sql){const db=this;return {bind(...args){return {sql,args,
 async first(){
  if(!sql.startsWith("UPDATE qira_notifications SET status='sending'"))throw Error("unexpected first");
  const [expires,id,at]=args,n=db.notifications.get(id);
  if(!n||!(n.status==="pending"||(n.status==="sending"&&n.lease_until<at)))return null;
  n.status="sending";n.attempts++;n.lease_until=expires;return {...n};
 },
 async all(){
  if(!sql.startsWith("SELECT notification_id"))throw Error("unexpected all");
  const at=args[0];return {success:true,results:[...db.notifications.values()].filter(n=>n.next_attempt_at<=at&&(n.status==="pending"||(n.status==="sending"&&n.lease_until<at))).slice(0,8)};
 },
 async run(){
  if(sql.startsWith("UPDATE qira_notifications SET status='sent'")){
   const [at,id]=args,n=db.notifications.get(id);if(n){n.status="sent";n.sent_at=at;}return {success:true};
  }
  if(sql.startsWith("UPDATE qira_notifications SET status='pending'")){
   const [next,id]=args,n=db.notifications.get(id);if(n){n.status="pending";n.lease_until=null;n.next_attempt_at=next;}return {success:true};
  }
  if(sql.startsWith("DELETE FROM qira_notifications")){
   for(const [id,n]of db.notifications)if(n.created_at<args[0])db.notifications.delete(id);return {success:true};
  }
  if(sql.startsWith("DELETE FROM qira_adjustments")){
   db.adjustments=db.adjustments.filter(x=>x.received_at>=args[0]);return {success:true};
  }
  throw Error("unexpected run "+sql.slice(0,70));
 }
 };}};}
 async batch(steps){
  for(const {sql,args} of steps){
   if(!sql.startsWith("INSERT OR IGNORE INTO qira_notifications"))throw Error("unexpected SQL "+sql);
   const [created,next,earliest]=args;let sources=[];
   if(sql.includes("FROM qira_orders"))sources=this.orders.filter(o=>o.updated_at>=earliest).map(o=>({notification_id:"order:"+o.session_id+":"+o.status,kind:o.status,session_id:o.session_id}));
   else if(sql.includes("FROM qira_intakes"))sources=this.intakes.filter(i=>i.submitted_at>=earliest&&this.orders.some(o=>o.session_id===i.session_id&&o.status==="paid")).map(i=>({notification_id:"intake:"+i.session_id,kind:"intake",session_id:i.session_id}));
   else if(sql.includes("FROM qira_adjustments"))sources=this.adjustments.filter(x=>x.received_at>=earliest).map(x=>({notification_id:"adjustment:"+x.event_id,kind:x.kind,session_id:x.session_id}));
   else throw Error("unexpected source");
   for(const src of sources)if(!this.notifications.has(src.notification_id))this.notifications.set(src.notification_id,{...src,status:"pending",attempts:0,created_at:created,next_attempt_at:next,lease_until:null});
  }return steps.map(()=>({success:true}));
 }
}
const t=1794821010;
const env=(db,key="re_test_domain_scoped")=>({QIRA_PROOF_ORDERS:db,QIRA_RESEND_API_KEY:key});
test("without a protected email key, enqueue operations but never falsely mark delivered",async()=>{
 const db=new FakeDB();const r=await runNotificationCycle(env(db,""),t,async()=>{throw Error("must not send")});
 assert.deepEqual(r,{configured:false,delivered:0});assert.equal(db.notifications.size,2);
 assert.ok([...db.notifications.values()].every(v=>v.status==="pending"));
});
test("scheduled queue emits one notification for paid order and one for intake, with no customer PII",async()=>{
 const db=new FakeDB(),out=[];
 const stub=async(u,init)=>{out.push({u,...init});return {ok:true,json:async()=>({id:"email_test_0123456789abcdef"})};};
 const r=await runNotificationCycle(env(db),t,stub);
 assert.deepEqual(r,{configured:true,delivered:2});assert.equal(out.length,2);
 for(const item of out){
  assert.equal(item.u,"https://api.resend.com/emails");
  assert.equal(item.headers.Authorization,"Bearer re_test_domain_scoped");
  const msg=JSON.parse(item.body);
  assert.equal(msg.to[0],"bryanleonard@imagineqira.com");
  assert.doesNotMatch(item.body,/owner\/private|buyer@example/);
 }
 assert.equal((await runNotificationCycle(env(db),t+300,stub)).delivered,0);
 assert.equal(out.length,2);
});
test("provider failure leaves durable retry and backoff without exposing key",async()=>{
 const db=new FakeDB(),calls=[];
 const fail=async(_,opts)=>{calls.push(opts);return {ok:false,status:503,text:async()=>"private provider error"};};
 const r=await runNotificationCycle(env(db),t,fail);
 assert.equal(r.delivered,0);assert.equal(calls.length,2);
 const first=[...db.notifications.values()][0];assert.equal(first.status,"pending");assert.ok(first.next_attempt_at>t);
 assert.equal((await runNotificationCycle(env(db),t+10,fail)).delivered,0);
 assert.equal(calls.length,2);
 const recovered=await runNotificationCycle(env(db),t+500,async()=>({ok:true,json:async()=>({id:"email_test_0123456789abcdef"})}));
 assert.equal(recovered.delivered,2);
});
test("adjustment notices are deduplicated by event ID and pruned after retention",async()=>{
 const db=new FakeDB();db.orders=[];db.intakes=[];
 db.adjustments=[{event_id:"evt_first",session_id:"cs_live_example",kind:"partial_refund",received_at:t},{event_id:"evt_second",session_id:"cs_live_example",kind:"dispute_closed",received_at:t}];
 await runNotificationCycle(env(db),t,async()=>({ok:true,json:async()=>({id:"email_test_0123456789abcdef"})}));
 assert.equal(db.notifications.size,2);
 await runNotificationCycle(env(db),t+300,async()=>({ok:true,json:async()=>({id:"email_test_0123456789abcdef"})}));
 assert.equal(db.notifications.size,2);
 await purgeNotifications(db,t+181*86400);
 await purgeAdjustments(db,t+181*86400);
 assert.equal(db.notifications.size,0);assert.equal(db.adjustments.length,0);
});
