import test from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import worker from "../commercial/landing.mjs";

test("editorial evidence atlas renders a source-labeled nonfiction-safe mock diagram",async()=>{
 const r=await worker.fetch(new Request("https://proof.imagineqira.com/"));
 const html=await r.text();
 assert.match(html,/role="img" aria-label="Example workflow graph/);
 assert.match(html,/ILLUSTRATIVE \/ NOT YOUR REPO/);
 assert.match(html,/CONFIGURATION ≠ EXPLOIT/);
 assert.match(html,/NOT A SECURITY CERTIFICATION/);
 assert.match(html,/NOT RECURRING/);
 assert.match(html,/prefers-reduced-motion:reduce/);
 for(const key of ["action","scope","ssh"]){
  assert.match(html,new RegExp('data-signal="'+key+'" aria-pressed="(?:true|false)"'));
 }
 assert.match(html,/<a[^>]*href="#pricing"[^>]*>[\s\S]*?Get a founding review/);
});
test("clicking every evidence category changes its explanation, source reference and pressed state",async()=>{
 const html=await (await worker.fetch(new Request("https://proof.imagineqira.com/"))).text();
 const script=html.match(/<script>([\s\S]*?)<\/script>/)?.[1];
 assert.ok(script,"Expected isolated first-party interaction script");
 const buttons=["action","scope","ssh"].map(signal=>({
  dataset:{signal},attrs:{},listeners:{},
  addEventListener(type,listener){this.listeners[type]=listener;},
  setAttribute(key,value){this.attrs[key]=value;}
 }));
 const ids=["signalTitle","signalText","sourceLine","signalType","graphLabelTiny","graphLabel","graphLabelSub","sourceCode"];
 const elements=Object.fromEntries(ids.map(id=>[id,{textContent:""}]));
 const document={
  querySelectorAll(selector){assert.equal(selector,"[data-signal]");return buttons;},
  getElementById(id){assert.ok(elements[id],"Unknown evidence field "+id);return elements[id];}
 };
 vm.runInNewContext(script,{document});
 const expected=[
  {signal:"action",title:"Mutable action reference",line:"27",node:"action@v4",source:"uses: actions/checkout@v4"},
  {signal:"scope",title:"Declared write permission",line:"8",node:"contents",source:"id-token: write"},
  {signal:"ssh",title:"SSH host discovery",line:"44",node:"ssh-keyscan",source:"ssh-keyscan -H"}
 ];
 for(const item of expected){
  const button=buttons.find(x=>x.dataset.signal===item.signal);
  assert.equal(typeof button.listeners.click,"function");
  button.listeners.click();
  assert.equal(elements.signalTitle.textContent,item.title);
  assert.ok(elements.sourceLine.textContent.endsWith(" : "+item.line));
  assert.equal(elements.graphLabel.textContent,item.node);
  assert.ok(elements.sourceCode.textContent.includes(item.source),"The source excerpt must follow the selected observation");
  assert.match(elements.signalText.textContent,/\S{8}/);
  assert.equal(button.attrs["aria-pressed"],"true");
  assert.ok(buttons.filter(x=>x!==button).every(x=>x.attrs["aria-pressed"]==="false"));
 }
});
test("mobile layout keeps primary actions and CSS-only workflow graphic without network calls",async()=>{
 const html=await (await worker.fetch(new Request("https://proof.imagineqira.com/"))).text();
 assert.match(html,/@media\(max-width:510px\)/);
 assert.match(html,/\.ctas \.cta\{width:100%\}/);
 assert.match(html,/<a class="cta ghost" href="https:\/\/qira-proof-auth-lab-[^"]+\/"><span>Try the read-only preview<\/span>/);
 assert.match(html,/href="\/start-review"/);
 assert.doesNotMatch(html,/src="https?:\/\//);
 assert.doesNotMatch(html,/\bfetch\(/);
});

test("report specimen is prominently marked synthetic and includes actionable evidence structure",async()=>{
 const html=await (await worker.fetch(new Request("https://proof.imagineqira.com/"))).text();
 assert.match(html,/An example of the final report\./);
 assert.match(html,/See what is in the report before buying/);
 assert.match(html,/ILLUSTRATIVE SAMPLE/);
 assert.match(html,/THIS SAMPLE IS SYNTHETIC, NOT A REAL CUSTOMER RESULT/);
 assert.match(html,/NOT PROVEN/);
 assert.match(html,/RECOMMENDED REVIEW/);
 assert.match(html,/id="sourceCode"/);
 assert.match(html,/TRACE \/ WORKFLOW SOURCE EXCERPT/);
});
test("post-purchase intake is a guided dossier rather than an auto-verification promise",async()=>{
 const res=await worker.fetch(new Request("https://proof.imagineqira.com/start-review"));
 assert.equal(res.status,200);
 const html=await res.text();
 assert.match(html,/intake-head/);
 assert.match(html,/intake-rail/);
 assert.match(html,/intake-actions/);
 assert.match(html,/VERIFY WITH QIRA/);
 assert.match(html,/Email your receipt reference/);
 assert.match(html,/does not verify payment or grant an entitlement/);
 assert.match(html,/Email paid-review intake/);
 assert.match(html,/Never email passwords/);
 assert.match(html,/up to 20 GitHub Actions workflow files/);
 assert.match(html,/mailto:bryanleonard@imagineqira.com/);
});
test("legal content describes $299 inclusive Stripe Tax without falsely claiming registration",async()=>{
 const terms=await (await worker.fetch(new Request("https://proof.imagineqira.com/terms"))).text();
 assert.match(terms,/\$299 USD, tax-inclusive one-time/);
 assert.match(terms,/Stripe automatic tax uses your billing details/);
 assert.match(terms,/tax collection is not implied where Trend is not registered/);
 const privacy=await (await worker.fetch(new Request("https://proof.imagineqira.com/privacy"))).text();
 assert.match(privacy,/does not use tracking cookies/);
 assert.match(privacy,/Stripe handles checkout, invoices and billing information for Trend/);
});
