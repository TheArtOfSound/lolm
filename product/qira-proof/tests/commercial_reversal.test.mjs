import test from "node:test";
import assert from "node:assert/strict";
import {createHmac,webcrypto} from "node:crypto";
import {handleStripeEvent,checkoutStatus,checkoutBanner,submitVerifiedIntake,EXPECTED_LINK,EXPECTED_TOTAL} from "../commercial/payments.mjs";
if(!globalThis.crypto)globalThis.crypto=webcrypto;
const secret="whsec_qira_test_only_not_live",pepper="test_local_key_0123456789abcdef0123456789abcdef012345";
const sid="cs_live_qira0123456789abcdef",pi="pi_qira0123456789abcdef";
const now=()=>Math.floor(Date.now()/1000);
class Ledger{
 constructor(){this.orders=new Map();this.events=new Map();this.adjustments=new Map();this.early=new Map();}
 prepare(sql){return {bind:(...args)=>({sql,args,first:async()=>{
  const r=this.orders.get(args[0]);
  if(sql.includes("SELECT status,buyer_email_digest"))return r||null;
  if(sql.includes("SELECT status"))return r?{status:r.status,refund_amount:r.refund_amount}:null;
  throw Error("unsupported SELECT");
 }})};}
 async batch(ops){
  for(const o of ops){
   if(o.sql.startsWith("INSERT OR IGNORE INTO qira_early_reversals")){
    const [id,digest,kind,amount,outcome,created,received]=o.args;
    if(!this.early.has(id))this.early.set(id,{digest,kind,amount,outcome,created,received});
   }else if(o.sql.startsWith("INSERT OR IGNORE INTO qira_events")&&o.sql.includes("FROM qira_early_reversals")){
    const [intent,digest]=o.args;
    if([...this.orders.values()].some(v=>v.intent===intent))
     for(const [id,r]of this.early)if(r.digest===digest)this.events.set(id,r.kind);
   }else if(o.sql.startsWith("INSERT OR IGNORE INTO qira_events")){
    if(!this.events.has(o.args[0]))this.events.set(o.args[0],o.args[1]);
   }else if(o.sql.startsWith("INSERT INTO qira_orders")){
    const [id,link,intent,status,amount,currency,created,paidAt,updated,digest]=o.args;
    const before=this.orders.get(id);
    if(before){
     before.status=["refunded","disputed"].includes(before.status)?before.status:
      status==="paid"?"paid":before.status==="paid"?"paid":created>=before.created?status:before.status;
    }else this.orders.set(id,{link,intent,status,amount,currency,created,paidAt,updated,buyer_email_digest:digest,refund_amount:0});
   }else if(o.sql.startsWith("UPDATE qira_orders")&&o.sql.includes("qira_early_reversals")){
    const [digest,,,updated,sessionId,intent]=o.args,order=this.orders.get(sessionId);
    if(order&&order.intent===intent){
     const markers=[...this.early.values()].filter(x=>x.digest===digest);
     if(!["refunded","disputed"].includes(order.status)){
      if(markers.some(x=>x.kind==="disputed"||x.kind==="dispute_closed"))order.status="disputed";
      else if(markers.some(x=>x.kind==="refunded"))order.status="refunded";
     }
     for(const r of markers)if(["partial_refund","refund_failed"].includes(r.kind))order.refund_amount=Math.max(order.refund_amount,r.amount);
     order.updated=updated;
    }
   }else if(o.sql.startsWith("UPDATE qira_orders")){
    const [value,created,updated,intent]=o.args;
    for(const order of this.orders.values())if(order.intent===intent&&!["refunded","disputed"].includes(order.status)){
     if(o.sql.includes("refund_amount=MAX"))order.refund_amount=Math.max(order.refund_amount,Number(value));
     else order.status=value;
     order.created=Math.max(order.created,created);order.updated=updated;
    }
   }else if(o.sql.startsWith("INSERT OR IGNORE INTO qira_adjustments")&&o.sql.includes("FROM qira_early_reversals")){
    const [intent,digest]=o.args;
    for(const [sessionId,order] of this.orders)if(order.intent===intent)
     for(const [eventId,r]of this.early)if(r.digest===digest&&["partial_refund","dispute_closed","refund_failed"].includes(r.kind))
      this.adjustments.set(eventId,{sessionId,kind:r.kind,amount:r.amount,outcome:r.outcome,received:r.received});
   }else if(o.sql.startsWith("INSERT OR IGNORE INTO qira_adjustments")){
    const [eventId,kind,amount,outcome,received,intent]=o.args;
    for(const [sessionId,order] of this.orders)if(order.intent===intent)this.adjustments.set(eventId,{sessionId,kind,amount,outcome,received});
   }else throw Error("unrecognized SQL "+o.sql.slice(0,60));
  }
  return ops.map(()=>({success:true}));
 }
}
const environment=db=>({QIRA_PROOF_ORDERS:db,QIRA_STRIPE_WEBHOOK_SECRET:secret,QIRA_ORDER_EMAIL_PEPPER:pepper});
let index=0;
function sign(type,object){
 const evt={id:"evt_reversal"+String(++index).padStart(12,"0"),object:"event",livemode:true,created:now(),type,data:{object}};
 const body=JSON.stringify(evt),t=String(now()),v1=createHmac("sha256",secret).update(t+"."+body).digest("hex");
 return new Request("https://proof.imagineqira.com/api/stripe/webhook",{method:"POST",headers:{"content-type":"application/json","stripe-signature":"t="+t+",v1="+v1},body});
}
const paid=()=>({object:"checkout.session",id:sid,livemode:true,mode:"payment",payment_link:EXPECTED_LINK,amount_total:EXPECTED_TOTAL,currency:"usd",payment_intent:pi,payment_status:"paid",customer_details:{email:"buyer@example.org"}});
const refund=(intent=pi,amountRefunded=EXPECTED_TOTAL)=>({object:"charge",livemode:true,payment_intent:intent,amount:EXPECTED_TOTAL,amount_refunded:amountRefunded,refunded:amountRefunded===EXPECTED_TOTAL,currency:"usd"});
const dispute=(intent=pi)=>({object:"dispute",livemode:true,payment_intent:intent,amount:EXPECTED_TOTAL,currency:"usd"});
test("a genuine full refund blocks intake and survives a replayed paid Checkout event",async()=>{
 const db=new Ledger(),env=environment(db);
 assert.equal((await handleStripeEvent(sign("checkout.session.completed",paid()),env)).status,200);
 assert.equal((await handleStripeEvent(sign("charge.refunded",refund()),env)).status,200);
 assert.equal(await checkoutStatus(db,sid),"refunded");
 assert.match(checkoutBanner("refunded"),/Payment refunded/);
 assert.equal((await handleStripeEvent(sign("checkout.session.completed",paid()),env)).status,200);
 assert.equal(await checkoutStatus(db,sid),"refunded");
 const intake=new Request("https://proof.imagineqira.com/api/orders/intake",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({session_id:sid,email:"buyer@example.org",repository:"owner/repo"})});
 assert.equal((await submitVerifiedIntake(intake,env)).status,403);
});
test("signed payment dispute puts matched Qira order on hold",async()=>{
 const db=new Ledger(),env=environment(db);
 await handleStripeEvent(sign("checkout.session.completed",paid()),env);
 assert.equal((await handleStripeEvent(sign("charge.dispute.created",dispute()),env)).status,200);
 assert.equal(await checkoutStatus(db,sid),"disputed");
 assert.match(checkoutBanner("disputed"),/Payment under dispute/);
});
test("unrelated Trend transactions cannot reverse a Qira order",async()=>{
 const db=new Ledger(),env=environment(db);
 await handleStripeEvent(sign("checkout.session.completed",paid()),env);
 for(const e of [
  sign("charge.refunded",refund("pi_unrelated0123456")),
  sign("charge.dispute.created",dispute("pi_unrelated0123456")),
  sign("charge.dispute.created",{...dispute(),amount:25000}),
  sign("charge.refunded",{...refund(),currency:"eur"}),
  sign("charge.refunded",{...refund(),livemode:false})
 ]){
  assert.equal((await handleStripeEvent(e,env)).status,200);
  assert.equal(await checkoutStatus(db,sid),"paid");
 }
 assert.equal(db.orders.size,1);
});
test("unsigned reversal fails closed",async()=>{
 const db=new Ledger(),env=environment(db);
 await handleStripeEvent(sign("checkout.session.completed",paid()),env);
 const req=sign("charge.refunded",refund());
 req.headers.set("stripe-signature","t=1,v1="+"a".repeat(64));
 assert.equal((await handleStripeEvent(req,env)).status,400);
 assert.equal(await checkoutStatus(db,sid),"paid");
});

