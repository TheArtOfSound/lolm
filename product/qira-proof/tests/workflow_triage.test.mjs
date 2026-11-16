import test from "node:test";
import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import {SCHEMA,workflowTriage,proof,verifyProof} from "../core.mjs";
import {renderHumanReport} from "../report.mjs";
if(!globalThis.crypto)globalThis.crypto=webcrypto;
const commit="0123456789abcdef0123456789abcdef01234567",repo="org/repo",time="2026-11-16T07:12:48Z";
function make(){
 const facts=[{provider:"github",asset:repo,signal:"repo_branch_protection_verifiable",value:"unknown",
  source_url:"https://github.com/"+repo+"/settings/branches",observed_at:time}];
 const configurations={
  "all.yml":[true,true,true],
  "write-action.yml":[true,true,false],
  "ssh-action.yml":[false,true,true],
  "mutable.yml":[false,true,false],
  "none.yml":[false,false,false],
  "unverified.yml":["unknown",false,"unknown"]
 };
 for(const [name,[write,mutable,ssh]] of Object.entries(configurations)){
  const asset=repo+":.github/workflows/"+name,link="https://github.com/"+repo+"/blob/"+commit+"/.github/workflows/"+name;
  for(const [signal,value] of [["workflow_token_write_permission",write],
   ["workflow_unpinned_actions",mutable],["runtime_ssh_keyscan",ssh]]){
   facts.push({provider:"github",asset,signal,value,source_url:link,observed_at:time});
  }
 }
 return {schema:SCHEMA,captured_at:time,facts,
  coverage:{mode:"bounded-repository-workflows",repository:repo,discovered:6,selected:6,assessed:6,skipped:0,limit:20,complete:true,truncated:false,commit}};
}
test("triage partitions workflows by observed overlap without inventing severity scores",()=>{
 const groups=workflowTriage(make());
 assert.equal(groups.reduce((sum,g)=>sum+g.workflows.length,0),6);
 assert.deepEqual(groups.map(g=>g.indicator_count),[3,2,2,1,0,0]);
 assert.equal(groups[0].workflows[0].workflow,"all.yml");
 assert.equal(groups[0].workflows[0].unknown_count,0);
 assert.ok(groups.some(g=>g.category==="incomplete"&&g.workflows[0].workflow==="unverified.yml"));
 assert.ok(groups.some(g=>g.category==="none"&&g.workflows[0].workflow==="none.yml"));
 assert.ok(groups.every(g=>g.workflows.every(x=>x.source_url.startsWith("https://github.com/org/repo/blob/"+commit))));
});
test("printable export includes grouping, exact links and no vulnerability certification",async()=>{
 const input=make();
 const receipt=await proof(input);
 assert.equal(await verifyProof(receipt),true);
 const html=await renderHumanReport(receipt);
 assert.match(html,/Workflow review order/);
 assert.match(html,/all\.yml/);
 assert.match(html,/incomplete evidence/);
 assert.match(html,/not a severity score/);
 assert.match(html,/not establish greater exploitability/);
});
test("triage does not invent coverage for a local single-file snapshot",()=>{
 const input=make();delete input.coverage;
 assert.deepEqual(workflowTriage(input),[]);
});
