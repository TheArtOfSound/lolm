import test from "node:test";
import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import {SCHEMA,normalizeSnapshot,proof,verifyProof,canonical,sha256,analyzeSnapshot,mergeSnapshots} from "../core.mjs";
import {scanWorkflowSyntax} from "../workflow_static.mjs";
import {renderHumanReport} from "../report.mjs";
if(!globalThis.crypto)globalThis.crypto=webcrypto;
const sha="0123456789abcdef0123456789abcdef01234567",time="2026-11-16T07:00:00Z";
const repo="org/repo",asset=repo+":.github/workflows/release.yml",url="https://github.com/"+repo+"/blob/"+sha+"/.github/workflows/release.yml";
const facts=[{provider:"github",asset,signal:"workflow_token_write_permission",value:true,source_url:url+"#L6",observed_at:time}];
const inventory=[{asset,scopes:[
 {scope:"contents",source_url:url+"#L6"},{scope:"issues",source_url:url+"#L7"},
 {scope:"id-token",source_url:url+"#L8"}
]}];
function snap(){return{schema:SCHEMA,captured_at:time,facts,permission_inventory:inventory}}
test("scanner records specific source lines without workflow text or secret values",()=>{
 const source=["on: workflow_dispatch","permissions:","  contents: read","jobs:","  publish:",
  "    permissions:","      contents: write","      issues: write","      id-token: write",
  "    steps:","      - run: echo publishing"].join("\n");
 const scanned=scanWorkflowSyntax(source);
 assert.deepEqual(scanned.writeScopes,[
  {scope:"contents",line:7},{scope:"issues",line:8},{scope:"id-token",line:9}
 ]);
 assert.equal(scanned.workflow_token_write_permission.value,true);
 assert.equal(scanned.workflow_explicit_read_only_permissions.value,false);
});
test("verified v3 receipt includes separate scope-specific links without adding risk findings",async()=>{
 const doc=await proof(snap());
 assert.equal(doc.schema,"qira-proof/evidence-v3");
 assert.equal(doc.policy_version,"2026-11-16-source-scopes-v3");
 assert.equal(doc.baseline.permission_inventory[0].scopes.length,3);
 assert.equal((await verifyProof(doc)),true);
 assert.equal(analyzeSnapshot(snap()).counts.review,0);
 const html=await renderHumanReport(doc);
 for(const name of ["contents: write","issues: write","id-token: write"])assert.ok(html.includes(name));
 assert.ok(html.includes("#L8"));
 assert.ok(html.includes("not a vulnerability count"));
});
test("tampered declared scope fails receipt verification",async()=>{
 const doc=await proof(snap());
 doc.baseline.permission_inventory[0].scopes[0].scope="packages";
 assert.equal(await verifyProof(doc),false);
});
test("rejects invented scope, source-host switch, missing permission fact and duplicate scope declarations",()=>{
 for(const edit of [
  x=>x.permission_inventory[0].scopes[0].scope="secret-key",
  x=>x.permission_inventory[0].scopes[0].source_url="https://evil.example/blob/"+sha+"/.github/workflows/release.yml#L6",
  x=>x.permission_inventory[0].scopes.push({...x.permission_inventory[0].scopes[0]}),
  x=>x.facts[0].value=false,
  x=>x.permission_inventory[0].scopes[0].source_url=url.replace("release.yml","fake.yml")+"#L6"
 ]){
  const x=structuredClone(snap());edit(x);
  assert.throws(()=>normalizeSnapshot(x),/permission inventory/i);
 }
});
test("cross-provider local composition retains source-specific scope inventory",()=>{
 const combined=mergeSnapshots(snap(),{schema:SCHEMA,captured_at:time,facts:[
  {provider:"cloudflare",asset:"edge",signal:"worker_preview_enabled",value:false,
   source_url:"https://example.org/edge",observed_at:time}
 ]});
 assert.equal(combined.permission_inventory[0].scopes.length,3);
 assert.equal(combined.facts.length,2);
});
test("previous v2 evidence receipts remain valid after v3 upgrade",async()=>{
 const base={schema:SCHEMA,captured_at:time,facts};
 const payload={schema:"qira-proof/evidence-v2",policy_version:"2026-11-16-static-workflow-v2",
  baseline:normalizeSnapshot(base),after:null,assessment:analyzeSnapshot(base),comparison:null,
  attestation:"self-contained deterministic calculation, NOT source authentication, a signature, or proof of prevention"};
 const doc={...payload,sha256:await sha256(canonical(payload))};
 assert.equal(await verifyProof(doc),true);
});