test("partial refund freezes paid intake without presenting a full refund",async()=>{
 const db=new Ledger(),env=environment(db);
 await handleStripeEvent(sign("checkout.session.completed",paid()),env);
 assert.equal((await handleStripeEvent(sign("charge.refunded",refund(pi,12000)),env)).status,200);
 assert.equal(await checkoutStatus(db,sid),"partially_refunded");
 assert.equal(db.orders.get(sid).refund_amount,12000);
 assert.equal(db.adjustments.size,1);
 assert.match(checkoutBanner("partially_refunded"),/Partial refund recorded/);
 assert.equal((await handleStripeEvent(sign("checkout.session.completed",paid()),env)).status,200);
 assert.equal(await checkoutStatus(db,sid),"partially_refunded");
 const request=new Request("https://proof.imagineqira.com/api/orders/intake",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({session_id:sid,email:"buyer@example.org",repository:"owner/repo"})});
 assert.equal((await submitVerifiedIntake(request,env)).status,403);
});
test("dispute closing and refund failure require operator review without re-enabling intake",async()=>{
 const db=new Ledger(),env=environment(db);
 await handleStripeEvent(sign("checkout.session.completed",paid()),env);
 await handleStripeEvent(sign("charge.dispute.created",dispute()),env);
 assert.equal((await handleStripeEvent(sign("charge.dispute.closed",{...dispute(),status:"won"}),env)).status,200);
 assert.equal(await checkoutStatus(db,sid),"disputed");
 assert.equal(db.adjustments.size,1);
 assert.equal((await handleStripeEvent(sign("refund.failed",{object:"refund",status:"failed",livemode:true,amount:29900,currency:"usd",payment_intent:pi}),env)).status,200);
 assert.equal(db.adjustments.size,2);
 assert.equal(await checkoutStatus(db,sid),"disputed");
});

