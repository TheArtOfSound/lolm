import test from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import worker from "../commercial/landing.mjs";

const base="https://proof.imagineqira.com";
const visit=async(path,env={})=>{
 const response=await worker.fetch(new Request(base+path),env);
 return {response,html:await response.text()};
};
const lastInlineScript=html=>{
 const scripts=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
 assert.ok(scripts.length>0,"Interactive page should provide at least one first-party script");
 return scripts.at(-1)[1];
};

test("the full-width sample report has an accessible evidence navigation and strict synthetic labels",async()=>{
 const {response,html}=await visit("/sample-report");
 assert.equal(response.status,200);
 assert.match(html,/<title>Explore sample report \| Qira Proof<\/title>/);
 assert.match(html,/OPEN THE/);
 assert.match(html,/SYNTHETIC · NOT A LIVE SCAN/);
 assert.match(html,/No repository was scanned to generate these examples/);
 assert.match(html,/NOT A SECURITY CERTIFICATION|not a security certification/i);
 assert.match(html,/id="reportCode"/);
 assert.match(html,/id="reportNext"/);
 assert.match(html,/id="reportLimits"/);
 assert.match(html,/role="group" aria-label="Select a synthetic finding"/);
 for(const variant of ["action","scope","ssh"])
  assert.match(html,new RegExp('data-case="'+variant+'" aria-pressed="(?:true|false)"'));
 assert.match(html,/href="\/#pricing"/);
 assert.match(html,/id="printReport"/);
 assert.match(html,/class="shell report-stage"/);
 assert.doesNotMatch(html,/<article class="shell legal[^"]*"><div class="section-headline">Qira Proof \/ Help desk<\/div><div class="report-page">/);
});

test("the full sample report switches source, recommendation, limitation and state in one action",async()=>{
 const {html}=await visit("/sample-report");
 const buttons=["action","scope","ssh"].map(key=>({
  dataset:{case:key},attrs:{},handlers:{},focused:false,
  addEventListener(event,callback){this.handlers[event]=callback;},
  setAttribute(key,value){this.attrs[key]=value;},
  focus(){this.focused=true;}
 }));
 const elements=Object.fromEntries(["reportTitle","reportSummary","reportSource","reportLimits","reportCode","reportNext","reportConfidence","reportCategory","reportPosition","reportAnnounce"].map(id=>[id,{textContent:""}]));
 let printed=0;const printer={handlers:{},addEventListener(kind,handler){this.handlers[kind]=handler;}};
 const doc={
  querySelectorAll(selector){assert.equal(selector,"[data-case]");return buttons;},
  getElementById(id){if(id==="printReport")return printer;assert.ok(elements[id],id);return elements[id];}
 };
 vm.runInNewContext(lastInlineScript(html),{document:doc,window:{print(){printed++;}}});
 const expectations=[
  {key:"scope",title:"Declared GitHub token write capability",reference:": 8",code:"id-token: write",next:"OIDC"},
  {key:"ssh",title:"SSH host-key discovery in a build step",reference:": 44",code:"ssh-keyscan",next:"fingerprints"},
  {key:"action",title:"Mutable external action reference",reference:": 27",code:"checkout@v4",next:"action publisher"}
 ];
 for(const item of expectations){
  const b=buttons.find(x=>x.dataset.case===item.key);
  b.handlers.click();
  assert.equal(elements.reportTitle.textContent,item.title);
  assert.match(elements.reportPosition.textContent,/QIRA PROOF \/ EXAMPLE REPORT \/ 0[1-3] OF 03/);
  assert.match(elements.reportAnnounce.textContent,/selected; [1-3] of 03/);
  assert.ok(elements.reportSource.textContent.endsWith(item.reference));
  assert.ok(elements.reportCode.textContent.includes(item.code));
  assert.match(elements.reportNext.textContent,new RegExp(item.next,"i"));
  assert.ok(elements.reportLimits.textContent.length>30);
  assert.equal(b.attrs["aria-pressed"],"true");
  assert.ok(buttons.filter(other=>other!==b).every(other=>other.attrs["aria-pressed"]==="false"));
 }
 printer.handlers.click();assert.equal(printed,1);
});

test("sample report keyboard controls rotate selection and move focus",async()=>{
 const {html}=await visit("/sample-report");
 const keys=["action","scope","ssh"];
 const buttons=keys.map(key=>({dataset:{case:key},attrs:{},handlers:{},focused:0,
  addEventListener(kind,fn){this.handlers[kind]=fn;},setAttribute(k,v){this.attrs[k]=v;},focus(){this.focused++;}
 }));
 const ids=["reportTitle","reportSummary","reportSource","reportLimits","reportCode","reportNext","reportConfidence","reportCategory","reportPosition","reportAnnounce"];
 const elements=Object.fromEntries(ids.map(id=>[id,{textContent:""}]));
 vm.runInNewContext(lastInlineScript(html),{document:{querySelectorAll:()=>buttons,getElementById:id=>elements[id]||null},window:{print(){}}});
 let prevented=0;
 buttons[0].handlers.keydown({key:"ArrowRight",preventDefault(){prevented++;}});
 assert.equal(buttons[1].focused,1);
 assert.equal(buttons[1].attrs["aria-pressed"],"true");
 assert.match(elements.reportPosition.textContent,/02 OF 03/);
 buttons[1].handlers.keydown({key:"End",preventDefault(){prevented++;}});
 assert.equal(buttons[2].attrs["aria-pressed"],"true");
 assert.match(elements.reportAnnounce.textContent,/03 of 03/);
 buttons[2].handlers.keydown({key:"Home",preventDefault(){prevented++;}});
 assert.equal(buttons[0].attrs["aria-pressed"],"true");
 assert.match(elements.reportPosition.textContent,/01 OF 03/);
 assert.equal(prevented,3);
});

