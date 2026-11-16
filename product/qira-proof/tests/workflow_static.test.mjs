import test from "node:test";
import assert from "node:assert/strict";
import {scanWorkflowSyntax} from "../workflow_static.mjs";
import {SCHEMA,normalizeSnapshot,analyzeSnapshot,proof,verifyProof} from "../core.mjs";
import {webcrypto} from "node:crypto";
if(!globalThis.crypto)globalThis.crypto=webcrypto;
const sha="0123456789abcdef0123456789abcdef01234567";
const when="2026-11-16T00:00:00Z";
test("read-only workflow permissions yield a bounded positive observation",()=>{
 const source=["name: Test","on: [push, pull_request]","permissions:","  contents: read",
 "  packages: none","jobs:","  test:","    runs-on: ubuntu-latest",
 "    steps:","      - uses: actions/checkout@"+sha,"      - run: echo okay"].join("\n");
 const s=scanWorkflowSyntax(source);
 assert.deepEqual(s.workflow_explicit_read_only_permissions,{value:true,line:3});
 assert.deepEqual(s.workflow_token_write_permission,{value:false,line:3});
 assert.equal(s.workflow_pull_request_target_trigger.value,false);
 assert.equal(s.workflow_unpinned_actions.value,false);
 assert.equal(s.runtime_ssh_keyscan.value,false);
});
test("source lines identify mutable action and SSH shell command",()=>{
 const source=["name: Deployment",'"on":',"  pull_request_target:","permissions:",
 "  contents: write","jobs:","  deploy:","    steps:",
 "      - uses: actions/checkout@v4","      - run: |",
 "          # ssh-keyscan -H example.org",
 "          ssh-keyscan -H example.org >> ~/.ssh/known_hosts",
 "          echo 'permissions: contents: write'"].join("\n");
 const s=scanWorkflowSyntax(source);
 assert.deepEqual(s.workflow_unpinned_actions,{value:true,line:9});
 assert.deepEqual(s.runtime_ssh_keyscan,{value:true,line:12});
 assert.deepEqual(s.workflow_token_write_permission,{value:true,line:5});
 assert.deepEqual(s.workflow_explicit_read_only_permissions,{value:false,line:5});
 assert.deepEqual(s.workflow_pull_request_target_trigger,{value:true,line:3});
});
test("job-level write overrides read-only declared at the workflow level",()=>{
 const s=scanWorkflowSyntax(["permissions: read-all","on: push","jobs:","  release:","    permissions:",
  "      contents: write","    steps:","      - run: echo release"].join("\n"));
 assert.equal(s.workflow_explicit_read_only_permissions.value,false);
 assert.equal(s.workflow_token_write_permission.value,true);
 assert.equal(s.workflow_token_write_permission.line,6);
});
test("missing or unusual permission syntax remains unknown",()=>{
 const empty=scanWorkflowSyntax("name: Empty\njobs:\n  check:\n    steps:\n      - run: echo hi\n");
 assert.equal(empty.workflow_explicit_read_only_permissions.value,"unknown");
 assert.equal(empty.workflow_token_write_permission.value,"unknown");
 assert.equal(empty.workflow_pull_request_target_trigger.value,"unknown");
 const dynamic=scanWorkflowSyntax(["on: workflow_dispatch","permissions:","  contents: dynamic-reference"].join("\n"));
 assert.equal(dynamic.workflow_explicit_read_only_permissions.value,"unknown");
 assert.equal(dynamic.workflow_token_write_permission.value,"unknown");
});
test("privileged PR trigger is review-only; no code execution claimed",()=>{
 const inspected=scanWorkflowSyntax(["on:","  pull_request_target:","permissions:","  contents: write"].join("\n"));
 const facts=Object.entries(inspected).filter(([signal])=>signal!=="writeScopes").map(([signal,meta])=>({
  provider:"github",asset:"owner/repo:.github/workflows/security.yml",signal,
  value:meta.value,source_url:"https://github.com/owner/repo/blob/"+sha+"/.github/workflows/security.yml"+(meta.line?"#L"+meta.line:""),observed_at:when
 }));
 const assessment=analyzeSnapshot(normalizeSnapshot({schema:SCHEMA,captured_at:when,facts}));
 assert.ok(assessment.findings.some(x=>x.check==="privileged_pr_trigger"&&x.level==="review"));
 assert.equal(assessment.findings.some(x=>x.level==="high"),false);
 assert.equal(assessment.controls.length,0);
});
test("immutable GitHub line links work, arbitrary fragments are rejected",async()=>{
 const base={schema:SCHEMA,captured_at:when,facts:[
  {provider:"github",asset:"owner/repo",signal:"workflow_unpinned_actions",value:true,
   source_url:"https://github.com/owner/repo/blob/"+sha+"/.github/workflows/ci.yml#L19",observed_at:when}
 ]};
 const receipt=await proof(base);
 assert.equal(await verifyProof(receipt),true);
 for(const url of ["https://example.org/ci#L19",
  "https://github.com/owner/repo/blob/main/.github/workflows/ci.yml#L19",
  "https://github.com/owner/repo/blob/"+sha+"/.github/workflows/ci.yml#evil",
  "https://github.com/owner/repo/blob/"+sha+"/.github/workflows/ci.yml?token=private#L19"]){
  const bad=structuredClone(base);bad.facts[0].source_url=url;
  assert.throws(()=>normalizeSnapshot(bad),/unsafe snapshot/i);
 }
});
test("read-only declaration makes a reproducible positive-control observation",async()=>{
 const input={schema:SCHEMA,captured_at:when,facts:[
  {provider:"github",asset:"owner/repo:.github/workflows/ci.yml",
   signal:"workflow_explicit_read_only_permissions",value:true,
   source_url:"https://github.com/owner/repo/blob/"+sha+"/.github/workflows/ci.yml#L3",observed_at:when}
 ]};
 const receipt=await proof(input);
 assert.equal(await verifyProof(receipt),true);
 assert.equal(receipt.assessment.controls.length,1);
 assert.match(receipt.assessment.controls[0].interpretation,/not independent proof/);
});

