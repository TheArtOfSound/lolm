import test from "node:test";
import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import {SCHEMA,normalizeSnapshot,analyzeSnapshot,compareSnapshots,proof,verifyProof} from "../core.mjs";
import {build} from "../build.mjs";

if(!globalThis.crypto)globalThis.crypto=webcrypto;
const d="2026-11-15T19:00:00Z";
const fact=(provider,asset,signal,value)=>({provider,asset,signal,value,
 source_url:"https://example.org/provider-evidence",observed_at:d});
const base=()=>({schema:SCHEMA,captured_at:d,facts:[
 fact("github","org/sample","runtime_ssh_keyscan",true),
 fact("github","org/sample","ssh_host_key_pinned","unknown"),
 fact("github","org/sample","repo_branch_protection_verifiable","unknown"),
 fact("cloudflare","worker-a","worker_preview_enabled",true),
 fact("cloudflare","worker-a","worker_public_enabled",true),
 fact("cloudflare","worker-a","worker_privileged_bindings",true),
]});
test("actual review candidates are conditional, not breach claims",()=>{
 const report=analyzeSnapshot(base());
 assert.equal(report.assets,2);
 assert.equal(report.counts.review,2);
 assert.equal(report.counts.unknown,1);
 assert.equal(report.counts.high,0);
 assert.match(report.conclusion,/Not confirmed compromises/);
 assert.equal(report.findings.find(x=>x.check==="worker_preview_surface").evidence.length,3);
});
test("public preview alone does not prove a vulnerability",()=>{
 const b=base();
 b.facts=b.facts.filter(f=>f.provider!=="github");
 b.facts.find(x=>x.signal==="worker_privileged_bindings").value=false;
 assert.equal(analyzeSnapshot(b).findings.length,0);
});
test("pinned SSH key suppresses first-connection trust review",()=>{
 const b=base();
 b.facts.find(x=>x.signal==="ssh_host_key_pinned").value=true;
 assert.ok(!analyzeSnapshot(b).findings.some(x=>x.check==="ssh_host_trust"));
});
test("unknown branch metadata is a visibility gap, not a failure",()=>{
 const r=analyzeSnapshot(base()).findings.find(x=>x.check==="branch_protection_visibility");
 assert.equal(r.level,"unknown");
});
test("a subsequent snapshot can clear an indicator but not claim a verified fix",()=>{
 const initial=base(),after=base();
 after.captured_at="2026-11-16T19:00:00Z";
 after.facts.find(x=>x.signal==="ssh_host_key_pinned").value=true;
 after.facts.find(x=>x.signal==="worker_preview_enabled").value=false;
 after.facts.find(x=>x.signal==="repo_branch_protection_verifiable").value=true;
 const c=compareSnapshots(initial,after);
 assert.equal(c.verified_changes,0);
 assert.ok(c.deltas.every(x=>x.state==="indicator-cleared"));
 assert.match(c.conclusion,/unverified/);
});
test("missing follow-up evidence is NOT a verified remediation",()=>{
 const before=base(),after=base();
 after.facts=after.facts.filter(x=>x.signal!=="ssh_host_key_pinned"&&x.signal!=="worker_privileged_bindings");
 const results=compareSnapshots(before,after);
 assert.equal(results.deltas.find(x=>x.id.endsWith("ssh_host_trust")).state,"not-rechecked");
 assert.equal(results.deltas.find(x=>x.id.endsWith("worker_preview_surface")).state,"not-rechecked");
});
test("unrecognized or potentially secret raw fields are refused",()=>{
 const b=base();b.facts[0].api_token="xyz";
 assert.throws(()=>normalizeSnapshot(b),/unsafe/);
});
test("non-HTTPS evidence, URLs with credentials, and duplicate assertions are refused",()=>{
 const b=base();b.facts[0].source_url="https://user:secret@example.org/evidence";
 assert.throws(()=>normalizeSnapshot(b));
 const c=base();c.facts.push({...c.facts[0]});
 assert.throws(()=>normalizeSnapshot(c),/duplicate/);
});
test("proof hash rejects alteration to evidence, report, or interpretation",async()=>{
 const p=await proof(base());
 assert.match(p.sha256,/^[0-9a-f]{64}$/);
 assert.equal(await verifyProof(p),true);
 const q=structuredClone(p);
 q.assessment.findings[0].interpretation="Nothing to see!";
 assert.equal(await verifyProof(q),false);
});
test("combined write token and untrusted PR context is a review signal not exploit execution",()=>{
 const b={schema:SCHEMA,captured_at:d,facts:[
  fact("github","org/sample","workflow_token_write_permission",true),
  fact("github","org/sample","workflow_untrusted_pull_request",true),
 ]};
 const r=analyzeSnapshot(b);
 assert.equal(r.counts.high,1);
 assert.match(r.findings[0].interpretation,/Validate/);
});
test("Worker deploy artifact serves local JS but accepts no POST/upload",async()=>{
 const file=build();
 assert.match(file,/dist/);
 const worker=(await import("../dist/worker.mjs")).default;
 const response=await worker.fetch(new Request("https://qira.invalid/"));
 assert.equal(response.status,200);
 assert.match(await response.text(),/QIRA Proof/);
 assert.match(response.headers.get("content-security-policy"),/connect-src 'self'/);
 const core=await worker.fetch(new Request("https://qira.invalid/core.mjs"));
 assert.equal(core.status,200);
 const app=await worker.fetch(new Request("https://qira.invalid/app.mjs"));
 assert.match(await app.text(),/verifyProof/);
 const post=await worker.fetch(new Request("https://qira.invalid/api/upload",{method:"POST",body:"secret"}));
 assert.equal(post.status,405);
 const auth=await worker.fetch(new Request("https://qira.invalid/api/github/status"));
 assert.equal(auth.status,200);
 assert.equal((await auth.json()).configured,false);
 const connect=await worker.fetch(new Request("https://qira.invalid/connect/github"));
 assert.equal(connect.status,503);
 const health=await worker.fetch(new Request("https://qira.invalid/health"));
 assert.equal((await health.json()).uploads_enabled,false);
});
