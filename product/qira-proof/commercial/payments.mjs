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
async function boundedBody(request){
 const declared=Number(request.headers.get("content-length"));
 if(Number.isFinite(declared)&&declared>MAX_BYTES)throw Error("oversize");
 if(!request.body)return "";
 const reader=request.body.getReader(),pieces=[];let length=0;
 try{
  while(true){
   const entry=await reader.read();if(entry.done)break;
   length+=entry.value.byteLength;
   if(length>MAX_BYTES){await reader.cancel();throw Error("oversize");}
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
 const supported=["checkout.session.completed","checkout.session.async_payment_succeeded","checkout.session.async_payment_failed"];
 if(!supported.includes(event.type))return response({received:true,ignored:true});
 const session=event.data?.object;
 if(!sessionValid(session,event))return response({received:true,ignored:true});
 const now=Math.floor(Date.now()/1000);
 const status=statusOf(event.type,session);
 const insertEvent="INSERT OR IGNORE INTO qira_events(event_id,event_type,event_created,received_at) VALUES(?,?,?,?)";
 const orderUpsert=[
  "INSERT INTO qira_orders(session_id,payment_link,payment_intent_id,status,amount_total,currency,event_created,paid_at,updated_at)",
  "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET",
  "status=CASE WHEN excluded.status='paid' THEN 'paid'",
  "WHEN qira_orders.status='paid' THEN 'paid'",
  "WHEN excluded.event_created>=qira_orders.event_created THEN excluded.status",
  "ELSE qira_orders.status END,",
  "payment_intent_id=COALESCE(qira_orders.payment_intent_id,excluded.payment_intent_id),",
  "event_created=MAX(qira_orders.event_created,excluded.event_created),",
  "paid_at=COALESCE(qira_orders.paid_at,excluded.paid_at),",
  "updated_at=excluded.updated_at"
 ].join(" ");
 try{
  const queries=[
   env.QIRA_PROOF_ORDERS.prepare(insertEvent).bind(event.id,event.type,event.created,now),
   env.QIRA_PROOF_ORDERS.prepare(orderUpsert).bind(
    session.id,EXPECTED_LINK,session.payment_intent||null,status,EXPECTED_TOTAL,"usd",event.created,
    status==="paid"?now:null,now)
  ];
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
  const result=await db.prepare("SELECT status FROM qira_orders WHERE session_id=?").bind(sessionId).first();
  return result?.status==="paid"?"paid":result?.status==="failed"?"failed":"pending";
 }catch{return "unavailable";}
}
export function checkoutBanner(status){
 const paid=status==="paid";
 const heading=paid?"Stripe payment received.":"Payment verification pending.";
 const detail=paid?
  "A Stripe-signed paid event matches the Qira Proof $299 order. This confirms a payment event only; Qira will still confirm purchaser identity, repository permission, scope and delivery.":
  status==="unavailable"?"Automatic status lookup is unavailable. Use your Stripe receipt to contact Qira; this page cannot confirm payment.":
  "No matching signed paid event has been recorded yet. Some payment methods settle later. Check your Stripe receipt, refresh this page or contact Qira. Do not buy twice solely because this status is pending.";
 const icon=paid?"✓":"◷";
 return '<div class="receipt-banner '+(paid?"confirmed":"pending")+'" role="status"><span aria-hidden="true" class="receipt-indicator">'+icon+'</span><div><strong>'+heading+'</strong><p>'+detail+'</p></div></div>';
}