test("a signed full refund arriving before Checkout prevents later paid entitlements",async()=>{
 const db=new Ledger(),env=environment(db);
 assert.equal((await handleStripeEvent(sign("charge.refunded",refund()),env)).status,200);
 assert.equal(db.orders.size,0);
 assert.equal(db.early.size,1);
 assert.equal((await handleStripeEvent(sign("checkout.session.completed",paid()),env)).status,200);
 assert.equal(await checkoutStatus(db,sid),"refunded");
 const intake=new Request("https://proof.imagineqira.com/api/orders/intake",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({session_id:sid,email:"buyer@example.org",repository:"owner/repo"})});
 assert.equal((await submitVerifiedIntake(intake,env)).status,403);
});
test("pre-checkout partial refunds and disputed payments remain on hold",async()=>{
 for(const [type,body,expected]of [
  ["charge.refunded",refund(pi,10000),"partially_refunded"],
  ["charge.dispute.created",dispute(),"disputed"],
  ["charge.dispute.closed",{...dispute(),status:"won"},"disputed"]
 ]){
  const db=new Ledger(),env=environment(db);
  assert.equal((await handleStripeEvent(sign(type,body),env)).status,200);
  assert.equal((await handleStripeEvent(sign("checkout.session.completed",paid()),env)).status,200);
  assert.equal(await checkoutStatus(db,sid),expected);
 }
});
test("an unrelated Trend payment intent cannot attach its earlier reversal to Qira checkout",async()=>{
 const db=new Ledger(),env=environment(db);
 await handleStripeEvent(sign("charge.refunded",refund("pi_unrelated0192837465")),env);
 await handleStripeEvent(sign("checkout.session.completed",paid()),env);
 assert.equal(await checkoutStatus(db,sid),"paid");
 assert.equal(db.orders.size,1);
 assert.equal(db.early.size,1);
});
