import test from "node:test";
import assert from "node:assert/strict";
import worker from "../commercial/landing.mjs";
const root="https://proof.imagineqira.com";
const page=async(path="/",env={})=>(await worker.fetch(new Request(root+path),env));

test("task-first homepage presents one accessible repository entry instead of competing dashboards",async()=>{
 const html=await (await page()).text();
 assert.match(html,/<h1 id="uxTitle">Which repository should we review\?<\/h1>/);
 assert.match(html,/<form class="ux-entry" id="repoCheck"/);
 assert.match(html,/<label class="ux-label" for="repoUrl">GitHub repository<\/label>/);
 assert.match(html,/id="repoUrl"[^>]*required maxlength="240"/);
 assert.match(html,/id="repoSubmit" type="submit"/);
 assert.match(html,/id="repoResult" role="status" aria-live="polite"/);
 assert.match(html,/Private repository\? Skip lookup/);
 assert.doesNotMatch(html,/role="img" aria-label="Example workflow graph/);
 assert.doesNotMatch(html,/ILLUSTRATIVE \/ NOT YOUR REPO/);
 assert.match(html,/No repository is accessed/);
});

test("real source evidence replaces synthetic atlas on homepage with immutable GitHub link",async()=>{
 const html=await (await page()).text();
 assert.match(html,/An observation you can verify/);
 assert.match(html,/Workflow-level write permissions/);
 assert.match(html,/contents: write/);
 assert.match(html,/id-token: write/);
 assert.match(html,/Not established:/);
 assert.match(html,/f9700d2e661640da4a8d0cf2bb9c046d77f8a06b\/\.github\/workflows/);
 assert.match(html,/href="\/case-study"/);
 assert.doesNotMatch(html,/CONFIGURATION ≠ EXPLOIT/);
});

test("homepage client script only fetches its same-origin public inventory endpoint",async()=>{
 const r=await page(),html=await r.text();
 assert.match(r.headers.get("content-security-policy"),/connect-src 'none'/);
 assert.doesNotMatch(html,/\bfetch\s*\(/);
 assert.doesNotMatch(html,/fetch\("https?:\/\//);
 assert.doesNotMatch(html,/<script src=/);
 assert.match(html,/no account, upload, or scan/i);
 assert.match(html,/Founding review/);
});

test("layout has clear mobile input and pricing states with reduced motion support",async()=>{
 const html=await (await page()).text();
 assert.match(html,/@media\(max-width:690px\)/);
 assert.match(html,/\.ux-entry-row\{flex-wrap:wrap/);
 assert.match(html,/\.ux-entry button\{flex:1 1 100%/);
 assert.match(html,/prefers-reduced-motion:reduce/);
 assert.match(html,/href="\/#pricing"/);
 assert.match(html,/id="buyLink"/);
 assert.match(html,/\$299/);
});

test("synthetic evidence demonstration remains available and explicitly marked in sample report",async()=>{
 const response=await page("/sample-report");
 assert.equal(response.status,200);
 const html=await response.text();
 assert.match(html,/SYNTHETIC · NOT A LIVE SCAN/);
 assert.match(html,/No repository was scanned to generate these examples/);
 assert.match(html,/id="reportCode"/);
 assert.match(html,/not a security certification/i);
 assert.match(html,/data-case="scope"/);
});

test("post-purchase intake remains manual and public lookup privacy is disclosed",async()=>{
 const intake=await (await page("/start-review")).text();
 assert.match(intake,/intake-head/);
 assert.match(intake,/VERIFY WITH QIRA/);
 assert.match(intake,/does not verify payment or grant an entitlement/);
 assert.match(intake,/Email your receipt reference/);
 const privacy=await (await page("/privacy")).text();
 assert.match(privacy,/sends the repository owner\/name to GitHub's public REST API/);
 assert.match(privacy,/does not use analytics scripts or tracking cookies/);
 assert.match(privacy,/Never email access tokens/);
 const terms=await (await page("/terms")).text();
 assert.match(terms,/\$299 USD, tax-inclusive one-time/);
 assert.match(terms,/tax collection is not implied where Trend is not registered/);
});