test("intake composer is local-only, labeled and does not claim payment confirmation",async()=>{
 const {response,html}=await visit("/start-review");
 assert.equal(response.status,200);
 assert.match(html,/<form id="intakeComposer"/);
 assert.match(html,/<label for="intakeEmail">/);
 assert.match(html,/<label for="intakeReceipt">/);
 assert.match(html,/<label for="intakeRepo">/);
 assert.match(html,/LOCAL ONLY \/ NO UPLOAD/);
 assert.match(html,/Email your receipt reference/);
 assert.match(html,/does not verify payment or grant an entitlement/);
 assert.match(html,/No data has been sent by this website/);
 assert.match(response.headers.get("content-security-policy"),/form-action 'none'/);
 assert.doesNotMatch(html,/<form[^>]*action="https?:/);
});

test("intake composer opens encoded email without collecting information server-side",async()=>{
 const {html}=await visit("/start-review");
 const state={intakeEmail:{value:"person@example.com"},intakeReceipt:{value:"rcpt_123_A"},intakeRepo:{value:"owner/repo"},composerOutput:{textContent:""}};
 const form={handlers:{},addEventListener(k,v){this.handlers[k]=v;}};
 const destinations=[];
 vm.runInNewContext(lastInlineScript(html),{
  document:{getElementById:id=>id==="intakeComposer"?form:state[id]},
  window:{location:{assign:uri=>destinations.push(uri)}}
 });
 let prevented=false;
 form.handlers.submit({preventDefault(){prevented=true;}});
 assert.equal(prevented,true);
 assert.equal(destinations.length,1);
 assert.match(destinations[0],/^mailto:bryanleonard@imagineqira\.com\?subject=/);
 assert.ok(decodeURIComponent(destinations[0]).includes("Checkout email: person@example.com"));
 assert.ok(decodeURIComponent(destinations[0]).includes("Stripe receipt reference: rcpt_123_A"));
 assert.ok(decodeURIComponent(destinations[0]).includes("GitHub repository: owner/repo"));
 assert.match(state.composerOutput.textContent,/No data has been sent/);
});

test("intake composer rejects secret-looking strings and invalid repository entries",async()=>{
 const {html}=await visit("/start-review");
 const field={intakeEmail:{value:"buyer@example.com"},intakeReceipt:{value:"ghp_fakeSecret"},intakeRepo:{value:"owner/repo"},composerOutput:{textContent:""}};
 const form={handlers:{},addEventListener(k,fn){this.handlers[k]=fn;}};
 const sent=[];
 vm.runInNewContext(lastInlineScript(html),{document:{getElementById:id=>id==="intakeComposer"?form:field[id]},window:{location:{assign:x=>sent.push(x)}}});
 const event={preventDefault(){}};
 form.handlers.submit(event);
 assert.equal(sent.length,0);
 assert.match(field.composerOutput.textContent,/Do not provide credentials/);
 field.intakeReceipt.value="rcpt_001";
 field.intakeRepo.value="not a repo path";
 form.handlers.submit(event);
 assert.equal(sent.length,0);
 assert.match(field.composerOutput.textContent,/owner\/repository/);
});

test("sample and intake changes cannot override the live Stripe checkout binding",async()=>{
 const link="https://buy.stripe.com/9B63cvexo0ts3OBfyv7kc07";
 const {html}=await visit("/",{QIRA_PROOF_CHECKOUT_URL:link});
 assert.match(html,/id="buyLink"/);
 assert.match(html,new RegExp('href="'+link.replace(/\./g,"\\.")+'"'));
 assert.match(html,/href="\/sample-report"/);
 const health=await worker.fetch(new Request(base+"/health"),{QIRA_PROOF_CHECKOUT_URL:link});
 assert.equal((await health.json()).checkout_configured,true);
 const sample=await visit("/sample-report",{QIRA_PROOF_CHECKOUT_URL:link});
 assert.equal(sample.response.status,200);
 assert.doesNotMatch(sample.html,/Stripe receipt reference: rcpt_/);
});

test("selected report is announced without disturbing sighted content",async()=>{
 const {html}=await visit("/sample-report");
 assert.match(html,/id="reportPosition"/);
 assert.match(html,/id="reportAnnounce" class="sr-only" aria-live="polite" aria-atomic="true"/);
 assert.match(html,/\.sr-only\{position:absolute!important/);
});
