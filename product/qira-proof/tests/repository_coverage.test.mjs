import test from "node:test";
import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import {SCHEMA,normalizeSnapshot,proof,verifyProof,mergeSnapshots} from "../core.mjs";
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
