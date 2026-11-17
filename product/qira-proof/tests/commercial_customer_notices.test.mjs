import test from "node:test";
import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import {buyerDigest} from "../commercial/payments.mjs";
import {runCustomerReadyNotices,purgeCustomerNotices} from "../commercial/customer_notices.mjs";
if(!globalThis.crypto)globalThis.crypto=webcrypto;
const mail="buyer@example.invalid",sid="cs_live_qiraCustomer1234567",key="local_customer_test_0123456789abcdef0123456789abcdef0123",at=1794880000;
class DB{
 constructor(){this.order={status:"paid",refund_amount:0,buyer_email_digest:null};this.intake={contact_email:mail,state:"delivered"};this.report={revoked_at:null,released_at:at-60};this.notice=null;}
 prepare(sql){const db=this;return {bind(...args){return {sql,args,
 async run(){
  if(sql.startsWith("INSERT OR IGNORE INTO qira_customer_notices")){
   if(!db.notice&&db.report.revoked_at==null&&db.report.released_at<=args[2]&&db.order.status==="paid"&&db.order.refund_amount===0&&db.intake.state==="delivered")
    db.notice={session_id:sid,status:"pending",attempts:0,created_at:args[0],next_attempt_at:args[1],lease_until:null};
   return {success:true};
  }
  if(sql.startsWith("UPDATE qira_customer_notices SET status='accepted'")){
   if(db.notice){db.notice.status="accepted";db.notice.accepted_at=args[0];db.notice.lease_until=null;}return {success:true};
  }
  if(sql.startsWith("UPDATE qira_customer_notices SET status='pending'")){
   if(db.notice){db.notice.status="pending";db.notice.next_attempt_at=args[0];db.notice.lease_until=null;}return {success:true};
  }
  if(sql.startsWith("DELETE FROM qira_customer_notices")){
   if(db.notice&&db.notice.status==="accepted"&&db.notice.created_at<args[0])db.notice=null;return {success:true};
  }
  throw Error("unsupported run "+sql.slice(0,75));
 },
 async first(){
  if(!sql.startsWith("UPDATE qira_customer_notices SET"))throw Error("unsupported first");
  if(!db.notice)return null;
  if(!(db.notice.status==="pending"||(db.notice.status==="sending"&&db.notice.lease_until<args[2])))return null;
  db.notice.status="sending";db.notice.attempts++;db.notice.lease_until=args[0];return {session_id:sid,attempts:db.notice.attempts};
 },
 async all(){
  if(!sql.startsWith("SELECT n.session_id"))throw Error("unsupported all");
  if(!db.notice||db.notice.next_attempt_at>args[0]||!(db.notice.status==="pending"||(db.notice.status==="sending"&&db.notice.lease_until<args[1]))||db.order.status!=="paid"||db.order.refund_amount!==0||db.intake.state!=="delivered"||db.report.revoked_at!=null||db.report.released_at>args[2])return {success:true,results:[]};
  return {success:true,results:[{...db.notice,contact_email:db.intake.contact_email,buyer_email_digest:db.order.buyer_email_digest}]};
 }
 };}};}
}
async function env(){const db=new DB();db.order.buyer_email_digest=await buyerDigest(key,mail);return {db,QIRA_PROOF_ORDERS:db,QIRA_ORDER_EMAIL_PEPPER:key,QIRA_RESEND_API_KEY:"re_test_sender"};}
const okay=async()=>({ok:true,json:async()=>({id:"33333333-3333-4333-8333-333333333333"})});
test("approved report is announced only to the Stripe-verified checkout inbox, once",async()=>{
 const e=await env(),sent=[];
 const result=await runCustomerReadyNotices(e,at,async(url,opts)=>{sent.push({url,opts});return okay();});
 assert.deepEqual(result,{configured:true,accepted:1});assert.equal(sent.length,1);
 const payload=JSON.parse(sent[0].opts.body);
 assert.deepEqual(payload.to,[mail]);
 assert.match(payload.text,/proof.imagineqira.com\/report-access/);
 assert.match(payload.text,/cs_live_qiraCustomer1234567/);
 assert.doesNotMatch(payload.text,/reports\/private|\.pdf|github_pat_|bucket_name/);
 assert.equal(e.db.notice.status,"accepted");
 await runCustomerReadyNotices(e,at+400,async()=>{throw Error("duplicate send")});
 assert.equal(sent.length,1);
});
test("unpaid, refunded, unapproved and mismatched emails do not result in a buyer notification",async()=>{
 for(const change of [e=>e.db.order.status="pending",e=>e.db.order.refund_amount=2500,e=>e.db.report.revoked_at=at,e=>e.db.intake.state="in_review",e=>e.db.order.buyer_email_digest="0".repeat(64)]){
  const e=await env();change(e);let sends=0;
  const result=await runCustomerReadyNotices(e,at,async()=>{sends++;return okay();});
  assert.equal(result.accepted,0);assert.equal(sends,0);
 }
});
test("provider failure retries through durable outbox and no sender key never fakes acceptance",async()=>{
 const e=await env();delete e.QIRA_RESEND_API_KEY;
 let r=await runCustomerReadyNotices(e,at,async()=>{throw Error("must not send")});
 assert.equal(r.configured,false);assert.equal(e.db.notice.status,"pending");
 e.QIRA_RESEND_API_KEY="re_test_sender";
 r=await runCustomerReadyNotices(e,at,async()=>({ok:false,status:503}));
 assert.equal(r.accepted,0);assert.equal(e.db.notice.status,"pending");
 assert.ok(e.db.notice.next_attempt_at>at);
 let calls=0;
 await runCustomerReadyNotices(e,at+30,async()=>{calls++;return okay();});assert.equal(calls,0);
 await runCustomerReadyNotices(e,at+500,async()=>{calls++;return okay();});assert.equal(calls,1);
 assert.equal(e.db.notice.status,"accepted");
});
test("180-day cleanup purges accepted delivery notices only",async()=>{
 const e=await env();await runCustomerReadyNotices(e,at,okay);
 await purgeCustomerNotices(e.db,at+181*86400);
 assert.equal(e.db.notice,null);
});
