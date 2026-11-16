import test from "node:test";
import assert from "node:assert/strict";
import worker from "../commercial/landing.mjs";
const origin="https://proof.imagineqira.com";
const view=async(path,env={})=>await(await worker.fetch(new Request(origin+path),env)).text();

test("homepage gives a single immediate action before proof, explanation and payment",async()=>{
 const html=await view("/");
 const input=html.indexOf('id="repoUrl"'),proof=html.indexOf('class="ux-proof"'),process=html.indexOf('id="process"'),pricing=html.indexOf('id="pricing"');
 assert.ok(input>=0&&proof>input&&process>proof&&pricing>process);
 assert.match(html,/Which repository should we review\?/);
 assert.match(html,/id="repoSubmit" type="submit"/);
 assert.match(html,/no account, upload, or scan/i);
 assert.match(html,/Private repository\? Skip lookup/);
 assert.doesNotMatch(html,/Understand what your workflows trust/);
 assert.doesNotMatch(html,/KNOW MORE\.<br>/);
});

test("real workflow evidence is prominently labeled as source observation, not a pretend scan",async()=>{
 const html=await view("/");
 assert.match(html,/From the actual source/);
 assert.match(html,/Workflow-level write permissions/);
 assert.match(html,/Not established:/);
 assert.match(html,/Inspect the exact GitHub lines/);
 assert.match(html,/No repository is accessed/);
 assert.match(html,/href="\/case-study"/);
 assert.doesNotMatch(html,/class="proof-board"/);
});

test("visual system is responsive, reduced-motion friendly, and removes fake dashboard theater",async()=>{
 const html=await view("/");
 assert.match(html,/V9: task-first site architecture/);
 assert.match(html,/\.ux-hero h1\{font:400 clamp\(/);
 assert.match(html,/\.ux-entry-row:focus-within/);
 assert.match(html,/\.ux-result\[hidden\]\{display:none!important/);
 assert.match(html,/@media\(max-width:690px\)/);
 assert.match(html,/@media\(prefers-reduced-motion:reduce\)/);
 assert.doesNotMatch(html,/class="proof-board"/);
});

test("exact hosted Stripe checkout and public examples remain reachable",async()=>{
 const url="https://buy.stripe.com/9B63cvexo0ts3OBfyv7kc07";
 const html=await view("/",{QIRA_PROOF_CHECKOUT_URL:url});
 assert.match(html,/id="buyLink"/);
 assert.match(html,new RegExp('href="'+url.replaceAll(".","\\.")+'"'));
 assert.match(html,/href="\/case-study"/);
 assert.match(html,/href="\/methodology"/);
 assert.match(html,/href="\/guides"/);
 const health=await worker.fetch(new Request(origin+"/health"),{QIRA_PROOF_CHECKOUT_URL:url});
 assert.equal((await health.json()).checkout_configured,true);
});

test("mobile navigation offers a single clear action while intake remains human-readable",async()=>{
 const home=await view("/");
 assert.match(home,/\.navi a:not\(\.navbuy\)\{display:none\}/);
 assert.match(home,/href="\/#start">Start review/);
 const intake=await view("/start-review");
 assert.match(intake,/From payment<br>to review\./);
 assert.match(intake,/Your review,<br>step by step\./);
 assert.doesNotMatch(intake,/LET'S<br>GET TO<br>/);
});
