import test from "node:test";
import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import worker from "./worker.mjs";
import {CONTROL_INFO,SCENARIOS,simulate,compareAll,pareto,minimalInterventions,evaluate,normalizePolicy} from "./engine.mjs";

globalThis.crypto ??= webcrypto;
const origin="https://event-horizon.example.invalid";
async function post(body,headers={"Content-Type":"application/json"}){
 return worker.fetch(new Request(origin+"/api/evaluate",{method:"POST",headers,body:JSON.stringify(body)}));
}
test("synthetic graph / nine disjoint scenarios",()=>{
 assert.equal(SCENARIOS.length,9);
 assert.equal(SCENARIOS.filter(x=>x.category==="malicious").length,5);
 assert.equal(SCENARIOS.filter(x=>x.category==="benign").length,4);
 assert.deepEqual(new Set(SCENARIOS.map(x=>x.id)).size,9);
 assert.equal(CONTROL_INFO.length,5);
});
test("counterfactuals, legitimate friction and impossibility counterexample",()=>{
 const base=compareAll({}),max=compareAll(Object.fromEntries(CONTROL_INFO.map(c=>[c.id,true])));
 assert.equal(base.summary.harm,575);
 assert.ok(max.summary.harm>0,"honest residual malicious insider loss must remain");
 assert.ok(max.summary.harm<base.summary.harm);
 assert.ok(max.summary.friction>base.summary.friction);
 assert.ok(max.summary.legitimateBlocked>0);
 assert.equal(simulate(SCENARIOS.find(x=>x.id==="credential-cascade"),{mfa:true}).harm,0);
 assert.equal(simulate(SCENARIOS.find(x=>x.id==="partner-replay"),{bound_tokens:true}).harm,0);
 assert.deepEqual(minimalInterventions(SCENARIOS.find(x=>x.id==="insider-override")),[]);
});
test("frontier is nondominated in harm/friction/complexity and is stable",()=>{
 const {all,frontier}=pareto();
 assert.equal(all.length,32); assert.ok(frontier.length>1);
 assert.equal(JSON.stringify(pareto()),JSON.stringify({all,frontier}));
 for(const p of frontier){
  assert.ok(!all.some(q=>q.mask!==p.mask&&q.harm<=p.harm&&q.friction<=p.friction&&q.complexity<=p.complexity
    &&(q.harm<p.harm||q.friction<p.friction||q.complexity<p.complexity)),"frontier dominated");
 }
});
test("human-approved insider misuse cannot be magically fixed",()=>{
 const s=SCENARIOS.find(x=>x.id==="insider-override");
 for(let m=0;m<32;m++){const p=Object.fromEntries(CONTROL_INFO.map((c,i)=>[c.id,Boolean(m&(1<<i))]));
 assert.ok(simulate(s,p).harm>=115,"insider is a deliberately undefeatable counterexample");}
});
test("malformed requests fail closed",async()=>{
 for(const body of [
  {scenarioId:"credential-cascade",policy:{mfa:"yes"}},
  {scenarioId:"arbitrary-live-target",policy:{}},
  {scenarioId:"credential-cascade",policy:{arbitraryCommand:true}},
  {scenarioId:"credential-cascade",policy:{},url:"https://example.com"}
 ]){
  const res=await post(body);assert.equal(res.status,400);
 }
 const type=await post({scenarioId:"credential-cascade",policy:{}},{"Content-Type":"text/plain"});
 assert.equal(type.status,415);
 const huge=await post({scenarioId:"credential-cascade",policy:{},unused:"x".repeat(5000)});
 assert.equal(huge.status,413);
});
test("worker public API returns reality-labeled data and verifiable integrity digest",async()=>{
 const meta=await worker.fetch(new Request(origin+"/api/meta"));
 assert.equal(meta.status,200);
 const m=await meta.json();assert.equal(m.scenarios.length,9);
 const res=await post({scenarioId:"credential-cascade",policy:{mfa:true}});
 assert.equal(res.status,200);
 const value=await res.json();
 assert.equal(value.selected.current.harm,0);
 assert.equal(value.schema,"qira-event-horizon/synthetic-v1");
 assert.match(value.disclaimer,/Synthetic/);
 const {receipt,...payload}=value;
 const buffer=await webcrypto.subtle.digest("SHA-256",new TextEncoder().encode(JSON.stringify(payload)));
 const computed=Buffer.from(buffer).toString("hex");
 assert.equal(computed,receipt.digest);
 assert.equal(receipt.algorithm,"SHA-256");
 assert.equal(value.robustness.worlds.length,6);
 assert.equal(value.robustness.controlCombinations,32);
 assert.equal(value.robustness.schema,"qira-event-horizon/assumption-robustness-v1");
});
test("Worker serves standalone responsive UI under CSP",async()=>{
 const res=await worker.fetch(new Request(origin+"/"));
 assert.equal(res.status,200);
 assert.match(res.headers.get("Content-Security-Policy"),/frame-ancestors 'none'/);
 assert.match(res.headers.get("Content-Security-Policy"),/nonce-/);
 const html=await res.text();
 assert.match(html,/What actually/);
 assert.match(html,/FICTIONAL DATA ONLY/);
 assert.match(html,/id="scenario"/);
 assert.match(html,/id="verify"/);
 assert.match(html,/id="robustness"/);
 assert.match(html,/id="apply-robust"/);
 assert.doesNotMatch(html,/__NONCE__/);
});
test("methods restricted and no state mutation endpoint",async()=>{
 assert.equal((await worker.fetch(new Request(origin+"/api/evaluate"))).status,404);
 assert.equal((await worker.fetch(new Request(origin+"/not-a-page"))).status,404);
 const h=await worker.fetch(new Request(origin+"/health"));assert.equal((await h.json()).persistence,false);
});
test("evaluation determinism and no hidden side effects",()=>{
 const a=evaluate({grant_review:true},"admin-maintenance"),b=evaluate({grant_review:true},"admin-maintenance");
 assert.deepEqual(a,b);
 assert.equal(Object.keys(a.summary).includes("real-world"),false);
 assert.throws(()=>normalizePolicy({mfa:"true"}));
 assert.throws(()=>normalizePolicy({token_exfiltration:true}));
});
