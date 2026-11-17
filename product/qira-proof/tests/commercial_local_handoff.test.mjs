import test from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import worker from "../commercial/landing.mjs";
const origin="https://proof.imagineqira.com";
const page=async(path="/",env={})=>await (await worker.fetch(new Request(origin+path),env)).text();
const scriptOf=html=>[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)?.[1];
function startUI(script,{href="https://buy.stripe.com/9B63cvexo0ts3OBfyv7kc07",query=""}={}){
 const store=new Map(),handlers={};
 const element=(tag="div")=>({
  tag,children:[],attrs:{},handlers:{},textContent:"",value:"",hidden:false,href:"",
  append(...items){this.children.push(...items);},
  replaceChildren(...items){this.children=[...items];},
  addEventListener(type,fn){this.handlers[type]=fn;},
  removeAttribute(name){delete this.attrs[name];},
  setAttribute(name,value){this.attrs[name]=value;},
  querySelector(){return null;},
  focus(){this.focused=true;}
 });
 const input=element("input"),target=element("div"),form=element("form"),price=element("a");
 price.href=href;
 const nodes={repoCheck:form,repoUrl:input,repoResult:target,buyLink:price};
 const document={getElementById:id=>nodes[id]||null,createElement:tag=>element(tag)};
 const sessionStorage={setItem:(key,value)=>store.set(key,value),getItem:key=>store.get(key)};
 vm.runInNewContext(script,{document,sessionStorage,URL,URLSearchParams,location:{search:query},fetch:()=>{throw Error("External fetch forbidden on local-first homepage")}});
 return {input,target,form,price,store};
}
const deepText=(node)=>[node.textContent||"",...(node.children||[]).flatMap(deepText)].join(" ");

test("one click shows an instant review-request summary and exact live Stripe link without network access",async()=>{
 const html=await page("/",{QIRA_PROOF_CHECKOUT_URL:"https://buy.stripe.com/9B63cvexo0ts3OBfyv7kc07"});
 const script=scriptOf(html);assert.ok(script);
 const ui=startUI(script);
 ui.input.value="https://github.com/TheArtOfSound/lolm";
 let prevented=false;
 ui.form.handlers.submit({preventDefault(){prevented=true}});
 assert.equal(prevented,true);
 assert.equal(ui.target.hidden,false);
 assert.match(deepText(ui.target),/Repository address ready/);
 assert.match(deepText(ui.target),/TheArtOfSound\/lolm/);
 assert.match(deepText(ui.target),/not confirmed this repository exists/);
 assert.match(deepText(ui.target),/Continue to Stripe — \$299/);
 assert.equal(ui.store.get("qira_proof_repo"),"TheArtOfSound/lolm");
 const actions=ui.target.children.find(x=>x.className==="ux-result-actions");
 assert.ok(actions);
 assert.equal(actions.children[0].href,"https://buy.stripe.com/9B63cvexo0ts3OBfyv7kc07");
});

test("invalid external links, credentials and query parameters are rejected locally without session storage",async()=>{
 const script=scriptOf(await page("/"));
 for(const value of ["https://evil.example/a/b","https://github.com/owner/repo?secret=1",
  "https://person:pass@github.com/owner/repo","http://github.com/owner/repo",
  "../repo","https://github.com/owner/repo/tree/main",".github/workflows"]){
  const ui=startUI(script);ui.input.value=value;
  ui.form.handlers.submit({preventDefault(){}});
  assert.match(deepText(ui.target),/Enter a GitHub repository address/,value);
  assert.equal(ui.input.attrs["aria-invalid"],"true");
  assert.equal(ui.store.has("qira_proof_repo"),false,value);
 }
});

test("valid private and public repository names are accepted without any existence claim",async()=>{
 const script=scriptOf(await page("/"));
 for(const value of ["github.com/owner/private-repo","Owner/private-repo","https://github.com/owner/private-repo"]){
  const ui=startUI(script);ui.input.value=value;ui.form.handlers.submit({preventDefault(){}});
  assert.match(deepText(ui.target),/We have not confirmed this repository exists/);
  assert.ok(ui.store.has("qira_proof_repo"));
  ui.input.handlers.input();
  assert.equal(ui.target.hidden,true);
 }
});

test("optional repo query starts the same local flow and metadata canonical never includes repo names",async()=>{
 const result=await worker.fetch(new Request(origin+"/?repo=TheArtOfSound%2Flolm"));
 const html=await result.text();
 assert.match(html,/rel="canonical" href="https:\/\/proof.imagineqira.com\/"/);
 assert.doesNotMatch(html.split("</head>")[0],/TheArtOfSound%2Flolm/);
 const ui=startUI(scriptOf(html),{query:"?repo=TheArtOfSound%2Flolm"});
 assert.equal(ui.input.value,"TheArtOfSound/lolm");
 assert.match(deepText(ui.target),/Repository address ready/);
});

test("intake reuses only the validated owner/repo from this browser tab, without requiring a backend",async()=>{
 const html=await page("/start-review");
 const script=scriptOf(html);assert.ok(script);
 const input={value:""},form={addEventListener(){}};
 const document={getElementById:id=>id==="intakeRepo"?input:id==="intakeComposer"?form:null};
 vm.runInNewContext(script,{document,window:{sessionStorage:{getItem:()=> "TheArtOfSound/lolm"},location:{assign(){}}}});
 assert.equal(input.value,"TheArtOfSound/lolm");
 const invalid={value:""};
 vm.runInNewContext(script,{document:{getElementById:id=>id==="intakeRepo"?invalid:id==="intakeComposer"?form:null},window:{sessionStorage:{getItem:()=> "ghp_really_secret/token"},location:{assign(){}}}});
 assert.equal(invalid.value,"");
});

test("mobile and privacy guards keep the local-first state understandable and contained",async()=>{
 const response=await worker.fetch(new Request(origin+"/"));
 const html=await response.text();
 assert.match(html,/id="repoResult" role="status" aria-live="polite"/);
 assert.match(html,/\.ux-entry button\{flex:1 1 100%/);
 assert.match(response.headers.get("content-security-policy"),/connect-src 'none';form-action 'none'/);
 assert.doesNotMatch(html,/\bfetch\s*\(/);
 const privacy=await page("/privacy");
 assert.match(privacy,/browser tab's session storage/);
 assert.match(privacy,/not transmitted to Qira by the entry field/);
});
