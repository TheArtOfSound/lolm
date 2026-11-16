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
 const ids=["signalTitle","signalText","sourceLine","signalType","graphLabelTiny","graphLabel","graphLabelSub"];
 const elements=Object.fromEntries(ids.map(id=>[id,{textContent:""}]));
 const document={
  querySelectorAll(selector){assert.equal(selector,"[data-signal]");return buttons;},
  getElementById(id){assert.ok(elements[id],"Unknown evidence field "+id);return elements[id];}
 };
 vm.runInNewContext(script,{document});
 const expected=[
  {signal:"action",title:"Mutable action reference",line:"27",node:"action@v4"},
  {signal:"scope",title:"Declared write permission",line:"8",node:"contents"},
  {signal:"ssh",title:"SSH host discovery",line:"44",node:"ssh-keyscan"}
 ];
 for(const item of expected){
  const button=buttons.find(x=>x.dataset.signal===item.signal);
  assert.equal(typeof button.listeners.click,"function");
  button.listeners.click();
  assert.equal(elements.signalTitle.textContent,item.title);
  assert.ok(elements.sourceLine.textContent.endsWith(" : "+item.line));
  assert.equal(elements.graphLabel.textContent,item.node);
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
