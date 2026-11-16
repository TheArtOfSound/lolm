import test from "node:test";
import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import {SCHEMA,normalizeSnapshot,analyzeSnapshot,proof,verifyProof,canonical,sha256} from "../core.mjs";
if(!globalThis.crypto)globalThis.crypto=webcrypto;
const captured="2026-11-15T20:00:00Z";
const baseline={schema:SCHEMA,captured_at:captured,facts:[
 {provider:"github",asset:"owner/repository",signal:"workflow_unpinned_actions",value:true,
  source_url:"https://github.com/owner/repository/blob/main/.github/workflows/ci.yml",observed_at:captured},
 {provider:"github",asset:"owner/repository",signal:"repo_branch_protection_verifiable",value:"unknown",
  source_url:"https://github.com/owner/repository/settings/branches",observed_at:captured}
]};
const attestation="self-contained deterministic calculation, NOT source authentication, a signature, or proof of prevention";
test("new evidence uses an explicit analysis version",async()=>{
 const result=await proof(baseline);
 assert.equal(result.schema,"qira-proof/evidence-v3");
 assert.equal(result.policy_version,"2026-11-16-source-scopes-v3");
 assert.equal(await verifyProof(result),true);
});
test("previously generated v1 receipts still verify deterministically",async()=>{
 const normalized=normalizeSnapshot(baseline);
 const {controls,...assessment}=analyzeSnapshot(normalized);
 const payload={schema:"qira-proof/evidence-v1",baseline:normalized,after:null,assessment,
  comparison:null,attestation};
 const legacy={...payload,sha256:await sha256(canonical(payload))};
 assert.equal(await verifyProof(legacy),true);
 const tampered=structuredClone(legacy);
 tampered.assessment.findings[0].title="Rewritten";
 assert.equal(await verifyProof(tampered),false);
});
test("receipt policy version cannot be silently changed",async()=>{
 const output=await proof(baseline);
 const corrupted=structuredClone(output);
 corrupted.policy_version="2026-11-16-static-workflow-v3";
 assert.equal(await verifyProof(corrupted),false);
 const migrated=structuredClone(output);
 migrated.schema="qira-proof/evidence-v1";
 assert.equal(await verifyProof(migrated),false);
});
