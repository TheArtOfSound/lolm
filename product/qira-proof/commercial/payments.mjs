import {paymentIntentDigest,rememberEarlyReversal,reconcileEarlyReversals} from "./early_reversals.mjs";
// Signed, bounded Stripe webhook ingestion for Qira Proof.
// No raw event bodies, emails, billing details or credentials are persisted.
// A verified checkout event does not authorize access to private reports.
export const EXPECTED_LINK="plink_1UcLsTGz3eX0vCtEVB7vSsQI";
export const EXPECTED_TOTAL=29900;
const MAX_BYTES=65536;
function response(data,status=200){
 return new Response(JSON.stringify(data),{status,headers:{
  "content-type":"application/json; charset=utf-8","cache-control":"no-store",
  "x-content-type-options":"nosniff","referrer-policy":"no-referrer",
  "x-robots-tag":"noindex, nofollow"
 }});
}
async function boundedBody(request,maxBytes=MAX_BYTES){
 const declared=Number(request.headers.get("content-length"));
 if(Number.isFinite(declared)&&declared>maxBytes)throw Error("oversize");
 if(!request.body)return "";
 const reader=request.body.getReader(),pieces=[];let length=0;
 try{
  while(true){
   const entry=await reader.read();if(entry.done)break;
   length+=entry.value.byteLength;
   if(length>maxBytes){await reader.cancel();throw Error("oversize");}
   pieces.push(entry.value);
  }
 }finally{reader.releaseLock();}
 const merged=new Uint8Array(length);let index=0;
 for(const piece of pieces){merged.set(piece,index);index+=piece.byteLength;}
 return new TextDecoder("utf-8",{fatal:true}).decode(merged);
}
function sameHex(a,b){
 if(a.length!==b.length)return false;
 let diff=0;for(let i=0;i<a.length;i++)diff|=a.charCodeAt(i)^b.charCodeAt(i);
 return diff===0;
}
export async function verifyStripeSignature(secret,header,raw,now=Date.now()){
 if(typeof secret!=="string"||!secret.startsWith("whsec_")||typeof header!=="string"||header.length>2048)return false;
 const fragments=header.split(",").map(s=>s.trim());
 const stamp=fragments.find(s=>/^t=\d+$/.test(s))?.slice(2);
 if(!stamp)return false;
 const seconds=Number(stamp);
 if(!Number.isSafeInteger(seconds)||Math.abs(Math.floor(now/1000)-seconds)>300)return false;
 const possible=fragments.filter(s=>/^v1=[0-9a-fA-F]{64}$/.test(s)).map(s=>s.slice(3).toLowerCase());
 if(!possible.length)return false;
 const signingKey=await crypto.subtle.importKey("raw",new TextEncoder().encode(secret),{name:"HMAC",hash:"SHA-256"},false,["sign"]);
 const signature=await crypto.subtle.sign("HMAC",signingKey,new TextEncoder().encode(stamp+"."+raw));
 const calculated=Array.from(new Uint8Array(signature),b=>b.toString(16).padStart(2,"0")).join("");
 return possible.some(x=>sameHex(x,calculated));
}

