import test from "node:test";
import assert from "node:assert/strict";
import {createHmac,webcrypto} from "node:crypto";
import worker from "../commercial/landing.mjs";
import {handleStripeEvent,buyerDigest,submitVerifiedIntake,readOrderIntakeStage,EXPECTED_LINK,EXPECTED_TOTAL} from "../commercial/payments.mjs";
if(!globalThis.crypto)globalThis.crypto=webcrypto;
const origin="https://proof.imagineqira.com",sessionId="cs_live_0123456789abcdefghijklmnop",signing="whsec_test_only_secure123456",pepper="abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789";
class MockD1{
 constructor(){this.orders=new Map();this.events=new Map();this.intakes=new Map();}
 prepare(sql){const db=this;return {bind(...args){return {sql,args,
 async first(){
  const id=args[0];
  if(sql.includes("FROM qira_intakes"))return db.intakes.get(id)||null;
  if(sql.includes("FROM qira_orders"))return db.orders.get(id)||null;
  throw Error("unexpected select");
 },
 async run(){
  if(!sql.startsWith("INSERT OR IGNORE INTO qira_intakes"))throw Error("unexpected run");
  const [session_id,contact_email,repository,submitted_at]=args;
  if(db.intakes.has(session_id))return {success:true,meta:{changes:0}};
  db.intakes.set(session_id,{session_id,contact_email,repository,submitted_at,state:"awaiting_authorization"});
  return {success:true,meta:{changes:1}};
 }
 };}};}
 async batch(steps){
  for(const step of steps){
   if(step.sql.startsWith("INSERT OR IGNORE INTO qira_events"))this.events.set(step.args[0],step.args);
   else if(step.sql.startsWith("INSERT INTO qira_orders")){
    const [id,link,intent,status,amount,currency,created,paidAt,updated,digest]=step.args;
    this.orders.set(id,{status,buyer_email_digest:digest,payment_link:link,amount_total:amount,currency});
   }else throw Error("unsupported batch");
  }
  return steps.map(()=>({success:true}));
 }
}
function signedWebhook(email="customer@example.com"){
 const event={id:"evt_paid987654321",object:"event",livemode:true,type:"checkout.session.completed",
  created:Math.floor(Date.now()/1000),data:{object:{object:"checkout.session",id:sessionId,livemode:true,mode:"payment",
  payment_link:EXPECTED_LINK,amount_total:EXPECTED_TOTAL,currency:"usd",payment_intent:"pi_test123456789",
  payment_status:"paid",customer_details:{email}}}};
 const payload=JSON.stringify(event),timestamp=String(Math.floor(Date.now()/1000));
 return new Request(origin+"/api/stripe/webhook",{method:"POST",headers:{"content-type":"application/json",
  "stripe-signature":"t="+timestamp+",v1="+createHmac("sha256",signing).update(timestamp+"."+payload).digest("hex")},body:payload});
}
const env=db=>({QIRA_PROOF_ORDERS:db,QIRA_STRIPE_WEBHOOK_SECRET:signing,QIRA_ORDER_EMAIL_PEPPER:pepper});
const submission=(email="customer@example.com",repository="owner/my-repo")=>new Request(origin+"/api/orders/intake",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({session_id:sessionId,email,repository})});

