import test from "node:test";
import assert from "node:assert/strict";

class Element{
 constructor(tag="div"){this.tagName=tag;this.children=[];this.textContent="";this.hidden=false;this.disabled=false;this.style={};this.dataset={};this.value="";this.events={};this.className="";this.classList={toggle:()=>{}}}
 appendChild(child){this.children.push(child);return child}
 replaceChildren(...children){this.children=children}
 addEventListener(name,fn){this.events[name]=fn}
 setAttribute(k,v){this[k]=String(v)}
 click(){return this.events.click?.()}
}
const sleep=()=>new Promise(r=>setImmediate(r));
test("connected visitor can select an installation, repo and workflow, and see real-labeled findings",async()=>{
 const elements=new Map(),calls=[],downloads=[];
 let connected=true;
 const originalBlobUrl=URL.createObjectURL,originalRevoke=URL.revokeObjectURL;
 URL.createObjectURL=blob=>{downloads.push(blob);return "blob:qira-test-report-"+downloads.length};
 URL.revokeObjectURL=()=>{};
 const el=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id)};
 globalThis.document={
  body:new Element("body"),getElementById:el,
  createElement:tag=>new Element(tag),
  querySelectorAll:()=>[]
 };
 globalThis.Option=class Option{constructor(label,value){this.label=label;this.value=value}};
 globalThis.location={href:"https://qira.example/"};
 globalThis.history={replaceState:()=>{}};
 globalThis.fetch=async(url,opts={})=>{
  calls.push({url:String(url),method:opts.method||"GET",body:opts.body||"",csrf:opts.headers?.["x-qira-csrf"]});
  let response;
  if(url==="/api/github/status")response={configured:true,connected,csrf:connected?"test-csrf":null,install_url:"https://github.com/apps/qira-proof-research/installations/new"};
  else if(url==="/api/github/disconnect"){connected=false;response={disconnected:true,server_side_token_revoked:false};}
  else if(url==="/api/github/installations")response={items:[{id:123,account:"Sample owner",selection:"selected"}],truncated:false};
  else if(url==="/api/github/repos")response={repos:[{name:"sample-owner/test-repo",branch:"main"}],truncated:false};
  else if(url==="/api/github/workflows")response={workflows:[{path:".github/workflows/deploy.yml"}],truncated:false};
  else if(url==="/api/github/assessment"&&JSON.parse(opts.body||"{}").workflow==="__all__")response={
   snapshot:{schema:"qira-proof/snapshot-v1",captured_at:"2026-11-15T19:00:00Z",facts:[
    {provider:"github",asset:"sample-owner/test-repo:.github/workflows/deploy.yml",signal:"workflow_unpinned_actions",value:true,source_url:"https://github.com/sample-owner/test-repo/blob/0123456789abcdef0123456789abcdef01234567/.github/workflows/deploy.yml",observed_at:"2026-11-15T19:00:00Z"},
    {provider:"github",asset:"sample-owner/test-repo",signal:"repo_branch_protection_verifiable",value:"unknown",source_url:"https://github.com/sample-owner/test-repo/settings/branches",observed_at:"2026-11-15T19:00:00Z"}
   ]},coverage:{mode:"bounded-repository-workflows",repository:"sample-owner/test-repo",discovered:1,selected:1,assessed:1,skipped:0,limit:20,complete:true,truncated:false,commit:"0123456789abcdef0123456789abcdef01234567"}};
  else if(url==="/api/github/assessment")response={snapshot:{schema:"qira-proof/snapshot-v1",captured_at:"2026-11-15T19:00:00Z",facts:[
   {provider:"github",asset:"sample-owner/test-repo",signal:"runtime_ssh_keyscan",value:true,source_url:"https://github.com/sample-owner/test-repo/blob/main/.github/workflows/deploy.yml",observed_at:"2026-11-15T19:00:00Z"},
   {provider:"github",asset:"sample-owner/test-repo",signal:"ssh_host_key_pinned",value:"unknown",source_url:"https://github.com/sample-owner/test-repo/blob/main/.github/workflows/deploy.yml",observed_at:"2026-11-15T19:00:00Z"}
  ]}};
  else throw Error("Unexpected endpoint: "+url);
  return new Response(JSON.stringify(response),{status:200,headers:{"content-type":"application/json"}});
 };
 await import("../app.mjs?ui-connected=2026-11-15");
 await sleep();await sleep();
 assert.equal(document.body.dataset.qiraBoot,"ready");
 assert.equal(document.body.dataset.githubConnection,"connected");
 assert.equal(el("gitPicker").hidden,false);
 assert.equal(el("startCard").hidden,true);
 assert.equal(el("gitConnect").hidden,true);
 assert.equal(el("sampleBanner").hidden,true);
 assert.equal(el("reportIntro").hidden,false);
 el("gitInstallation").value="123";
 await el("gitInstallation").events.change({target:{value:"123"}});
 assert.equal(el("gitRepository").disabled,false);
 el("gitRepository").value="sample-owner/test-repo";
 await el("gitRepository").events.change({target:{value:"sample-owner/test-repo"}});
 assert.equal(el("gitWorkflow").disabled,false);
 assert.equal(el("gitScanAll").disabled,false);
 assert.match(el("gitScanAll").textContent,/Review 1 repository workflows/);
 el("gitWorkflow").value=".github/workflows/deploy.yml";
 el("gitWorkflow").events.change({target:{value:".github/workflows/deploy.yml"}});
 assert.equal(el("gitAssess").disabled,false);
 await el("gitAssess").events.click();
 assert.equal(document.body.dataset.reportType,"customer");
 assert.match(el("baselineName").textContent,/Connected GitHub workflow/);
 assert.equal(el("sampleBanner").hidden,true);
 assert.equal(el("assetsCount").textContent,1);
 assert.equal(el("reviewCount").textContent,1);
 assert.equal(el("observationsCount").textContent,1);
 assert.match(el("gitMessage").textContent,/Assessment ready/);
 assert.equal(el("findings").children[0].tagName,"details");
 assert.equal(el("findings").children[0].open,true);
 assert.equal(el("humanReportButton").disabled,false);
 await el("humanReportButton").events.click();
 assert.equal(downloads.length,1);
 const printable=await downloads[0].text();
 assert.match(printable,/Infrastructure configuration assessment/);
 assert.match(printable,/Deployment SSH trust requires verification/);
 assert.doesNotMatch(printable,/FICTIONAL EXAMPLE/);
 assert.match(el("verificationState").textContent,/Printable assessment downloaded/);
 await el("exportButton").events.click();
 assert.equal(downloads.length,2);
 const receipt=JSON.parse(await downloads[1].text());
 assert.equal(receipt.schema,"qira-proof/evidence-v1");
 assert.match(receipt.sha256,/^[a-f0-9]{64}$/);
 await el("gitScanAll").events.click();
 assert.equal(el("scanCoverage").hidden,false);
 assert.match(el("scanCoverage").textContent,/1 of 1 discovered workflows assessed/);
 assert.match(el("baselineName").textContent,/Connected GitHub workflow/);
 assert.match(el("gitMessage").textContent,/Reviewed all 1 discovered workflows/);
 assert.equal(el("reviewCount").textContent,1);
 assert.equal(el("observationsCount").textContent,1);
 assert.equal(el("unknownCount").textContent,1);
 assert.equal(document.body.dataset.reportType,"customer");
 assert.equal(el("gitScanAll").disabled,false);
 await el("gitDisconnect").events.click();
 assert.equal(document.body.dataset.githubConnection,"ready");
 assert.equal(document.body.dataset.reportType,"unstarted");
 assert.equal(el("gitPicker").hidden,true);
 assert.equal(el("humanReportButton").disabled,true);
 assert.match(el("gitMessage").textContent,/Local session cleared/);
 URL.createObjectURL=originalBlobUrl;
 URL.revokeObjectURL=originalRevoke;
 for(const call of calls.filter(x=>x.method==="POST")){
  assert.ok(call.url.startsWith("/api/github/"));
  assert.ok(!call.url.includes("sample-owner"),"source identifier must be in body not URL");
  assert.equal(call.csrf,"test-csrf");
 }
});