function normalizeEmail(email){
 if(typeof email!=="string")return null;
 const v=email.trim().toLowerCase();
 if(v.length<5||v.length>254||/[\s<>\\]/.test(v)||!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v))return null;
 return v;
}
function repositoryName(name){
 if(typeof name!=="string"||name.length>150)return null;
 const v=name.trim(),parts=v.split("/");
 if(parts.length!==2||!/^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$/.test(parts[0]))return null;
 if(!/^[A-Za-z0-9_.-]{1,100}$/.test(parts[1])||parts[1]==="."||parts[1]===".."||parts[1].startsWith("."))return null;
 if(/(?:ghp_|github_pat_|gho_|ghu_|ghs_|ghr_|sk_live_|sk_test_)/i.test(v))return null;
 return v;
}
export async function buyerDigest(secret,email){
 const valid=normalizeEmail(email);
 if(!valid||typeof secret!=="string"||secret.length<32)return null;
 const key=await crypto.subtle.importKey("raw",new TextEncoder().encode(secret),{name:"HMAC",hash:"SHA-256"},false,["sign"]);
 const signature=await crypto.subtle.sign("HMAC",key,new TextEncoder().encode("qira-proof-buyer-v1:"+valid));
 return Array.from(new Uint8Array(signature),b=>b.toString(16).padStart(2,"0")).join("");
}
export async function submitVerifiedIntake(request,env){
 if(request.method!=="POST")return response({error:"method_not_allowed"},405);
 if(!env.QIRA_PROOF_ORDERS||!env.QIRA_ORDER_EMAIL_PEPPER)return response({error:"service_unavailable"},503);
 if(!request.headers.get("content-type")?.toLowerCase().startsWith("application/json"))return response({error:"invalid_request"},415);
 let input;
 try{input=JSON.parse(await boundedBody(request,4096));}catch{return response({error:"invalid_request"},400);}
 const sessionId=input?.session_id,email=normalizeEmail(input?.email),repo=repositoryName(input?.repository);
 if(!/^cs_live_[A-Za-z0-9]{10,255}$/.test(sessionId||"")||!email||!repo)return response({error:"invalid_request"},400);
 try{
  const record=await env.QIRA_PROOF_ORDERS.prepare("SELECT status,buyer_email_digest,refund_amount FROM qira_orders WHERE session_id=?").bind(sessionId).first();
  if(record?.status!=="paid"||Number(record?.refund_amount||0)>0||!record?.buyer_email_digest)return response({error:"payment_not_verified"},403);
  const digest=await buyerDigest(env.QIRA_ORDER_EMAIL_PEPPER,email);
  if(!digest||!sameHex(digest,record.buyer_email_digest))return response({error:"payment_not_verified"},403);
  const r=await env.QIRA_PROOF_ORDERS.prepare("INSERT OR IGNORE INTO qira_intakes(session_id,contact_email,repository,submitted_at,state) VALUES(?,?,?,?,'awaiting_authorization')").bind(sessionId,email,repo,Math.floor(Date.now()/1000)).run();
  if(r?.success===false)throw Error("write_failed");
  return response({received:true,state:"awaiting_authorization",existing:r?.meta?.changes===0});
 }catch{return response({error:"service_unavailable"},503);}
}

