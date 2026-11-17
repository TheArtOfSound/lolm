import test from "node:test";
import assert from "node:assert/strict";
import worker from "../commercial/landing.mjs";
import {enhanceJourney,JOURNEY_CSS} from "../commercial/site_journey.mjs";
const origin="https://proof.imagineqira.com";
const render=async path=>(await worker.fetch(new Request(origin+path))).text();
const routes=["/","/case-study","/sample-report","/methodology","/guides","/guides/github-actions-permissions","/guides/github-actions-dependency-pinning","/guides/ssh-host-key-verification","/guides/release-gate-failure-modes","/privacy","/terms","/start-review"];

test("unified navigation exists on every customer-facing HTML route",async()=>{
 for(const path of routes){
  const html=await render(path);
  assert.match(html,/<nav class="navi" aria-label="Primary">/,path);
  assert.match(html,/<details class="site-menu"><summary>Menu<\/summary>/,path);
  assert.match(html,/class="site-menu-links"/,path);
  assert.match(html,/href="\/case-study"/,path);
  assert.match(html,/href="\/sample-report"/,path);
  assert.match(html,/href="\/guides"/,path);
  assert.match(html,/href="\/start-review"/,path);
  assert.match(html,/\.site-menu summary\{cursor:pointer/,path);
  assert.match(html,/@media\(max-width:820px\)\{\.site-menu\{display:block\}/,path);
  assert.equal((html.match(/<main id="main">/g)||[]).length,1,path);
 }
});
test("current location is marked for desktop and mobile, with one contextual breadcrumb",async()=>{
 for(const path of routes.slice(1)){
  const html=await render(path);
  assert.match(html,/aria-label="Breadcrumb"/,path);
  assert.match(html,/class="shell site-path-inner"/,path);
  assert.match(html,/aria-current="page"/,path);
  assert.ok(html.indexOf('aria-label="Breadcrumb"')<html.indexOf('<main id="main">'),path);
 }
 const child=await render("/guides/github-actions-permissions");
 assert.match(child,/<a href="\/guides">Guides<\/a><span>\/<\/span><strong aria-current="page">Token permissions<\/strong>/);
 const home=await render("/");
 assert.doesNotMatch(home,/aria-label="Breadcrumb"/);
});
test("real case study exposes the findings immediately and an optional next action",async()=>{
 const html=await render("/case-study");
 assert.match(html,/href="#rcWorkflow">Jump to the actual findings/);
 assert.match(html,/aria-label="Related actions"/);
 assert.match(html,/Review my repository/);
 assert.match(html,/href="\/sample-report"/);
 assert.match(html,/not current-state findings/);
});
test("example report mobile controls use three compact tabs instead of stacked choices",async()=>{
 const html=await render("/sample-report");
 assert.match(html,/grid-template-columns:repeat\(3,minmax\(0,1fr\)\)!important/);
 assert.match(html,/<button type="button" data-case="scope" aria-pressed="false">/);
 assert.match(html,/id="reportCode"/);
 assert.match(html,/role="group" aria-label="Select a synthetic finding"/);
});
test("guides and terms provide navigation without turning content into sales funnels",async()=>{
 for(const path of ["/guides","/methodology","/terms","/privacy","/guides/release-gate-failure-modes"]){
  const html=await render(path);
  assert.match(html,/Where next\?/);
  assert.match(html,/href="\/#start"/);
  assert.match(html,/href="\/case-study"/);
 }
 const guide=await render("/guides/github-actions-permissions");
 assert.match(guide,/aria-current="page">Security guides/);
 assert.match(guide,/href="\/guides">All field notes/);
});
test("paid intake retains the status and three-field interaction without an extra sales block",async()=>{
 const html=await render("/start-review");
 assert.match(html,/id="intakeComposer"/);
 assert.match(html,/id="intakeEmail"/);
 assert.match(html,/id="intakeReceipt"/);
 assert.match(html,/id="intakeRepo"/);
 assert.doesNotMatch(html,/class="site-next"/);
 assert.match(html,/class="site-path"/);
 assert.match(html,/meta name="robots" content="noindex,follow"/);
});
test("unknown pages remain noindex and no mirrored checkout is introduced",async()=>{
 const missing=await worker.fetch(new Request(origin+"/not-a-real-route"));
 assert.equal(missing.status,404);
 assert.equal(missing.headers.get("x-robots-tag"),"noindex");
 const home=await render("/");
 assert.match(home,/id="buyLink"/);
 assert.match(home,/Which repository should we review/);
 assert.doesNotMatch(home,/class="site-next"/);
});
test("consistent navigation remains progressive without scripts or external assets",()=>{
 const stub='<html><head><style></style></head><body><header><nav class="navi" aria-label="Primary"><a href="/">Original</a></nav></header><main id="main"><h1>Example</h1></main></body></html>';
 const a=enhanceJourney(stub,"/privacy");
 assert.match(a,/aria-label="Breadcrumb"/);
 assert.match(a,/aria-label="Related actions"/);
 assert.match(a,/class="site-menu"/);
 assert.doesNotMatch(a,/<script|<img/);
 assert.ok(JOURNEY_CSS.includes(".site-next-links"));
 assert.ok(JOURNEY_CSS.includes(".report-toggles"));
});
