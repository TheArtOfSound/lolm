import test from "node:test";
import assert from "node:assert/strict";
import {SCHEMA,normalizeSnapshot,analyzeSnapshot,compareSnapshots,proof,verifyProof} from "../core.mjs";
import {webcrypto} from "node:crypto";
if(!globalThis.crypto)globalThis.crypto=webcrypto;

const d="2026-11-15T19:00:00Z";
const fact=(signal,value,provider="vercel")=>({provider,asset:"sample-project",
 signal,value,source_url:"https://api.vercel.com/v9/projects/prj_Test",observed_at:d});
const snapshot=(protection=false,preview=true,error=true)=>({schema:SCHEMA,captured_at:d,facts:[
 fact("vercel_deployment_protection_configured",protection),
 fact("vercel_recent_preview_observed",preview),
 fact("vercel_latest_production_errored",error)
]});

test("only explicitly observed preview + disabled protection yields a conditional review",()=>{
 const report=analyzeSnapshot(snapshot());
 assert.equal(report.counts.review,2);
 assert.ok(report.findings.some(f=>f.check==="vercel_preview_visibility"));
 assert.ok(report.findings.some(f=>f.check==="vercel_production_release"));
 assert.ok(report.findings.every(f=>/not|does not|may/i.test(f.interpretation)));
});
test("unknown states are not silently false and no fabricated exposures are emitted",()=>{
 const report=analyzeSnapshot(snapshot("unknown",true,"unknown"));
 assert.equal(report.findings.length,0);
 assert.equal(analyzeSnapshot(snapshot(false,"unknown",false)).findings.length,0);
 assert.equal(analyzeSnapshot(snapshot(true,true,false)).findings.length,0);
});
test("provider mismatch and duplicate facts are blocked",()=>{
 const a=snapshot();
 a.facts[0].provider="github";
 assert.throws(()=>normalizeSnapshot(a),/Signal\/provider mismatch/);
 const b=snapshot();b.facts.push({...b.facts[0]});
 assert.throws(()=>normalizeSnapshot(b),/duplicate/);
});
test("proof contains only declared evidence and is tamper-evident",async()=>{
 const p=await proof(snapshot());
 assert.equal(await verifyProof(p),true);
 const altered=structuredClone(p);
 altered.baseline.facts[0].value=true;
 assert.equal(await verifyProof(altered),false);
});
test("evidence recheck reports indicators cleared but not actual remediation",()=>{
 const previous=snapshot();
 const current=snapshot(true,true,false);
 current.captured_at="2026-11-16T19:00:00Z";
 for(const f of current.facts) f.observed_at=current.captured_at;
 const result=compareSnapshots(previous,current);
 assert.equal(result.verified_changes,0);
 assert.equal(result.deltas.length,2);
 assert.ok(result.deltas.every(x=>x.state==="indicator-cleared"));
});
