import test from "node:test";
import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import {paymentIntentDigest,rememberEarlyReversal,reconcileEarlyReversals,purgeEarlyReversals} from "../commercial/early_reversals.mjs";
if(!globalThis.crypto)globalThis.crypto=webcrypto;
const pepper="synthetic_intent_key_0123456789abcdef0123456789abcdef",pi="pi_testABC0123456789";
const db={prepare(sql){return {bind(...args){return {sql,args,run:async()=>({success:true})};}};}};
test("only validated PaymentIntent IDs become distinct, nonreversible keyed hashes",async()=>{
 const first=await paymentIntentDigest(pepper,pi),second=await paymentIntentDigest(pepper,"pi_different01234");
 assert.match(first,/^[0-9a-f]{64}$/);assert.notEqual(first,second);
 assert.equal(first,await paymentIntentDigest(pepper,pi));
 assert.equal(await paymentIntentDigest(pepper,"bad_intent"),null);
 assert.equal(await paymentIntentDigest("short",pi),null);
});
test("signed reversal buffer stores the HMAC, never raw PaymentIntent, card or buyer email",async()=>{
 const digest=await paymentIntentDigest(pepper,pi);
 const event={id:"evt_early123456789",created:1794880000};
 const reversal={paymentIntent:pi,status:"refunded",amountRefunded:29900};
 const cmd=rememberEarlyReversal(db,event,reversal,digest,1794880010);
 assert.match(cmd.sql,/INSERT OR IGNORE INTO qira_early_reversals/);
 assert.equal(cmd.args[1],digest);
 assert.doesNotMatch(JSON.stringify(cmd),/pi_testABC0123456789|@|card_number/);
 assert.equal(cmd.args[2],"refunded");
});
test("late checkout transaction atomically checks terminal disputes, partial refunds and event copies",async()=>{
 const digest=await paymentIntentDigest(pepper,pi);
 const q=reconcileEarlyReversals(db,"cs_live_testcheckout01234",pi,digest,1794880000);
 assert.equal(q.length,3);
 assert.match(q[0].sql,/IN \('disputed','dispute_closed'\)/);
 assert.match(q[0].sql,/r.kind='partial_refund'/);
 assert.doesNotMatch(q[0].sql,/r.kind IN \('partial_refund','refund_failed'\)/);
 assert.match(q[1].sql,/INSERT OR IGNORE INTO qira_adjustments/);
 assert.match(q[2].sql,/INSERT OR IGNORE INTO qira_events/);
});
test("buffer removes markers older than 30 days without requesting remote Stripe data",async()=>{
 let seen;
 const mocked={prepare(sql){return {bind(t){seen={sql,t};return {run:async()=>({success:true})};}};}};
 await purgeEarlyReversals(mocked,1794880000);
 assert.equal(seen.t,1794880000-30*86400);
 assert.match(seen.sql,/DELETE FROM qira_early_reversals/);
 await assert.rejects(purgeEarlyReversals(null,1794880000),/unavailable/);
});
