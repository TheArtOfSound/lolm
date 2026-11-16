import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import {scanWorkflowSyntax} from "../workflow_static.mjs";

const corpora=["workflow_accuracy.json","workflow_adjudication_holdout.json"].map(name=>JSON.parse(fs.readFileSync(new URL("./fixtures/"+name,import.meta.url),"utf8")));
const obs={
 mutable:x=>x.workflow_unpinned_actions.value,
 write:x=>x.workflow_token_write_permission.value,
 restricted:x=>x.workflow_explicit_read_only_permissions.value,
 target:x=>x.workflow_pull_request_target_trigger.value,
 ssh:x=>x.runtime_ssh_keyscan.value,
 scopes:x=>x.writeScopes.map(y=>y.scope)
};
test("curated synthetic accuracy corpus has unique well-described cases",()=>{
 assert.equal(corpora[0].schema,"qira-proof/accuracy-fixtures-v1");
 assert.equal(corpora[1].schema,"qira-proof/adjudication-holdout-v1");
 const cases=corpora.flatMap(x=>x.fixtures);
 assert.equal(cases.length,100);
 assert.equal(new Set(cases.map(x=>x.id)).size,cases.length);
 assert.ok(cases.every(x=>x.rationale.length>=18&&x.workflow.includes("\n")));
});
for(const fixture of corpora.flatMap(x=>x.fixtures)){
 test("accuracy fixture: "+fixture.id,()=>{
  const seen=scanWorkflowSyntax(fixture.workflow);
  for(const [name,want] of Object.entries(fixture.expected)){
   assert.ok(Object.hasOwn(obs,name),name+" is not a supported gold label");
   assert.deepEqual(obs[name](seen),want,name+" / "+fixture.rationale);
  }
 });
}
