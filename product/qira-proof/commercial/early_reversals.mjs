// Stripe does not guarantee webhook event order. Keep signed charge reversals
// as short-lived, keyed markers so a late Checkout Session cannot grant paid
// intake after a refund, dispute or unsettled reversal. No raw PaymentIntent,
// unrelated merchant email, card data or charge payload is stored here.
const MAX_WINDOW=30*86400;
export async function paymentIntentDigest(secret,intent){
 if(typeof secret!=="string"||secret.length<32||typeof intent!=="string"||!/^pi_[A-Za-z0-9]+$/.test(intent))return null;
 const key=await crypto.subtle.importKey("raw",new TextEncoder().encode(secret),{name:"HMAC",hash:"SHA-256"},false,["sign"]);
 const bytes=await crypto.subtle.sign("HMAC",key,new TextEncoder().encode("qira-proof-intent-v1:"+intent));
 return Array.from(new Uint8Array(bytes),b=>b.toString(16).padStart(2,"0")).join("");
}
export function rememberEarlyReversal(db,event,reversal,digest,receivedAt){
 if(!/^[a-f0-9]{64}$/.test(digest||""))throw Error("intent_digest_missing");
 const amount=Math.max(0,Math.min(29900,reversal.amountRefunded||0));
 return db.prepare("INSERT OR IGNORE INTO qira_early_reversals(event_id,intent_digest,kind,amount_refunded,outcome,event_created,received_at) VALUES(?,?,?,?,?,?,?)")
  .bind(event.id,digest,reversal.status,amount,reversal.outcome||null,event.created,receivedAt);
}
export function reconcileEarlyReversals(db,sessionId,intent,digest,at){
 if(!/^[a-f0-9]{64}$/.test(digest||""))throw Error("intent_digest_missing");
 const hold=`UPDATE qira_orders SET
 status=CASE WHEN status IN ('refunded','disputed') THEN status
 WHEN EXISTS(SELECT 1 FROM qira_early_reversals r WHERE r.intent_digest=? AND r.kind IN ('disputed','dispute_closed')) THEN 'disputed'
 WHEN EXISTS(SELECT 1 FROM qira_early_reversals r WHERE r.intent_digest=? AND r.kind='refunded') THEN 'refunded'
 ELSE status END,
 refund_amount=MAX(refund_amount,COALESCE((SELECT MAX(r.amount_refunded) FROM qira_early_reversals r WHERE r.intent_digest=? AND r.kind='partial_refund'),0)),
 updated_at=?
 WHERE session_id=? AND payment_intent_id=?`;
 const adjustments=`INSERT OR IGNORE INTO qira_adjustments(event_id,session_id,kind,amount_refunded,outcome,received_at)
 SELECT r.event_id,o.session_id,r.kind,r.amount_refunded,r.outcome,r.received_at
 FROM qira_early_reversals r JOIN qira_orders o ON o.payment_intent_id=?
 WHERE r.intent_digest=? AND r.kind IN ('partial_refund','dispute_closed','refund_failed')`;
 const eventCopy=`INSERT OR IGNORE INTO qira_events(event_id,event_type,event_created,received_at)
 SELECT r.event_id,
 CASE r.kind WHEN 'partial_refund' THEN 'charge.refunded'
 WHEN 'refunded' THEN 'charge.refunded'
 WHEN 'disputed' THEN 'charge.dispute.created'
 WHEN 'dispute_closed' THEN 'charge.dispute.closed'
 ELSE 'refund.failed' END,
 r.event_created,r.received_at
 FROM qira_early_reversals r JOIN qira_orders o ON o.payment_intent_id=?
 WHERE r.intent_digest=?`;
 return [
  db.prepare(hold).bind(digest,digest,digest,at,sessionId,intent),
  db.prepare(adjustments).bind(intent,digest),
  db.prepare(eventCopy).bind(intent,digest)
 ];
}
export async function purgeEarlyReversals(db,at=Math.floor(Date.now()/1000)){
 if(!db||!Number.isSafeInteger(at))throw Error("early_reversal_purge_unavailable");
 const result=await db.prepare("DELETE FROM qira_early_reversals WHERE received_at<?").bind(at-MAX_WINDOW).run();
 if(result?.success===false)throw Error("early_reversal_purge_failed");
 return true;
}
