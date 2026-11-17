// Qira Proof report-ready customer email outbox.
// Only an explicit human-released R2 deliverable may trigger a notice.
// Email is loaded from restricted paid intake and independently matches
// the HMAC of the Stripe-confirmed checkout email before sending.
import {buyerDigest} from "./payments.mjs";
const FROM="Qira Proof Reports <reports@imagineqira.com>";
const REPORT_URL="https://proof.imagineqira.com/report-access";
const now=()=>Math.floor(Date.now()/1000);
function constantEqual(a,b){if(typeof a!=="string"||typeof b!=="string"||a.length!==b.length)return false;let d=0;for(let i=0;i<a.length;i++)d|=a.charCodeAt(i)^b.charCodeAt(i);return d===0;}
function hex(bytes){return Array.from(new Uint8Array(bytes),b=>b.toString(16).padStart(2,"0")).join("");}
export async function enqueueReadyReports(db,at=now()){
 const query=`INSERT OR IGNORE INTO qira_customer_notices(session_id,status,attempts,created_at,next_attempt_at)
 SELECT d.session_id,'pending',0,?,? FROM qira_deliverables d
 JOIN qira_orders o ON o.session_id=d.session_id
 JOIN qira_intakes i ON i.session_id=d.session_id
 WHERE d.revoked_at IS NULL AND d.released_at<=? AND o.status='paid'
 AND COALESCE(o.refund_amount,0)=0 AND i.state='delivered'`;
 const result=await db.prepare(query).bind(at,at,at).run();
 if(result?.success===false)throw Error("outbox_insert_failed");
}
export async function deliverReadyReports(env,at=now(),fetcher=fetch){
 const db=env?.QIRA_PROOF_ORDERS;if(!db)return {configured:false,accepted:0};
 if(!env.QIRA_RESEND_API_KEY||!env.QIRA_ORDER_EMAIL_PEPPER)return {configured:false,accepted:0};
 const eligible=await db.prepare(`SELECT n.session_id,n.status,n.attempts,i.contact_email,o.buyer_email_digest
 FROM qira_customer_notices n
 JOIN qira_orders o ON o.session_id=n.session_id
 JOIN qira_intakes i ON i.session_id=n.session_id
 JOIN qira_deliverables d ON d.session_id=n.session_id
 WHERE n.next_attempt_at<=? AND
  (n.status='pending' OR (n.status='sending' AND n.lease_until<?))
 AND o.status='paid' AND COALESCE(o.refund_amount,0)=0
 AND i.state='delivered' AND d.revoked_at IS NULL AND d.released_at<=?
 ORDER BY n.created_at ASC LIMIT 8`).bind(at,at,at).all();
 if(eligible?.success===false)throw Error("outbox_read_failed");
 let accepted=0;
 for(const note of eligible.results||[]){
  const expected=await buyerDigest(env.QIRA_ORDER_EMAIL_PEPPER,note.contact_email);
  if(!expected||!constantEqual(expected,note.buyer_email_digest))continue;
  const claimed=await db.prepare(`UPDATE qira_customer_notices SET
   status='sending',attempts=attempts+1,lease_until=?
   WHERE session_id=? AND (status='pending' OR (status='sending' AND lease_until<?))
   RETURNING session_id,attempts`).bind(at+180,note.session_id,at).first();
  if(!claimed)continue;
  try{
   const key=hex(await crypto.subtle.digest("SHA-256",new TextEncoder().encode("qira-report-ready-v1:"+claimed.session_id)));
   const response=await fetcher("https://api.resend.com/emails",{
    method:"POST",
    headers:{"Authorization":"Bearer "+env.QIRA_RESEND_API_KEY,"Content-Type":"application/json","Idempotency-Key":"qira-ready-"+key},
    body:JSON.stringify({
     from:FROM,to:[note.contact_email],
     subject:"Your Qira Proof review is ready for secure retrieval",
     text:"Your human-reviewed Qira Proof report has been released for secure retrieval.\n\nOpen: "+REPORT_URL+
       "\nStripe checkout reference: "+claimed.session_id+
       "\nCheckout email: the address that received this message.\n\nThe access page sends a separate eight-digit one-time code to this mailbox. There is no need to buy again. Please do not share your access code.\n\nThe report is a scoped configuration review, not a certification or guarantee of security."
    })
   });
   if(!response.ok)throw Error("provider_rejected");
   const receipt=await response.json();
   if(typeof receipt?.id!=="string"||receipt.id.length<10)throw Error("provider_receipt_missing");
   const updated=await db.prepare("UPDATE qira_customer_notices SET status='accepted',accepted_at=?,lease_until=NULL WHERE session_id=? AND status='sending'").bind(at,claimed.session_id).run();
   if(updated?.success===false)throw Error("outbox_acceptance_failed");
   accepted++;
  }catch{
   const retry=at+Math.min(3600,Math.pow(2,Math.min(claimed.attempts,6))*60);
   await db.prepare("UPDATE qira_customer_notices SET status='pending',lease_until=NULL,next_attempt_at=? WHERE session_id=? AND status='sending'").bind(retry,claimed.session_id).run();
  }
 }
 return {configured:true,accepted};
}
export async function runCustomerReadyNotices(env,at=now(),fetcher=fetch){
 if(!env?.QIRA_PROOF_ORDERS)return {configured:false,accepted:0};
 await enqueueReadyReports(env.QIRA_PROOF_ORDERS,at);
 return deliverReadyReports(env,at,fetcher);
}
export async function purgeCustomerNotices(db,at=now()){
 const r=await db.prepare("DELETE FROM qira_customer_notices WHERE status='accepted' AND created_at<?").bind(at-180*86400).run();
 if(r?.success===false)throw Error("customer_notice_cleanup_failed");
}
