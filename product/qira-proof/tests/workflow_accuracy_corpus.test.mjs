import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import {scanWorkflowSyntax} from "../workflow_static.mjs";

const corpus=JSON.parse(fs.readFileSync(new URL("./fixtures/workflow_accuracy.json",import.meta.url),"utf8"));
const obs={
 mutable:x=>x.workflow_unpinned_actions.value,
 write:x=>x.workflow_token_write_permission.value,
 restricted:x=>x.workflow_explicit_read_only_permissions.value,
 target:x=>x.workflow_pull_request_target_trigger.value,
 ssh:x=>x.runtime_ssh_keyscan.value,
 scopes:x=>x.writeScopes.map(y=>y.scope)
};
test("curated synthetic accuracy corpus has unique well-described cases",()=>{
 assert.equal(corpus.schema,"qira-proof/accuracy-fixtures-v1");
 assert.ok(corpus.fixtures.length>=60,"At least sixty distinct fixtures expected");
 assert.equal(new Set(corpus.fixtures.map(x=>x.id)).size,corpus.fixtures.length);
 assert.ok(corpus.fixtures.every(x=>x.rationale.length>=18&&x.workflow.includes("\n")));
});
for(const fixture of corpus.fixtures){
 test("accuracy fixture: "+fixture.id,()=>{
  const seen=scanWorkflowSyntax(fixture.workflow);
  for(const [name,want] of Object.entries(fixture.expected)){
   assert.ok(Object.hasOwn(obs,name),name+" is not a supported gold label");
   assert.deepEqual(obs[name](seen),want,name+" / "+fixture.rationale);
  }
 });
}