test("signed paid event stores only a keyed email digest, not card or email details",async()=>{
 const db=new MockD1();assert.equal((await handleStripeEvent(signedWebhook(),env(db))).status,200);
 const record=db.orders.get(sessionId);
 assert.match(record.buyer_email_digest,/^[0-9a-f]{64}$/);
 assert.equal(record.buyer_email_digest,await buyerDigest(pepper,"CUSTOMER@example.com"));
 assert.doesNotMatch(JSON.stringify(record),/customer@example.com|whsec_|sk_live_|card_number/);
 assert.equal(record.payment_link,EXPECTED_LINK);
});
test("successful paid-intake submission requires matching checkout email, then persists only required details",async()=>{
 const db=new MockD1();await handleStripeEvent(signedWebhook(),env(db));
 const response=await submitVerifiedIntake(submission("CUSTOMER@example.com","owner/my-repo"),env(db));
 assert.equal(response.status,200);
 assert.deepEqual(await response.json(),{received:true,state:"awaiting_authorization",existing:false});
 const record=db.intakes.get(sessionId);
 assert.equal(record.contact_email,"customer@example.com");
 assert.equal(record.repository,"owner/my-repo");
 const stage=await readOrderIntakeStage(db,sessionId);
 assert.deepEqual(stage,{ready:true,state:"awaiting_authorization"});
 const again=await submitVerifiedIntake(submission("customer@example.com","owner/other-repo"),env(db));
 assert.equal(again.status,200);
 assert.equal((await again.json()).existing,true);
 assert.equal(db.intakes.get(sessionId).repository,"owner/my-repo");
});
test("unknown, pending, or email-mismatched orders cannot submit or hijack intake",async()=>{
 const db=new MockD1();
 assert.equal((await submitVerifiedIntake(submission(),env(db))).status,403);
 await handleStripeEvent(signedWebhook(),env(db));
 assert.equal((await submitVerifiedIntake(submission("attacker@example.com"),env(db))).status,403);
 assert.equal(db.intakes.size,0);
 db.orders.get(sessionId).status="pending";
 assert.equal((await submitVerifiedIntake(submission(),env(db))).status,403);
});
test("invalid repository, secrets, malformed JSON, missing pepper and oversized requests reject safely",async()=>{
 const db=new MockD1();await handleStripeEvent(signedWebhook(),env(db));
 for(const repo of ["bad/repo/tree/main","https://github.com/owner/repo","ghp_secret/key","../../repo","owner/.."]){
  const r=await submitVerifiedIntake(submission("customer@example.com",repo),env(db));
  assert.equal(r.status,400,repo);
 }
 const noPepper=await submitVerifiedIntake(submission(),{QIRA_PROOF_ORDERS:db});
 assert.equal(noPepper.status,503);
 const oversize=await submitVerifiedIntake(new Request(origin+"/api/orders/intake",{method:"POST",headers:{"content-type":"application/json"},body:"x".repeat(5000)}),env(db));
 assert.equal(oversize.status,400);
 assert.equal(db.intakes.size,0);
});
test("paid server-rendered page offers direct intake and shows recorded status after submission",async()=>{
 const db=new MockD1();await handleStripeEvent(signedWebhook(),env(db));
 const url=origin+"/start-review?session_id="+sessionId;
 const first=await worker.fetch(new Request(url),env(db));
 assert.equal(first.status,200);
 const h=await first.text();
 assert.match(h,/data-verified-checkout="true"/);
 assert.match(h,/Send review request/);
 assert.match(h,/src-none-unreachable-nevermatch|fetch\("\/api\/orders\/intake"/);
 assert.match(first.headers.get("content-security-policy"),/connect-src 'self'/);
 assert.equal(first.headers.get("x-robots-tag"),"noindex, follow");
 const r=await worker.fetch(submission(),env(db));
 assert.equal(r.status,200);
 const after=await (await worker.fetch(new Request(url),env(db))).text();
 assert.match(after,/Your request is in/);
 assert.doesNotMatch(after,/data-verified-checkout="true"/);
});
test("unverified or unmatched orders retain manual fallback without pretending payment succeeded",async()=>{
 const db=new MockD1();
 const pending=await (await worker.fetch(new Request(origin+"/start-review?session_id="+sessionId),env(db))).text();
 assert.match(pending,/Payment verification pending/);
 assert.doesNotMatch(pending,/data-verified-checkout="true"/);
 const noBindings=await worker.fetch(submission(),{});
 assert.equal(noBindings.status,503);
});
