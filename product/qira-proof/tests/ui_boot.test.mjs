import test from "node:test";
import assert from "node:assert/strict";

class FakeElement{
  constructor(tag="div"){
    this.tagName=tag;this.children=[];this.textContent="";this.hidden=false;this.disabled=false;
    this.style={};this.dataset={};this.value="";this.events={};this.className="";
    this.classList={toggle:()=>{}};
  }
  appendChild(el){this.children.push(el);return el}
  replaceChildren(...els){this.children=els;return this}
  setAttribute(k,v){this[k]=String(v)}
  addEventListener(k,fn){this.events[k]=fn}
  getAttribute(k){return this[k]??null}
  click(){this.events.click?.()}
}
test("actual page module initializes GitHub status on startup (not only after file import)",async()=>{
  const ids=new Map();
  const el=(id)=>{if(!ids.has(id))ids.set(id,new FakeElement());return ids.get(id)};
  const fetched=[];
  globalThis.document={
    body:new FakeElement("body"),getElementById:el,
    createElement:tag=>new FakeElement(tag),
    querySelectorAll:selector=>[]
  };
  globalThis.location={href:"https://qira.example/"};
  globalThis.history={replaceState:()=>{}};
  globalThis.fetch=async(url)=>{
    fetched.push(String(url));
    if(String(url)==="/api/github/status")return new Response(JSON.stringify({
      configured:false,connected:false,csrf:null,install_url:null,expires_at:null
    }),{status:200,headers:{"content-type":"application/json"}});
    throw new Error("unexpected browser network call");
  };
  await import("../app.mjs?ui-smoke=2026-11-15");
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(document.body.dataset.qiraBoot,"ready");
  assert.equal(document.body.dataset.githubConnection,"pending-setup");
  assert.equal(el("gitBadge").textContent,"Pending setup");
  assert.equal(el("reviewCount").textContent,2);
  assert.equal(document.body.dataset.reportType,"unstarted");
  assert.equal(el("reportIntro").hidden,false);
  assert.equal(el("assessmentData").hidden,true);
  assert.equal(el("sampleBanner").hidden,true);
  el("startSample").click();
  assert.equal(document.body.dataset.reportType,"example");
  assert.equal(el("reportIntro").hidden,true);
  assert.equal(el("assessmentData").hidden,false);
  assert.equal(el("sampleBanner").hidden,false);
  assert.equal(el("unknownCount").textContent,1);
  assert.deepEqual(fetched,["/api/github/status"]);
  assert.ok(el("baselineInput").events.change);
  assert.ok(el("gitAssess").events.click);
  assert.ok(el("gitDisconnect").events.click);
});
