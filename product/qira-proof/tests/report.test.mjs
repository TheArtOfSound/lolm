import test from "node:test";
import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import {SCHEMA,proof} from "../core.mjs";
import {renderHumanReport} from "../report.mjs";
if(!globalThis.crypto)globalThis.crypto=webcrypto;
const ts="2026-11-15T19:00:00Z";
const item=(provider,asset,signal,value)=>({
 provider,asset,signal,value,source_url:"https://example.org/a",observed_at:ts
});
const snapshot=()=>({schema:SCHEMA,captured_at:ts,facts:[
 item("github","owner/repo","workflow_unpinned_actions",true),
 item("github","owner/repo","repo_branch_protection_verifiable","unknown"),
 item("cloudflare","worker","worker_preview_enabled",false),
 item("vercel","project","vercel_deployment_protection_configured",true)
]});
test("printable report contains a verified receipt, evidence coverage, and conservative findings",async()=>{
 const artifact=await proof(snapshot());
 const html=await renderHumanReport(artifact);
 assert.match(html,/Infrastructure configuration assessment/);
 assert.match(html,/GITHUB/);
 assert.match(html,/CLOUDFLARE/);
 assert.match(html,/VERCEL/);
 assert.match(html,/Third-party CI actions use mutable/);
 assert.match(html,/Branch protection could not be verified/);
 assert.match(html,/not a penetration test/i);
 assert.ok(html.includes(artifact.sha256));
 assert.ok(!/<script/i.test(html));
 assert.ok(!/<img/i.test(html));
 assert.match(html,/Content-Security-Policy/);
});
test("fictional samples are prominently labeled as fictional",async()=>{
 const html=await renderHumanReport(await proof(snapshot()),{sample:true});
 assert.match(html,/FICTIONAL EXAMPLE — NOT A CUSTOMER ASSESSMENT/);
 assert.match(html,/Fictional demonstration only/);
});
test("tampered or incomplete receipts cannot produce a printable report",async()=>{
 const p=await proof(snapshot());
 const modified=structuredClone(p);
 modified.baseline.facts[0].value=false;
 await assert.rejects(renderHumanReport(modified),/verification/);
 await assert.rejects(renderHumanReport({}),/verification/);
});
test("untrusted asset and source strings cannot inject markup into human report",async()=>{
 const dangerous='<img src=x onerror=alert(1)>';
 const s=snapshot();s.facts[0].asset=dangerous;
 // update every fact for the same asset to remain consistent
 s.facts[1].asset=dangerous;
 const html=await renderHumanReport(await proof(s));
 assert.ok(!html.includes(dangerous));
 assert.ok(html.includes("&lt;img src=x onerror=alert(1)&gt;"));
 assert.ok(!/<img\s/i.test(html));
});
test("no findings does not imply security certification",async()=>{
 const s={schema:SCHEMA,captured_at:ts,facts:[item("cloudflare","worker","worker_preview_enabled",false)]};
 const html=await renderHumanReport(await proof(s));
 assert.match(html,/No configured Qira rule matched/);
 assert.match(html,/not a clean bill of health/);
});