// Reversal events only affect an order whose Stripe PaymentIntent was previously
// linked to the exact Qira Payment Link by a signed Checkout event. Never use
// a customer email, amount alone or a shared Trend charge to identify an order.
function reversalOf(event){
 const d=event?.data?.object;
 if(event.type==="charge.refunded"){
  if(d?.object!=="charge"||d.livemode!==true||d.amount!==EXPECTED_TOTAL||
     d.currency!=="usd"||!Number.isInteger(d.amount_refunded)||
     d.amount_refunded<1||d.amount_refunded>EXPECTED_TOTAL)return null;
  if(!/^pi_[A-Za-z0-9]+$/.test(d.payment_intent||""))return null;
  return {paymentIntent:d.payment_intent,status:d.amount_refunded===EXPECTED_TOTAL?"refunded":"partial_refund",
          amountRefunded:d.amount_refunded};
 }
 if(event.type==="charge.dispute.created"||event.type==="charge.dispute.closed"){
  if(d?.object!=="dispute"||d.livemode!==true||d.amount!==EXPECTED_TOTAL||d.currency!=="usd"||
     !/^pi_[A-Za-z0-9]+$/.test(d.payment_intent||""))return null;
  if(event.type==="charge.dispute.closed"&&!["won","lost"].includes(d.status))return null;
  return {paymentIntent:d.payment_intent,status:event.type==="charge.dispute.created"?"disputed":"dispute_closed",
          outcome:event.type==="charge.dispute.closed"?d.status:null};
 }
 if(event.type==="refund.failed"){
  if(d?.object!=="refund"||d.livemode!==true||d.status!=="failed"||
     !Number.isInteger(d.amount)||d.amount<1||d.amount>EXPECTED_TOTAL||
     d.currency!=="usd"||!/^pi_[A-Za-z0-9]+$/.test(d.payment_intent||""))return null;
  return {paymentIntent:d.payment_intent,status:"refund_failed",amountRefunded:d.amount};
 }
 return null;
}
function sessionValid(s,event){
 return s?.object==="checkout.session"&&s.livemode===true&&s.mode==="payment"&&
 s.payment_link===EXPECTED_LINK&&s.amount_total===EXPECTED_TOTAL&&s.currency==="usd"&&
 /^cs_live_[A-Za-z0-9]{10,255}$/.test(s.id||"")&&
 (s.payment_intent==null||/^pi_[A-Za-z0-9]+$/.test(s.payment_intent))&&
 Number.isSafeInteger(event.created)&&event.created>0;
}
function statusOf(type,session){
 if(type==="checkout.session.async_payment_failed")return "failed";
 return session.payment_status==="paid"?"paid":"pending";
}
export async function handleStripeEvent(request,env){
 if(request.method!=="POST")return response({error:"method_not_allowed"},405);
 if(!env.QIRA_PROOF_ORDERS||!env.QIRA_STRIPE_WEBHOOK_SECRET)return response({error:"verification_unavailable"},503);
 if(!request.headers.get("content-type")?.toLowerCase().startsWith("application/json"))return response({error:"invalid_event"},415);
 let raw;
 try{raw=await boundedBody(request);}
 catch{return response({error:"invalid_event"},413);}
 if(!await verifyStripeSignature(env.QIRA_STRIPE_WEBHOOK_SECRET,request.headers.get("stripe-signature"),raw))return response({error:"invalid_signature"},400);
 let event;
 try{event=JSON.parse(raw);}catch{return response({error:"invalid_event"},400);}
 if(event?.object!=="event"||!/^evt_[A-Za-z0-9]+$/.test(event.id||"")||event.livemode!==true)return response({error:"invalid_event"},400);
 const reverse=["charge.refunded","charge.dispute.created","charge.dispute.closed","refund.failed"];
 if(reverse.includes(event.type)){
  const reversal=reversalOf(event);
  if(!reversal)return response({received:true,ignored:true});
  const now=Math.floor(Date.now()/1000);
  const intentHash=await paymentIntentDigest(env.QIRA_ORDER_EMAIL_PEPPER,reversal.paymentIntent);
  if(!intentHash)return response({error:"verification_unavailable"},503);
  try{
   const statements=[
    rememberEarlyReversal(env.QIRA_PROOF_ORDERS,event,reversal,intentHash,now),
    env.QIRA_PROOF_ORDERS.prepare("INSERT OR IGNORE INTO qira_events(event_id,event_type,event_created,received_at) SELECT ?,?,?,? WHERE EXISTS (SELECT 1 FROM qira_orders WHERE payment_intent_id=?)").bind(event.id,event.type,event.created,now,reversal.paymentIntent)
   ];
   if(reversal.status==="partial_refund"){
    // Do not misrepresent a partial refund as fully refunded. Never reactivate
    // intake after a partial refund, even if a paid Checkout event is replayed.
    statements.push(env.QIRA_PROOF_ORDERS.prepare("UPDATE qira_orders SET refund_amount=MAX(refund_amount,?),event_created=MAX(event_created,?),updated_at=? WHERE payment_intent_id=? AND status='paid'").bind(reversal.amountRefunded,event.created,now,reversal.paymentIntent));
   }else if(["refunded","disputed"].includes(reversal.status)){
    statements.push(env.QIRA_PROOF_ORDERS.prepare("UPDATE qira_orders SET status=?,event_created=MAX(event_created,?),updated_at=? WHERE payment_intent_id=? AND status NOT IN ('refunded','disputed')").bind(reversal.status,event.created,now,reversal.paymentIntent));
   }
   if(["partial_refund","dispute_closed","refund_failed"].includes(reversal.status)){
    // A closed dispute or a failed refund is a manual-reconciliation signal,
    // NOT proof that paid access should resume.
    statements.push(env.QIRA_PROOF_ORDERS.prepare("INSERT OR IGNORE INTO qira_adjustments(event_id,session_id,kind,amount_refunded,outcome,received_at) SELECT ?,session_id,?,?,?,? FROM qira_orders WHERE payment_intent_id=?").bind(event.id,reversal.status,reversal.amountRefunded||0,reversal.outcome||null,now,reversal.paymentIntent));
   }
   const result=await env.QIRA_PROOF_ORDERS.batch(statements);
   if(!Array.isArray(result)||result.some(x=>x.success===false))throw Error("reversal commit failed");
  }catch{return response({error:"verification_unavailable"},503);}
  return response({received:true});
 }
 const supported=["checkout.session.completed","checkout.session.async_payment_succeeded","checkout.session.async_payment_failed"];
 if(!supported.includes(event.type))return response({received:true,ignored:true});
 const session=event.data?.object;
 if(!sessionValid(session,event))return response({received:true,ignored:true});
 const now=Math.floor(Date.now()/1000);
 const status=statusOf(event.type,session);
 const emailDigest=await buyerDigest(env.QIRA_ORDER_EMAIL_PEPPER,session.customer_details?.email||session.customer_email);
 const intentHash=session.payment_intent?await paymentIntentDigest(env.QIRA_ORDER_EMAIL_PEPPER,session.payment_intent):null;
 if(session.payment_intent&&!intentHash)return response({error:"verification_unavailable"},503);
 const insertEvent="INSERT OR IGNORE INTO qira_events(event_id,event_type,event_created,received_at) VALUES(?,?,?,?)";
 const orderUpsert=[
  "INSERT INTO qira_orders(session_id,payment_link,payment_intent_id,status,amount_total,currency,event_created,paid_at,updated_at,buyer_email_digest)",
  "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET",
  "status=CASE WHEN qira_orders.status IN ('refunded','disputed') THEN qira_orders.status",
  "WHEN excluded.status='paid' THEN 'paid'",
  "WHEN qira_orders.status='paid' THEN 'paid'",
  "WHEN excluded.event_created>=qira_orders.event_created THEN excluded.status",
  "ELSE qira_orders.status END,",
  "payment_intent_id=COALESCE(qira_orders.payment_intent_id,excluded.payment_intent_id),",
  "buyer_email_digest=COALESCE(qira_orders.buyer_email_digest,excluded.buyer_email_digest),",
  "event_created=MAX(qira_orders.event_created,excluded.event_created),",
  "paid_at=COALESCE(qira_orders.paid_at,excluded.paid_at),",
  "updated_at=excluded.updated_at"
 ].join(" ");
 try{
  const queries=[
   env.QIRA_PROOF_ORDERS.prepare(insertEvent).bind(event.id,event.type,event.created,now),
   env.QIRA_PROOF_ORDERS.prepare(orderUpsert).bind(
    session.id,EXPECTED_LINK,session.payment_intent||null,status,EXPECTED_TOTAL,"usd",event.created,
    status==="paid"?now:null,now,emailDigest)
  ];
  if(intentHash)queries.push(...reconcileEarlyReversals(env.QIRA_PROOF_ORDERS,session.id,session.payment_intent,intentHash,now));
  const result=await env.QIRA_PROOF_ORDERS.batch(queries);
  if(!Array.isArray(result)||result.some(x=>x.success===false))throw Error("ledger commit failed");
 }catch{return response({error:"verification_unavailable"},503);}
 return response({received:true});
}
export async function checkoutStatus(db,sessionId){
 // A Checkout Session ID is a bearer lookup handle, NOT customer authentication.
 // Do not disclose identity, email, card details, receipt or private reports.
 if(!/^cs_live_[A-Za-z0-9]{10,255}$/.test(sessionId||""))return "unknown";
 if(!db)return "unavailable";
 try{
  const result=await db.prepare("SELECT status,refund_amount FROM qira_orders WHERE session_id=?").bind(sessionId).first();
  return result?.status==="paid"&&Number(result?.refund_amount||0)>0?"partially_refunded":
   ["paid","failed","refunded","disputed"].includes(result?.status)?result.status:"pending";
 }catch{return "unavailable";}
}
export async function readOrderIntakeStage(db,sessionId){
 if(!db||!/^cs_live_[A-Za-z0-9]{10,255}$/.test(sessionId||""))return {ready:false,state:null};
 try{
  const [order,intake]=await Promise.all([
   db.prepare("SELECT buyer_email_digest FROM qira_orders WHERE session_id=?").bind(sessionId).first(),
   db.prepare("SELECT state FROM qira_intakes WHERE session_id=?").bind(sessionId).first()
  ]);
  return {ready:typeof order?.buyer_email_digest==="string"&&/^[0-9a-f]{64}$/.test(order.buyer_email_digest),state:typeof intake?.state==="string"?intake.state:null};
 }catch{return {ready:false,state:null};}
}
export function checkoutBanner(status){
 const paid=status==="paid",refunded=status==="refunded",disputed=status==="disputed",partial=status==="partially_refunded";
 const heading=paid?"Stripe payment received.":refunded?"Payment refunded.":disputed?"Payment under dispute.":partial?"Partial refund recorded.":"Payment verification pending.";
 const detail=paid?
  "A Stripe-signed paid event matches the Qira Proof $299 order. This confirms a payment event only; Qira will still confirm purchaser identity, repository permission, scope and delivery.":
  refunded?"A signed Stripe refund event was recorded for this payment. The automated review request is unavailable. Contact Qira if you believe this is an error; do not make another payment solely to fix this status.":
  disputed?"Stripe has reported a payment dispute. The review request is on hold while the transaction is reconciled. Contact Qira support; do not pay again solely because of this message.":
  partial?"A partial refund was recorded for this order. Review intake is temporarily on hold while the transaction and service scope are reconciled. Contact Qira; do not purchase again to resolve this.":
  status==="unavailable"?"Automatic status lookup is unavailable. Use your Stripe receipt to contact Qira; this page cannot confirm payment.":
  "No matching signed paid event has been recorded yet. Some payment methods settle later. Check your Stripe receipt, refresh this page or contact Qira. Do not buy twice solely because this status is pending.";
 const icon=paid?"✓":(refunded||disputed||partial?"!":"◷");
 return '<div class="receipt-banner '+(paid?"confirmed":"pending")+'" role="status"><span aria-hidden="true" class="receipt-indicator">'+icon+'</span><div><strong>'+heading+'</strong><p>'+detail+'</p></div></div>';
}

