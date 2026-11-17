import test from "node:test";
import assert from "node:assert/strict";
import {createHmac,webcrypto} from "node:crypto";
import worker from "../commercial/landing.mjs";
import {verifyStripeSignature,handleStripeEvent,checkoutStatus,EXPECTED_LINK,EXPECTED_TOTAL} from "../commercial/payments.mjs";
if(!globalThis.crypto)globalThis.crypto=webcrypto;
const secret="whsec_test_secret_qira_proof_not_real";
const url="https://proof.imagineqira.com/api/stripe/webhook";
const base=Date.now();
const sessionId="cs_live_1234567890abcdefghijklmnop";
const order={
 object:"checkout.session",id:sessionId,livemode:true,mode:"payment",
 payment_link:EXPECTED_LINK,amount_total:EXPECTED_TOTAL,currency:"usd",
 payment_intent:"pi_proof0123456789",payment_status:"paid",status:"complete"
};
const event=(type="checkout.session.completed",overrides={})=>({
 id:"evt_test0123456789",object:"event",livemode:true,type,
 created:Math.floor(Date.now()/1000),
 data:{object:{...order,...overrides}}
});
const makeRequest=(payload,extra={})=>{
 const text=typeof payload==="string"?payload:JSON.stringify(payload);
 const timestamp=String(extra.timestamp??Math.floor(Date.now()/1000));
 const signature=createHmac("sha256",extra.secret||secret).update(timestamp+"."+text).digest("hex");
 return new Request(url,{
  method:"POST",headers:{"content-type":"application/json", "stripe-signature":extra.header||("t="+timestamp+",v1="+signature)},
  body:text
 });
};
class MemoryD1 {
 constructor(){this.orders=new Map();this.events=new Map();this.failBatch=false;}
 prepare(sql){
  const db=this;
  return {bind(...args){return {sql,args,
   async first(){if(!sql.includes("SELECT status"))throw Error("unsupported mock select");const row=db.orders.get(args[0]);return row?{status:row.status}:null;}
  };}};
 }
 async batch(steps){
  if(this.failBatch)throw Error("injected sqlite failure");
  for(const step of steps){
   if(step.sql.includes("INSERT OR IGNORE INTO qira_events")&&step.sql.includes("SELECT r.event_id")){
    // No buffered reversals exist in these isolated checkout-only tests.
   }else if(step.sql.includes("INSERT OR IGNORE INTO qira_events")){
    const [id,type,created,received]=step.args;
    if(!this.events.has(id))this.events.set(id,{type,created,received});
   }else if(step.sql.includes("INSERT INTO qira_orders")){
    const [id,link,intent,state,amount,currency,created,paidAt,updated]=step.args;
    const old=this.orders.get(id);
    const next=old?{
     ...old,status:state==="paid"?"paid":old.status==="paid"?"paid":created>=old.created?state:old.status,
     created:Math.max(old.created,created),paidAt:old.paidAt||paidAt,updated,
    }:{link,intent,status:state,amount,currency,created,paidAt,updated};
    this.orders.set(id,next);
   }else if(step.sql.startsWith("UPDATE qira_orders SET")&&step.sql.includes("qira_early_reversals")){
    // The synthetic merchant has no pre-checkout reversals in this fixture.
   }else if(step.sql.includes("INSERT OR IGNORE INTO qira_adjustments")&&step.sql.includes("FROM qira_early_reversals")){
    // No matched early adjustment event.
   }else throw Error("unexpected SQL "+step.sql.slice(0,70));
  }
  return steps.map(()=>({success:true}));
 }
}
const env=db=>({QIRA_PROOF_ORDERS:db,QIRA_STRIPE_WEBHOOK_SECRET:secret,QIRA_ORDER_EMAIL_PEPPER:"test_checkout_email_key_0123456789abcdef0123456789abcdef"});
test("HMAC verifier accepts genuine fresh payload and rejects altered/timed out signatures",async()=>{
 const data=JSON.stringify(event());const signed=makeRequest(data);
 assert.equal(await verifyStripeSignature(secret,signed.headers.get("stripe-signature"),data),true);
 assert.equal(await verifyStripeSignature(secret,signed.headers.get("stripe-signature"),data+" "),false);
 assert.equal(await verifyStripeSignature(secret,"t=1,v1="+"0".repeat(64),data),false);
 assert.equal(await verifyStripeSignature(secret,"t=bogus,v1="+"a".repeat(64),data),false);
 assert.equal(await verifyStripeSignature(secret,"",data),false);
 assert.equal(await verifyStripeSignature("garbage",signed.headers.get("stripe-signature"),data),false);
});
test("only signed paid event for the exact Trend product and link enters minimal ledger",async()=>{
 const db=new MemoryD1(),evt=event();
 const r=await handleStripeEvent(makeRequest(evt),env(db));assert.equal(r.status,200);
 assert.deepEqual(await r.json(),{received:true});
 assert.equal(db.orders.get(sessionId)?.status,"paid");
 assert.equal(db.events.size,1);
 assert.equal(await checkoutStatus(db,sessionId),"paid");
 const persisted=JSON.stringify([...db.orders.values()])+JSON.stringify([...db.events.values()]);
 assert.doesNotMatch(persisted,/@|secret|card|customer_details/i);
 const repeat=await handleStripeEvent(makeRequest(evt),env(db));
 assert.equal(repeat.status,200);assert.equal(db.events.size,1);assert.equal(db.orders.size,1);
});
test("provider signature is mandatory, including for internally valid event bodies",async()=>{
 const db=new MemoryD1();const req=makeRequest(event(),{header:"t=1,v1="+"0".repeat(64)});
 const response=await worker.fetch(req,env(db));
 assert.equal(response.status,400);
 assert.equal(db.orders.size,0);
 assert.equal(db.events.size,0);
 assert.doesNotMatch(await response.text(),/whsec_/);
});
test("non-Qira link, changed price, wrong currency, or test-mode events never create orders",async()=>{
 const sample=[
 event("checkout.session.completed",{payment_link:"plink_other"}),
 event("checkout.session.completed",{amount_total:30000}),
 event("checkout.session.completed",{currency:"cad"}),
 event("checkout.session.completed",{mode:"subscription"}),
 event("checkout.session.completed",{livemode:false}),
 {...event(),livemode:false}
 ];
 for(let i=0;i<sample.length;i++){
  const db=new MemoryD1();
  const r=await handleStripeEvent(makeRequest(sample[i]),env(db));
  assert.ok([200,400].includes(r.status));
  assert.equal(db.orders.size,0,"Rejected case #"+i);
 }
});
test("pending payments are not paid and a stale failure cannot downgrade an existing paid order",async()=>{
 const db=new MemoryD1();const initial=event("checkout.session.completed",{payment_status:"unpaid"});
 assert.equal((await handleStripeEvent(makeRequest(initial),env(db))).status,200);
 assert.equal(db.orders.get(sessionId).status,"pending");
 const paid=event("checkout.session.async_payment_succeeded",{payment_status:"paid"});paid.id="evt_success012345";
 paid.created=initial.created+10;
 assert.equal((await handleStripeEvent(makeRequest(paid),env(db))).status,200);
 assert.equal(db.orders.get(sessionId).status,"paid");
 const failed=event("checkout.session.async_payment_failed",{payment_status:"unpaid"});failed.id="evt_failed012345";
 failed.created=initial.created+1;
 assert.equal((await handleStripeEvent(makeRequest(failed),env(db))).status,200);
 assert.equal(db.orders.get(sessionId).status,"paid");
});
test("datastore outages are visible to Stripe so provider retries event delivery",async()=>{
 const db=new MemoryD1();db.failBatch=true;
 const result=await handleStripeEvent(makeRequest(event()),env(db));
 assert.equal(result.status,503);
 assert.deepEqual(await result.json(),{error:"verification_unavailable"});
 assert.equal(db.orders.size,0);
});
test("webhook cannot be accidentally opened via GET and does not accept missing bindings",async()=>{
 const get=await worker.fetch(new Request(url,{method:"GET"}),env(new MemoryD1()));
 assert.equal(get.status,405);
 const missing=await worker.fetch(makeRequest(event()),{});
 assert.equal(missing.status,503);
 const wrongBody=await worker.fetch(new Request(url,{method:"POST",headers:{"content-type":"text/plain"},body:"payload"}),env(new MemoryD1()));
 assert.equal(wrongBody.status,415);
});
test("large payload and unsupported events are bounded and ignored",async()=>{
 const db=new MemoryD1();
 const oversize=await handleStripeEvent(makeRequest("x".repeat(70000)),env(db));assert.equal(oversize.status,413);
 const other=event("customer.created");
 const r=await handleStripeEvent(makeRequest(other),env(db));
 assert.equal(r.status,200);assert.deepEqual(await r.json(),{received:true,ignored:true});
 assert.equal(db.orders.size,0);
});
test("post-checkout page reports verified payment without treating it as customer authentication",async()=>{
 const db=new MemoryD1();
 await handleStripeEvent(makeRequest(event()),env(db));
 const request=new Request("https://proof.imagineqira.com/start-review?session_id="+sessionId);
 const page=await worker.fetch(request,env(db));
 assert.equal(page.status,200);
 const html=await page.text();
 assert.match(html,/Stripe payment received/);
 assert.match(html,/Qira will still confirm purchaser identity/);
 assert.match(html,/value="cs_live_1234567890abcdefghijklmnop"/);
 assert.match(html,/does not verify payment or grant an entitlement/);
 assert.equal(page.headers.get("cache-control"),"no-store");
 assert.equal(page.headers.get("referrer-policy"),"no-referrer");
 assert.doesNotMatch(html,/customer_details/);
});
test("unknown receipt returns safe pending state and old intake remains intact",async()=>{
 const db=new MemoryD1();
 const request=new Request("https://proof.imagineqira.com/start-review?session_id="+sessionId);
 const page=await worker.fetch(request,env(db));
 assert.match(await page.text(),/Payment verification pending/);
 const defaultIntake=await worker.fetch(new Request("https://proof.imagineqira.com/start-review"),env(db));
 const html=await defaultIntake.text();
 assert.doesNotMatch(html,/Stripe payment received/);
 assert.match(html,/Compose email to Qira/);
});
