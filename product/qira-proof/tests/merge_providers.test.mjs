import test from "node:test";
import assert from "node:assert/strict";
import {SCHEMA,normalizeSnapshot,mergeSnapshots,analyzeSnapshot,proof,verifyProof} from "../core.mjs";
import {webcrypto} from "node:crypto";
if(!globalThis.crypto)globalThis.crypto=webcrypto;

const d="2026-11-15T19:00:00Z";
function snapshot(provider, signal, value, at=d){
 return {schema:SCHEMA,captured_at:at,facts:[{
  provider,asset:provider+"-asset",signal,value,
  source_url:"https://example.org/authorized-evidence",observed_at:at
 }]};
}
test("GitHub, Cloudflare and Vercel evidence compose without pretending shared provenance",async()=>{
 const github=snapshot("github","runtime_ssh_keyscan",true);
 const cf=snapshot("cloudflare","worker_privileged_bindings",true);
 const vercel=snapshot("vercel","vercel_recent_preview_observed",true);
 const merged=mergeSnapshots(github,cf,vercel);
 assert.equal(merged.facts.length,3);
 assert.equal(analyzeSnapshot(merged).assets,3);
 assert.deepEqual(new Set(merged.facts.map(x=>x.provider)),new Set(["cloudflare","github","vercel"]));
 const signed=await proof(merged);
 assert.equal(await verifyProof(signed),true);
});
test("reject duplicate vendor facts, including conflicts and conflicting source links",()=>{
 const a=snapshot("vercel","vercel_recent_preview_observed",true);
 assert.throws(()=>mergeSnapshots(a,structuredClone(a)),/duplicate/);
 const b=structuredClone(a);b.facts[0].value=false;
 assert.throws(()=>mergeSnapshots(a,b),/duplicate/);
});
test("refuse source snapshots captured over a day apart",()=>{
 const a=snapshot("github","runtime_ssh_keyscan",false);
 const b=snapshot("vercel","vercel_recent_preview_observed",false,"2026-11-17T19:00:00Z");
 assert.throws(()=>mergeSnapshots(a,b),/24 hours/);
});
test("merge preserves last capture date and per-provider observation timestamps",()=>{
 const a=snapshot("github","runtime_ssh_keyscan",true);
 const b=snapshot("vercel","vercel_recent_preview_observed",true,"2026-11-16T18:59:59Z");
 const merged=mergeSnapshots(a,b);
 assert.equal(merged.captured_at,"2026-11-16T18:59:59.000Z");
 assert.deepEqual(new Set(merged.facts.map(x=>x.observed_at)),new Set([a.captured_at,b.captured_at]));
});
test("provider mismatch and secret-shaped fields cannot be used to bypass strict normalization",()=>{
 const wrong=snapshot("cloudflare","vercel_recent_preview_observed",true);
 assert.throws(()=>normalizeSnapshot(wrong),/Signal\/provider mismatch/);
 const leaked=snapshot("vercel","vercel_recent_preview_observed",true);
 leaked.facts[0].password="not-allowed";
 assert.throws(()=>mergeSnapshots(leaked),/unsafe/);
});
