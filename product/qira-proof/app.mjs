import {SCHEMA,normalizeSnapshot,analyzeSnapshot,compareSnapshots,proof,verifyProof}
from "./core.mjs";

const DEMO_DATE="2026-11-15T19:00:00Z";
const DEMO={
 schema:SCHEMA,captured_at:DEMO_DATE,
 facts:[
  {provider:"github",asset:"fictional-org/operations-demo",signal:"runtime_ssh_keyscan",value:true,
   source_url:"https://example.org/fictional-workflow",observed_at:DEMO_DATE},
  {provider:"github",asset:"fictional-org/operations-demo",signal:"ssh_host_key_pinned",value:"unknown",
   source_url:"https://example.org/fictional-workflow",observed_at:DEMO_DATE},
  {provider:"github",asset:"fictional-org/operations-demo",signal:"repo_branch_protection_verifiable",value:"unknown",
   source_url:"https://example.org/fictional-rules",observed_at:DEMO_DATE},
  {provider:"cloudflare",asset:"fictional-worker",signal:"worker_preview_enabled",value:true,
   source_url:"https://example.org/fictional-worker",observed_at:DEMO_DATE},
  {provider:"cloudflare",asset:"fictional-worker",signal:"worker_public_enabled",value:true,
   source_url:"https://example.org/fictional-worker",observed_at:DEMO_DATE},
  {provider:"cloudflare",asset:"fictional-worker",signal:"worker_privileged_bindings",value:true,
   source_url:"https://example.org/fictional-worker",observed_at:DEMO_DATE},
 ]
};
function sampleAfter(){
 const date="2026-11-16T19:00:00Z";
 return {schema:SCHEMA,captured_at:date,facts:DEMO.facts.map(f=>{
  const changed=f.signal==="worker_preview_enabled"?false:
   f.signal==="ssh_host_key_pinned"||f.signal==="repo_branch_protection_verifiable"?true:f.value;
  return {...f,value:changed,observed_at:date};
 })};
}
const state={before:normalizeSnapshot(DEMO),after:null,mode:"demo",tab:"assessment",last:null};
const el=id=>document.getElementById(id);
const clear=e=>e.replaceChildren();
function node(tag,cls,value){const d=document.createElement(tag);if(cls)d.className=cls;if(value!==undefined)d.textContent=value;return d}
function status(message,isError=false){el("status").textContent=message;el("status").style.color=isError?"#f2b1aa":""}
function buttonTab(tab){
 state.tab=tab;
 document.querySelectorAll("[data-tab]").forEach(b=>{
  const on=b.dataset.tab===tab;b.classList.toggle("active",on);b.setAttribute("aria-selected",String(on));
 });
 document.querySelectorAll(".tabcontent").forEach(p=>p.hidden=p.id!==tab);
 el("workTitle").textContent={assessment:"Assessment",recheck:"Configuration recheck",evidence:"Evidence export & verification"}[tab];
}
function render(){
 const report=analyzeSnapshot(state.before);
 el("assetsCount").textContent=report.assets;
 el("reviewCount").textContent=report.counts.review+report.counts.high;
 el("unknownCount").textContent=report.counts.unknown;
 el("factsCount").textContent=report.facts;
 el("baselineState").textContent=state.mode==="demo"?"Sample":"Loaded";
 el("baselineName").textContent=state.mode==="demo"?"Fictional demo · "+report.facts+" facts":
  "Private local snapshot · "+report.facts+" facts · "+state.before.captured_at;
 el("followupState").textContent=state.after?"Loaded":"Empty";
 el("followupName").textContent=state.after?"Follow-up · "+state.after.captured_at:"No later snapshot selected";
 const findings=el("findings");clear(findings);
 if(!report.findings.length){findings.appendChild(node("div","empty","No configured rule matched these facts. This is not a clean bill of health."));}
 report.findings.forEach((x,index)=>{
  const card=node("article","finding");
  const head=node("div","finding-head"),label=node("div"),title=node("div","finding-title",x.title);
  label.appendChild(title);label.appendChild(node("div","finding-meta",
   x.provider.toUpperCase()+" / "+x.asset+" · "+x.category+" · "+x.confidence));
  head.appendChild(label);head.appendChild(node("span","severity "+x.level,x.level==="unknown"?"Unverified":x.level==="review"?"Review":"Elevated"));
  card.appendChild(head);
  const body=node("div","finding-body");
  body.appendChild(node("p","",x.interpretation));
  body.appendChild(node("div","section-label","Recommended verification"));
  body.appendChild(node("p","",x.next));
  body.appendChild(node("div","section-label","Observed evidence"));
  const evidence=node("div","evidence");
  x.evidence.forEach(f=>{
   if(state.mode==="demo"){evidence.appendChild(node("span","chip","Fictional · "+f.signal+" = "+String(f.observed_value)));return;}
   const a=node("a","",f.signal+" = "+String(f.observed_value));
   a.href=f.source_url;a.target="_blank";a.rel="noopener noreferrer";
   a.title="Open declared provider evidence: "+f.source_url;
   evidence.appendChild(a);
  });
  body.appendChild(evidence);card.appendChild(body);findings.appendChild(card);
 });
 const deltaBox=el("deltas");clear(deltaBox);
 if(!state.after){
  const empty=node("div","empty");
  empty.appendChild(node("strong","","No follow-up snapshot yet"));
  empty.appendChild(node("div","","Import a second local JSON file or choose Sample recheck. No active infrastructure modification happens here."));
  deltaBox.appendChild(empty);
 }else{
  const comparison=compareSnapshots(state.before,state.after);
  comparison.deltas.forEach(x=>{
   const d=node("div","delta");d.appendChild(node("b","",x.title));
   d.appendChild(node("span","label",x.state.replaceAll("-"," ").toUpperCase()));
   d.appendChild(node("span","",": "+x.explanation));deltaBox.appendChild(d);
  });
  if(!comparison.deltas.length)deltaBox.appendChild(node("div","empty","No previous review conditions to compare."));
  deltaBox.appendChild(node("div","note",comparison.conclusion));
 }
 status(state.mode==="demo"?"DEMONSTRATION: fictional source data. Import authorized evidence to run a real configuration review.":
 state.mode==="connected"?"GITHUB APP: selected read-only metadata was retrieved transiently through this Worker's server. Analysis occurs in your browser; source origin is not independently attested.":
 "PRIVATE LOCAL ANALYSIS: imported files remain in this browser. Source identity and authorization are not cryptographically attested.");
}
async function readSnapshot(file){
 if(!file||file.size>512_000)throw Error("Choose a JSON snapshot smaller than 500 KB");
 const input=JSON.parse(await file.text());
 return normalizeSnapshot(input);
}
el("baselineInput").addEventListener("change",async e=>{
 const file=e.target.files?.[0];
 if(!file)return;
 try{state.before=await readSnapshot(file);state.after=null;state.mode="private";render();buttonTab("assessment");}
 catch(error){status("Baseline was rejected: "+error.message,true)}
 e.target.value="";
});
el("followupInput").addEventListener("change",async e=>{
 const file=e.target.files?.[0];if(!file)return;
 try{
  if(state.mode==="demo")throw Error("Load a real baseline before comparing a real follow-up");
  state.after=await readSnapshot(file);render();buttonTab("recheck");
 }catch(error){status("Follow-up rejected: "+error.message,true)}
 e.target.value="";
});
el("demoButton").addEventListener("click",()=>{state.before=normalizeSnapshot(DEMO);state.after=null;state.mode="demo";render();buttonTab("assessment")});
el("demoRecheck").addEventListener("click",()=>{
 if(state.mode!=="demo"){status("Reset to the fictional demo to load its sample follow-up",true);return}
 state.after=normalizeSnapshot(sampleAfter());render();buttonTab("recheck");
});
el("clearFollowup").addEventListener("click",()=>{state.after=null;render();buttonTab("assessment")});
document.querySelectorAll("[data-tab]").forEach(b=>b.addEventListener("click",()=>buttonTab(b.dataset.tab)));
function downloadJson(data,filename){
 const blob=new Blob([JSON.stringify(data,null,2)],{type:"application/json"});
 const url=URL.createObjectURL(blob),a=document.createElement("a");
 a.href=url;a.download=filename;a.click();
 setTimeout(()=>URL.revokeObjectURL(url),1000);
}
el("exportButton").addEventListener("click",async()=>{
 try{
  const artifact=await proof(state.before,state.after);
  state.last=artifact;
  el("digestValue").textContent=artifact.sha256;
  el("verificationState").textContent="Locally generated. Hash is not a digital signature or provider authentication.";
  downloadJson(artifact,"qira-proof-evidence.json");
 }catch(error){el("verificationState").textContent="Unable to generate evidence: "+error.message;}
});
el("verifyButton").addEventListener("click",()=>el("verifyInput").click());
el("verifyInput").addEventListener("change",async event=>{
 const f=event.target.files?.[0];if(!f)return;
 try{
  if(f.size>1_000_000)throw Error("Evidence exceeds 1 MB");
  const artifact=JSON.parse(await f.text());
  const okay=await verifyProof(artifact);
  el("verificationState").textContent=okay?
   "PASS: document, source facts, findings, and digest match a fresh local deterministic calculation. Provider origin is not verified.":
   "FAIL: evidence does not match the deterministic proof calculation, or its fields were altered.";
  el("digestValue").textContent=okay?artifact.sha256:"Verification failed";
  buttonTab("evidence");
 }catch(error){el("verificationState").textContent="Evidence rejected: "+error.message}
 event.target.value="";
});

