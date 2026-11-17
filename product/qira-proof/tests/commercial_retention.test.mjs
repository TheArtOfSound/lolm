import test from "node:test";
import assert from "node:assert/strict";
import worker from "../commercial/landing.mjs";
import {purgeOldOrderRows} from "../commercial/payments.mjs";
class ExpiringD1 {
 constructor(now){
  this.events=new Map([["evt_old",{received:now-181*86400}],["evt_new",{received:now-5*86400}]]);
  this.orders=new Map([["cs_live_old",{updated:now-181*86400}],["cs_live_new",{updated:now-3*86400}]]);
  this.intakes=new Map([["cs_live_old",{submitted:now-181*86400,state:"cancelled"}],["cs_live_new",{submitted:now-3*86400,state:"awaiting_authorization"}]]);
  this.reports=new Set();this.codes=new Set();this.notices=new Set();
  this.failing=false;
 }
 prepare(sql){return {bind:(cutoff)=>({sql,cutoff})};}
 async batch(statements){
  if(this.failing)throw Error("db failure");
  assert.equal(statements.length,3);
  for(const s of statements){
   if(s.sql.startsWith("DELETE FROM qira_events")){
    for(const [id,v]of this.events)if(v.received<s.cutoff)this.events.delete(id);
   }else if(s.sql.startsWith("DELETE FROM qira_intakes")){
    assert.match(s.sql,/state='cancelled'/);
    for(const [sid,v]of this.intakes)if(v.submitted<s.cutoff&&v.state==="cancelled"&&!this.reports.has(sid))this.intakes.delete(sid);
   }else if(s.sql.startsWith("DELETE FROM qira_orders")){
    assert.match(s.sql,/NOT EXISTS \(SELECT 1 FROM qira_intakes/);
    assert.match(s.sql,/NOT EXISTS \(SELECT 1 FROM qira_deliverables/);
    for(const [sid,v]of this.orders)
     if(v.updated<s.cutoff&&!this.intakes.has(sid)&&!this.reports.has(sid)&&!this.codes.has(sid)&&!this.notices.has(sid))this.orders.delete(sid);
   }else throw Error("Unexpected cleanup query");
  }
  return [{success:true},{success:true},{success:true}];
 }
}
const now=Math.floor(Date.now()/1000);
test("180-day D1 retention deletes only expired webhook IDs and receipt handles",async()=>{
 const db=new ExpiringD1(now);
 assert.equal(await purgeOldOrderRows(db,now),true);
 assert.deepEqual([...db.events.keys()],["evt_new"]);
 assert.deepEqual([...db.orders.keys()],["cs_live_new"]);
 assert.deepEqual([...db.intakes.keys()],["cs_live_new"]);
});
test("retention rejects missing database and propagates storage errors for observability",async()=>{
 await assert.rejects(()=>purgeOldOrderRows(null,now),/retention_unavailable/);
 const db=new ExpiringD1(now);db.failing=true;
 await assert.rejects(()=>purgeOldOrderRows(db,now),/db failure/);
});
test("Cloudflare scheduled handler registers retention work and does nothing without D1",async()=>{
 const db=new ExpiringD1(now),pending=[];
 await worker.scheduled({}, {QIRA_PROOF_ORDERS:db},{waitUntil:p=>pending.push(p)});
 assert.equal(pending.length,1);
 await pending[0];
 assert.equal(db.orders.has("cs_live_old"),false);
 await worker.scheduled({}, {},{waitUntil:()=>{throw Error("unexpected") }});
});
test("retention has no HTTP admin or unauthenticated cleanup endpoint",async()=>{
 for(const path of ["/api/orders/purge","/admin/delete-orders","/api/stripe/purge"]){
  const resp=await worker.fetch(new Request("https://proof.imagineqira.com"+path));
  assert.equal(resp.status,404);
 }
});
