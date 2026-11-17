import test from "node:test";
import assert from "node:assert/strict";

class Element{
 constructor(tag="div"){this.tagName=tag;this.children=[];this.textContent="";this.hidden=false;
  this.disabled=false;this.style={};this.dataset={};this.value="";this.events={};
  this.className="";this.classList={toggle:()=>{}};}
 appendChild(x){this.children.push(x);return x}
 replaceChildren(...xs){this.children=xs}
 addEventListener(k,cb){this.events[k]=cb}
 setAttribute(k,v){this[k]=String(v)}
 click(){return this.events.click?.()}
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
test("real UI treats inaccessible workflow directory as an empty choice with useful instructions",async()=>{
 const elements=new Map(),calls=[];
 const el=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id)};
 globalThis.document={body:new Element("body"),getElementById:el,createElement:tag=>new Element(tag),
  querySelectorAll:()=>[]};
 globalThis.Option=class Option{constructor(label,value){this.label=label;this.value=value}};
 globalThis.location={href:"https://qira.example/"};
 globalThis.history={replaceState:()=>{}};
 globalThis.fetch=async(url,options={})=>{
  calls.push(String(url));
  let result;
  if(url==="/api/github/status")result={configured:true,connected:true,csrf:"test-csrf",install_url:null};
  else if(url==="/api/github/installations")result={items:[{id:123,account:"TheArtOfSound",selection:"all"}],truncated:false};
  else if(url==="/api/github/repos")result={repos:[{name:"TheArtOfSound/ResumeAI",branch:"main"}],truncated:false};
  else if(url==="/api/github/workflows")result={repo:"TheArtOfSound/ResumeAI",branch:"main",workflows:[],truncated:false,
   availability:"directory_not_found_or_inaccessible"};
  else throw Error("Unexpected URL "+url);
  return new Response(JSON.stringify(result),{status:200,headers:{"content-type":"application/json"}});
 };
 await import("../app.mjs?ui-empty-workflow-2026-11-16");
 await tick();await tick();
 assert.equal(document.body.dataset.githubConnection,"connected");
 el("gitInstallation").value="123";
 await el("gitInstallation").events.change({target:{value:"123"}});
 el("gitRepository").value="TheArtOfSound/ResumeAI";
 await el("gitRepository").events.change({target:{value:"TheArtOfSound/ResumeAI"}});
 assert.equal(el("gitWorkflow").disabled,true);
 assert.equal(el("gitAssess").disabled,true);
 assert.match(el("gitMessage").textContent,/workflow directory is absent or inaccessible/);
 assert.match(el("gitMessage").textContent,/Choose a different repository/);
 assert.equal(el("gitWorkflow").children[0].label,"No accessible workflows on this branch");
 assert.ok(calls.includes("/api/github/workflows"));
 assert.equal(document.body.dataset.reportType,"unstarted");
});