test("nested env or with permissions keys are not misreported as effective read-only scopes",()=>{
 const fakeEnv=[
  "on: push","env:","  permissions:","    contents: read",
  "jobs:","  inspect:","    runs-on: ubuntu-latest",
  "    steps:","      - uses: actions/checkout@v4",
  "        with:","          permissions:","            contents: read"].join("\n");
 const data=scanWorkflowSyntax(fakeEnv);
 assert.equal(data.workflow_explicit_read_only_permissions.value,"unknown");
 assert.equal(data.workflow_token_write_permission.value,"unknown");
});
test("an authoritative read-only declaration is not promoted to safe when nested ambiguous permissions exist",()=>{
 const workflow=[
  "on: push","permissions:","  contents: read",
  "jobs:","  inspect:","    runs-on: ubuntu-latest",
  "    steps:","      - run: |",
  "          permissions:","            contents: write"
 ].join("\n");
 const data=scanWorkflowSyntax(workflow);
 // The shell payload must not become a GitHub Actions permission declaration.
 assert.equal(data.workflow_explicit_read_only_permissions.value,true);
 assert.equal(data.workflow_token_write_permission.value,false);
});
test("valid sequence-style pull_request_target is detected, not marked safe",()=>{
 const sequence=["on:","  - push","  - pull_request_target","permissions:","  contents: write"].join("\n");
 const data=scanWorkflowSyntax(sequence);
 assert.equal(data.workflow_pull_request_target_trigger.value,true);
 assert.equal(data.workflow_pull_request_target_trigger.line,3);
});
test("unsupported inline event maps and quoted events remain unknown",()=>{
 for(const on of ["on: { pull_request_target: {} }","on: 'pull_request_target'","on: [push, *event_alias]"]){
  assert.equal(scanWorkflowSyntax(on).workflow_pull_request_target_trigger.value,"unknown");
 }
});
test("non-pull-request-target workflow event maps are recognized as false only when structurally valid",()=>{
 const workflow=["on:","  schedule:","    - cron: '15 5 * * *'","  workflow_dispatch:","jobs:","  test:"].join("\n");
 assert.equal(scanWorkflowSyntax(workflow).workflow_pull_request_target_trigger.value,false);
});
