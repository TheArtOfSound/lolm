import test from "node:test";
import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import {SCHEMA,normalizeSnapshot,proof,verifyProof,mergeSnapshots,analyzeSnapshot,groupReviewFindings} from "../core.mjs";
import {renderHumanReport} from "../report.mjs";
if(!globalThis.crypto)globalThis.crypto=webcrypto;
const when="2026-11-16T05:00:00Z";
const commit="0123456789abcdef0123456789abcdef01234567";
const repo="example/repo";
const wf=".github/workflows/ci.yml";
const source="https://github.com/example/repo/blob/"+commit+"/"+wf;
function snap({partial=false}={}){
 const coverage={mode:"bounded-repository-workflows",repository:repo,discovered:partial?3:1,
  selected:partial?3:1,assessed:1,skipped:partial?2:0,limit:20,
  complete:!partial,truncated:false,commit};
 return {schema:SCHEMA,captured_at:when,coverage,facts:[
  {provider:"github",asset:repo,signal:"repo_branch_protection_verifiable",value:"unknown",
   source_url:"https://github.com/example/repo/settings/branches",observed_at:when},
  {provider:"github",asset:repo+":"+wf,signal:"workflow_unpinned_actions",value:true,
   source_url:source,observed_at:when},
  {provider:"github",asset:repo+":"+wf,signal:"runtime_ssh_keyscan",value:false,
   source_url:source,observed_at:when}
 ]};
}
test("complete coverage is preserved in report JSON and human-readable export",async()=>{
 const s=normalizeSnapshot(snap());
 assert.equal(s.coverage.assessed,1);
 const receipt=await proof(s);
 assert.equal(await verifyProof(receipt),true);
 const html=await renderHumanReport(receipt);
 assert.match(html,/all discovered workflows inspected/);
 assert.match(html,/1 of 1 workflows assessed/);
 assert.match(html,/0123456789abcdef0123456789abcdef01234567/);
});
test("partial scan remains clearly disclosed in printable report",async()=>{
 const r=await proof(snap({partial:true}));
 assert.equal(await verifyProof(r),true);
 const html=await renderHumanReport(r);
 assert.match(html,/Repository scan coverage — PARTIAL/);
 assert.match(html,/1 of 3 workflows assessed; 2 failed or skipped/);
});
test("tampering with coverage fails verification",async()=>{
 const r=await proof(snap());
 r.baseline.coverage.discovered=2;
 assert.equal(await verifyProof(r),false);
 await assert.rejects(renderHumanReport(r),/verification/);
});
test("coverage cannot claim all workflows when data shows skipped items",()=>{
 const x=snap({partial:true});
 x.coverage.complete=true;
 assert.throws(()=>normalizeSnapshot(x),/coverage/i);
});
test("coverage cannot invent additional scan facts",()=>{
 const x=snap();
 x.coverage.assessed=2;
 assert.throws(()=>normalizeSnapshot(x),/coverage/i);
});
test("combining evidence does not falsely inherit repository-wide coverage",()=>{
 const a=snap(),b={schema:SCHEMA,captured_at:when,facts:[
  {provider:"cloudflare",asset:"edge",signal:"worker_preview_enabled",value:false,
   source_url:"https://example.org/edge",observed_at:when}
 ]};
 const joined=mergeSnapshots(a,b);
 assert.equal(joined.coverage,undefined);
 assert.equal(joined.facts.length,4);
});

test("multiple workflow findings appear as concise groups without losing either source",async()=>{
 const s=snap();
 const workflow2=".github/workflows/release.yml";
 s.coverage={...s.coverage,discovered:2,selected:2,assessed:2};
 s.facts.push({provider:"github",asset:repo+":"+workflow2,signal:"workflow_unpinned_actions",
  value:true,source_url:"https://github.com/example/repo/blob/"+commit+"/"+workflow2,observed_at:when});
 const assessment=analyzeSnapshot(s);
 assert.equal(assessment.findings.length,3);
 const grouped=groupReviewFindings(assessment.findings);
 assert.equal(grouped.length,2);
 const repeated=grouped.find(x=>x.check==="workflow_action_integrity");
 assert.equal(repeated.affected,2);
 assert.equal(repeated.evidence.length,2);
 assert.match(repeated.title,/2 workflows/);
 const receipt=await proof(s);
 assert.equal(receipt.assessment.findings.length,3,"Underlying evidence must not be discarded");
 assert.equal(await verifyProof(receipt),true);
 const html=await renderHumanReport(receipt);
 assert.match(html,/2 workflows: Third-party CI actions/);
 assert.match(html,/ci.yml/);
 assert.match(html,/release.yml/);
 assert.equal((html.match(/class="finding"/g)||[]).length,2);
});