const git={connected:false,csrf:null};
function gitMessage(value,isError=false){
 const out=el("gitMessage");out.textContent=value;out.style.color=isError?"#f2b1aa":"";
}
async function githubApi(path,options={}){
 const response=await fetch(path,{credentials:"same-origin",cache:"no-store",...options});
 if(!response.ok)throw Error(response.status===401?"GitHub connection expired. Connect again.":
  response.status===403?"Your GitHub App authorization does not permit this resource.":
  "GitHub read-only metadata could not be retrieved (HTTP "+response.status+").");
 return response.json();
}
function selectOptions(id,items,label,value,placeholder){
 const control=el(id);
 control.replaceChildren();
 control.appendChild(new Option(placeholder,""));
 for(const item of items)control.appendChild(new Option(label(item),value(item)));
 control.disabled=items.length===0;
 control.value="";
}
async function loadGithubInstallations(){
 const payload=await githubApi("/api/github/installations");
 selectOptions("gitInstallation",payload.items,x=>x.account+" · "+x.selection,x=>String(x.id),"Choose installation");
 selectOptions("gitRepository",[],x=>x.name,x=>x.name,"Choose repository");
 selectOptions("gitWorkflow",[],x=>x.path,x=>x.path,"Choose workflow");
 el("gitAssess").disabled=true;
 gitMessage(payload.items.length?"Choose an installation, then a repository and workflow.":
 "No authorized installations found. Install the read-only GitHub App, then reconnect.");
 if(payload.truncated)gitMessage("More than 50 installations found; this pilot lists the first 50.");
}
async function githubConnectionStatus(){
 try{
  const current=await githubApi("/api/github/status");
  git.connected=current.connected;
  git.csrf=current.csrf;
  el("gitConnect").hidden=!current.configured||current.connected;
  el("gitDisconnect").hidden=!current.connected;
  el("gitInstall").hidden=!current.install_url;
  if(current.install_url)el("gitInstall").href=current.install_url;
  el("gitPicker").hidden=!current.connected;
  el("gitBadge").textContent=!current.configured?"Pending setup":current.connected?"Connected":"Ready";
  el("gitStatus").textContent=!current.configured?
   "GitHub App registration and secure credentials are not configured yet. Manual JSON analysis remains available.":
   current.connected?"Authorized GitHub connection. Temporary session; selected metadata is processed without server storage.":
   "Authorize our read-only GitHub App to select a repository and its workflow.";
  if(current.connected)await loadGithubInstallations();
 }catch(error){
  el("gitBadge").textContent="Unavailable";
  el("gitStatus").textContent="Could not check GitHub connection availability.";
  gitMessage(error.message,true);
 }
}
el("gitInstallation").addEventListener("change",async event=>{
 const id=event.target.value;
 selectOptions("gitRepository",[],x=>x.name,x=>x.name,"Choose repository");
 selectOptions("gitWorkflow",[],x=>x.path,x=>x.path,"Choose workflow");
 el("gitAssess").disabled=true;
 if(!id)return;
 gitMessage("Loading authorized repositories…");
 try{
  const result=await githubApi("/api/github/repos?installation_id="+encodeURIComponent(id));
  selectOptions("gitRepository",result.repos,x=>x.name,x=>x.name,"Choose repository");
  gitMessage(result.truncated?"Only the first 100 repositories are listed in this pilot.":
   "Select a repository to load authorized workflows.");
 }catch(error){gitMessage(error.message,true)}
});
el("gitRepository").addEventListener("change",async event=>{
 const id=el("gitInstallation").value,repo=event.target.value;
 selectOptions("gitWorkflow",[],x=>x.path,x=>x.path,"Choose workflow");
 el("gitAssess").disabled=true;
 if(!id||!repo)return;
 gitMessage("Loading authorized workflow names…");
 try{
  const result=await githubApi("/api/github/workflows?installation_id="+encodeURIComponent(id)+
   "&repo="+encodeURIComponent(repo));
  selectOptions("gitWorkflow",result.workflows,x=>x.path,x=>x.path,"Choose workflow");
  gitMessage(result.workflows.length?"Choose a workflow and run the read-only assessment.":
   "No supported workflow files were accessible.");
 }catch(error){gitMessage(error.message,true)}
});
el("gitWorkflow").addEventListener("change",event=>{
 el("gitAssess").disabled=!event.target.value;
});
el("gitAssess").addEventListener("click",async()=>{
 const id=el("gitInstallation").value,repo=el("gitRepository").value,workflow=el("gitWorkflow").value;
 if(!id||!repo||!workflow)return;
 el("gitAssess").disabled=true;gitMessage("Retrieving authorized configuration evidence…");
 try{
  const data=await githubApi("/api/github/assessment?installation_id="+encodeURIComponent(id)+
   "&repo="+encodeURIComponent(repo)+"&workflow="+encodeURIComponent(workflow));
  state.before=normalizeSnapshot(data.snapshot);
  state.after=null;state.mode="connected";
  render();buttonTab("assessment");
  gitMessage("Read-only GitHub assessment loaded. No provider credentials were returned to this page.");
 }catch(error){gitMessage(error.message,true)}
 finally{el("gitAssess").disabled=false}
});
el("gitDisconnect").addEventListener("click",async()=>{
 if(!git.csrf)return;
 try{
  await githubApi("/api/github/disconnect",{method:"POST",headers:{"content-type":"application/json","x-qira-csrf":git.csrf},body:"{}"});
  state.before=normalizeSnapshot(DEMO);state.after=null;state.mode="demo";
  render();buttonTab("assessment");gitMessage("Local session cleared. GitHub authorization must be revoked separately in GitHub if desired.");
  await githubConnectionStatus();
 }catch(error){gitMessage(error.message,true)}
});
const githubResult=new URL(location.href).searchParams.get("github");
if(githubResult==="failed")gitMessage("GitHub authorization could not be completed. Check App permissions and try again.",true);
if(githubResult){const cleaned=new URL(location.href);cleaned.searchParams.delete("github");history.replaceState(null,"",cleaned.pathname+cleaned.search+cleaned.hash);}
render();buttonTab("assessment");document.body.dataset.qiraBoot="ready";githubConnectionStatus();
