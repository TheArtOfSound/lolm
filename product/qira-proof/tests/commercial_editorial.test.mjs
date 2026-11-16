import test from "node:test";
import assert from "node:assert/strict";
import worker from "../commercial/landing.mjs";
const origin="https://proof.imagineqira.com";
const view=async(path,env={})=>await (await worker.fetch(new Request(origin+path),env)).text();

test("homepage leads with bounded human-reviewed service, not fictitious scanner theater",async()=>{
 const html=await view("/");
 assert.match(html,/<h1 id="heroTitle">Understand what your workflows trust\.<\/h1>/);
 assert.match(html,/An independent, human-reviewed assessment/);
 assert.match(html,/What the review covers/);
 assert.match(html,/Up to 20 GitHub Actions workflows/);
 assert.match(html,/one-time, tax-inclusive/);
 assert.match(html,/Scope matters/);
 assert.doesNotMatch(html,/DON'T<br>SHIP/);
 assert.doesNotMatch(html,/KNOW MORE\.<br>/);
 assert.doesNotMatch(html,/LESS NOISE\.<br>/);
});
test("synthetic diagram is moved below scope brief with no misleading real data impression",async()=>{
 const html=await view("/");
 const hero=html.indexOf('<section class="shell hero"'),demo=html.indexOf('<section class="product-demo"'),diagram=html.indexOf('class="proof-board"');
 assert.ok(hero>=0&&demo>hero&&diagram>demo);
 assert.match(html,/Illustrative review \/ not a repository scan/);
 assert.match(html,/ILLUSTRATIVE \/ NOT YOUR REPO/);
 assert.match(html,/NOT A SECURITY CERTIFICATION/);
 assert.match(html,/id="sourceCode"/);
});
test("site styling removes fluorescent hero, rotated badges and card theater",async()=>{
 const html=await view("/");
 assert.match(html,/Qira Proof \/ editorial identity/);
 assert.match(html,/\.hero h1\{font:400 clamp\(/);
 assert.match(html,/\.ribbon\{display:none\}/);
 assert.match(html,/\.proof-board\{[^}]*box-shadow:none/);
 assert.match(html,/\.logomark\{[^}]*transform:none/);
 assert.match(html,/@media\(prefers-reduced-motion:reduce\)/);
 assert.match(html,/\.cta\.primary\{background:var\(--navy\)/);
});
test("live purchase link and customer evidence paths remain intact after restructuring",async()=>{
 const url="https://buy.stripe.com/9B63cvexo0ts3OBfyv7kc07";
 const html=await view("/",{QIRA_PROOF_CHECKOUT_URL:url});
 assert.match(html,/id="buyLink"/);
 assert.match(html,new RegExp('href="'+url.replaceAll(".","\\.")+'"'));
 assert.match(html,/href="\/sample-report"/);
 assert.match(html,/href="\/start-review"/);
 const health=await worker.fetch(new Request(origin+"/health"),{QIRA_PROOF_CHECKOUT_URL:url});
 assert.equal((await health.json()).checkout_configured,true);
});
