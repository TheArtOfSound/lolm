import test from "node:test";
import assert from "node:assert/strict";
import {SCHEMA,analyzeSnapshot,normalizeSnapshot,compareSnapshots,proof,verifyProof} from "../core.mjs";
import {webcrypto} from "node:crypto";
if(!globalThis.crypto)globalThis.crypto=webcrypto;
const ts="2026-11-15T19:00:00Z";
function evidence(value,at=ts){return {schema:SCHEMA,captured_at:at,facts:[
 {provider:"github",asset:"TheArtOfSound/lolm",signal:"workflow_unpinned_actions",
  value,source_url:"https://github.com/TheArtOfSound/lolm/blob/main/.github/workflows/qira-proof-pilot.yml",
  observed_at:at}
]};}
test("version-tag references produce a review finding, not an exploitation assertion",()=>{
 const findings=analyzeSnapshot(evidence(true)).findings;
 assert.equal(findings.length,1);
 assert.equal(findings[0].check,"workflow_action_integrity");
 assert.equal(findings[0].level,"review");
 assert.match(findings[0].interpretation,/not proof of a malicious update/i);
 assert.match(findings[0].next,/commit SHA/);
});
test("absent version-tag signal is not a finding; unknown not interpreted as false",()=>{
 assert.equal(analyzeSnapshot(evidence(false)).findings.length,0);
 assert.equal(analyzeSnapshot(evidence("unknown")).findings.length,0);
});
test("provider mismatch is rejected",()=>{
 const wrong=evidence(true);
 wrong.facts[0].provider="vercel";
 assert.throws(()=>normalizeSnapshot(wrong),/Signal\/provider mismatch/);
});
test("rechecked commit pin is only indicator cleared, not verified remediation",()=>{
 const before=evidence(true);
 const after=evidence(false,"2026-11-16T19:00:00Z");
 const result=compareSnapshots(before,after);
 assert.equal(result.verified_changes,0);
 assert.equal(result.deltas[0].state,"indicator-cleared");
});
test("the evidence receipt detects alterations",async()=>{
 const result=await proof(evidence(true));
 assert.equal(await verifyProof(result),true);
 const changed=structuredClone(result);
 changed.baseline.facts[0].value=false;
 assert.equal(await verifyProof(changed),false);
});
