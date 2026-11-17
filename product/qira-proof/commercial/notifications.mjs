// Minimal, idempotent operations notifications for Qira Proof.
// No customer email, repository name, source code, or raw Stripe event leaves D1.
// Provider credentials are protected Cloudflare secret_text bindings.
const DAY=86400;
const DESTINATION="bryanleonard@imagineqira.com";
const FROM="Qira Proof Operations <notifications@imagineqira.com>";
const labels={
  paid:"New verified Qira Proof payment",
  failed:"Qira Proof payment failure",
  refunded:"Qira Proof full refund",
  disputed:"Qira Proof payment dispute",
  intake:"New Qira Proof review intake",
  partial_refund:"Qira Proof partial refund — manual reconciliation",
  dispute_closed:"Qira Proof dispute closed — verify outcome",
  refund_failed:"Qira Proof refund failed — investigate"
};
const nowSeconds=()=>Math.floor(Date.now()/1000);
function assertBatch(results){if(!Array.isArray(results)||results.some(r=>r?.success===false))throw Error("notification storage unavailable");}
export async function populateNotifications(db,at=nowSeconds()){
 if(!db)throw Error("notification database missing");
 const earliest=at-90*DAY;
 const q=[
  db.prepare("INSERT OR IGNORE INTO qira_notifications(notification_id,kind,session_id,status,created_at,next_attempt_at) SELECT 'order:' || session_id || ':' || status, status,session_id,'pending',?,? FROM qira_orders WHERE status IN ('paid','failed','refunded','disputed') AND updated_at>=?").bind(at,at,earliest),
  db.prepare("INSERT OR IGNORE INTO qira_notifications(notification_id,kind,session_id,status,created_at,next_attempt_at) SELECT 'intake:' || i.session_id,'intake',i.session_id,'pending',?,? FROM qira_intakes i JOIN qira_orders o ON i.session_id=o.session_id WHERE i.submitted_at>=? AND o.status='paid'").bind(at,at,earliest),
  db.prepare("INSERT OR IGNORE INTO qira_notifications(notification_id,kind,session_id,status,created_at,next_attempt_at) SELECT 'adjustment:' || event_id,kind,session_id,'pending',?,? FROM qira_adjustments WHERE kind IN ('partial_refund','dispute_closed','refund_failed') AND received_at>=?").bind(at,at,earliest)
 ];
 assertBatch(await db.batch(q));
}
export async function sendPendingNotifications(env,at=nowSeconds(),httpFetch=fetch){
 const db=env?.QIRA_PROOF_ORDERS;
 if(!db)return {configured:false,delivered:0};
 // Missing credentials never results in a fake sent status or discarded queue.
 if(typeof env.QIRA_RESEND_API_KEY!=="string"||!env.QIRA_RESEND_API_KEY.startsWith("re_"))
  return {configured:false,delivered:0};
 const selected=await db.prepare("SELECT notification_id,kind,session_id FROM qira_notifications WHERE next_attempt_at<=? AND (status='pending' OR (status='sending' AND lease_until<?)) ORDER BY created_at LIMIT 8").bind(at,at).all();
 if(selected?.success===false)throw Error("notification queue read failed");
 let delivered=0;
 for(const note of selected.results||[]){
  if(!labels[note.kind])continue;
  const claimed=await db.prepare("UPDATE qira_notifications SET status='sending', attempts=attempts+1, lease_until=? WHERE notification_id=? AND (status='pending' OR (status='sending' AND lease_until<?)) RETURNING notification_id,kind,session_id,attempts").bind(at+120,note.notification_id,at).first();
  if(!claimed)continue; // another invocation already reserved this notification
  try{
   const digest=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(claimed.notification_id));
   const dedupeKey="qira-proof-"+Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,"0")).join("");
   const payload={
    from:FROM,to:[DESTINATION],subject:labels[claimed.kind],
    text:"Qira Proof operator action required.\nType: "+claimed.kind+"\nStripe Checkout Session: "+claimed.session_id+
         "\nReview the exact payment and any existing intake in Trend Stripe and restricted Cloudflare D1 before acting."+
         "\nNo repository access or customer delivery is authorized by this message.\n"+
         "Stripe dashboard: https://dashboard.stripe.com/payments\n"
   };
   const response=await httpFetch("https://api.resend.com/emails",{
    method:"POST",
    headers:{"Authorization":"Bearer "+env.QIRA_RESEND_API_KEY,"Content-Type":"application/json","Idempotency-Key":dedupeKey},
    body:JSON.stringify(payload)
   });
   if(!response.ok)throw Error("email provider rejected notification");
   const receipt=await response.json();
   if(typeof receipt?.id!=="string"||!/^[-a-zA-Z0-9]{10,100}$/.test(receipt.id))throw Error("missing provider receipt");
   // Valid provider acceptance is NOT proof of recipient inbox delivery.
   const sent=await db.prepare("UPDATE qira_notifications SET status='sent',sent_at=?,lease_until=NULL WHERE notification_id=? AND status='sending'").bind(at,claimed.notification_id).run();
   if(sent?.success===false)throw Error("notification update failed");
   delivered++;
  }catch{
   const retry=at+Math.min(3600,Math.pow(2,Math.min(claimed.attempts,6))*60);
   await db.prepare("UPDATE qira_notifications SET status='pending',lease_until=NULL,next_attempt_at=? WHERE notification_id=? AND status='sending'").bind(retry,claimed.notification_id).run();
  }
 }
 return {configured:true,delivered};
}
export async function runNotificationCycle(env,at=nowSeconds(),httpFetch=fetch){
 if(!env?.QIRA_PROOF_ORDERS)return {configured:false,delivered:0};
 await populateNotifications(env.QIRA_PROOF_ORDERS,at);
 return sendPendingNotifications(env,at,httpFetch);
}
export async function purgeNotifications(db,at=nowSeconds()){
 const cutoff=at-180*DAY;
 const result=await db.prepare("DELETE FROM qira_notifications WHERE created_at<?").bind(cutoff).run();
 if(result?.success===false)throw Error("notification cleanup failed");
}
