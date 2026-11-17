import test from "node:test";
import assert from "node:assert/strict";
class Element{
 constructor(tag="div"){this.tagName=tag;this.children=[];this.textContent="";this.hidden=false;
  this.disabled=false;this.style={};this.dataset={};this.value="";this.events={};
  this.className="";this.classList={toggle:()=>{}};this.tabIndex=0;}
 appendChild(v){this.children.push(v);return v}
 replaceChildren(...v){this.children=v}
 addEventListener(name,fn){this.events[name]=fn}
 setAttribute(key,value){this[key]=String(value)}
 focus(){}
}
const tick=()=>new Promise(done=>setImmediate(done));
test("switching repositories cannot display stale workflows from an earlier selection",async()=>{
 const elements=new Map();
 const el=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id)};
 globalThis.document={body:new Element("body"),getElementById:el,createElement:n=>new Element(n),querySelectorAll:()=>[]};
 globalThis.Option=class Option{constructor(label,value){this.label=label;this.value=value}};
 globalThis.location={href:"https://qira.example/"};
 globalThis.history={replaceState:()=>{}};
 let releaseAlpha;
 const alpha=new Promise(resolve=>{releaseAlpha=resolve});
 globalThis.fetch=async(url,opts={})=>{
  if(url==="/api/github/status")return Response.json({configured:true,connected:true,csrf:"csrf",install_url:null});
  if(url==="/api/github/installations")return Response.json({items:[{id:123,account:"owner",selection:"all"}],truncated:false});
  if(url==="/api/github/repos")return Response.json({repos:[{name:"owner/alpha",branch:"main"},{name:"owner/beta",branch:"main"}],truncated:false});
  if(url==="/api/github/workflows"){
   const repo=JSON.parse(opts.body).repo;
   if(repo==="owner/alpha"){await alpha;return Response.json({workflows:[{path:".github/workflows/alpha.yml"}]})}
   if(repo==="owner/beta")return Response.json({workflows:[{path:".github/workflows/beta.yml"}]});
  }
  throw Error("Unexpected service call: "+url);
 };
 await import("../app.mjs?race=20261116");
 await tick();await tick();
 el("gitInstallation").value="123";
 await el("gitInstallation").events.change({target:{value:"123"}});
 el("gitRepository").value="owner/alpha";
 const pendingAlpha=el("gitRepository").events.change({target:{value:"owner/alpha"}});
 el("gitRepository").value="owner/beta";
 await el("gitRepository").events.change({target:{value:"owner/beta"}});
 releaseAlpha();
 await pendingAlpha;
 assert.equal(el("gitWorkflow").children[1].value,".github/workflows/beta.yml");
 assert.equal(el("gitWorkflow").children.some(x=>x.value===".github/workflows/alpha.yml"),false);
 assert.match(el("gitMessage").textContent,/Review the repository or select one workflow/);
});