export async function purgeOldOrderRows(db,atSeconds=Math.floor(Date.now()/1000)){
 // A paid customer's active intake or approved report cannot be removed simply
 // because the original payment happened over 180 days ago. Such deletion can
 // break a delivery promise or violate D1 foreign-key constraints.
 // Only event receipts, cancelled/stale intake and truly unreferenced orders
 // are eligible for this 180-day housekeeping. Stripe owns the financial record.
 if(!db||!Number.isSafeInteger(atSeconds)||atSeconds<180*86400)throw Error("retention_unavailable");
 const cutoff=atSeconds-180*86400;
 const actions=[
  db.prepare("DELETE FROM qira_events WHERE received_at < ?").bind(cutoff),
  // Do not remove a review still awaiting authorization, in progress or
  // delivered. Cancelled, unfulfilled requests alone are disposable.
  db.prepare("DELETE FROM qira_intakes WHERE submitted_at < ? AND state='cancelled' AND NOT EXISTS (SELECT 1 FROM qira_deliverables d WHERE d.session_id=qira_intakes.session_id)").bind(cutoff),
  // Report and notice tables reference the order. Guard every dependent
  // record, even if foreign keys are disabled in another D1 environment.
  db.prepare("DELETE FROM qira_orders WHERE updated_at < ? AND NOT EXISTS (SELECT 1 FROM qira_intakes i WHERE i.session_id=qira_orders.session_id) AND NOT EXISTS (SELECT 1 FROM qira_deliverables d WHERE d.session_id=qira_orders.session_id) AND NOT EXISTS (SELECT 1 FROM qira_report_challenges c WHERE c.session_id=qira_orders.session_id) AND NOT EXISTS (SELECT 1 FROM qira_customer_notices n WHERE n.session_id=qira_orders.session_id)").bind(cutoff)
 ];
 const result=await db.batch(actions);
 if(!Array.isArray(result)||result.some(x=>x.success===false))throw Error("retention_write_failed");
 return true;
}
