import test from "node:test";
import assert from "node:assert/strict";
import {CONTROL_INFO,maskToPolicy} from "./engine.mjs";
import {WORLDS,evaluateWorld,robustAnalysis} from "./robustness.mjs";

function independentWorldUtility(mask, world) {
  const p=maskToPolicy(mask);
  const outcome=evaluateWorld(p,world);
  return outcome.harm+4*outcome.friction+3*CONTROL_INFO.filter(c=>p[c.id]).length;
}

test("decision certificate is selection-independent and fully synthetic",()=>{
  const results=[0,7,18,31].map(mask=>robustAnalysis(maskToPolicy(mask)));
  for(const result of results){
    assert.equal(result.decisionCertificate.schema,"qira-event-horizon/decision-sensitivity-v1");
    assert.equal(result.decisionCertificate.leaveOneWorldOut.length,6);
    assert.match(result.decisionCertificate.limitation,/fictional/);
    assert.ok(["abstain_from_unique_policy_claim","stable_within_declared_synthetic_worlds_only"]
      .includes(result.decisionCertificate.status));
  }
  for(const result of results.slice(1)){
    assert.deepEqual(result.decisionCertificate,results[0].decisionCertificate);
  }
});

test("each omission exactly recomputes regret and ties from an independent enumeration",()=>{
  const result=robustAnalysis(maskToPolicy(31));
  const certificate=result.decisionCertificate;
  const policies=Array.from({length:32},(_,mask)=>({
    mask,
    utilities:WORLDS.map(w=>independentWorldUtility(mask,w))
  }));
  for(let omit=0;omit<WORLDS.length;omit++){
    const other=WORLDS.map((_,i)=>i).filter(i=>i!==omit);
    const ideals=other.map(i=>Math.min(...policies.map(p=>p.utilities[i])));
    const scores=policies.map(p=>({
      mask:p.mask,
      maxRegret:Math.max(...other.map((i,j)=>p.utilities[i]-ideals[j]))
    }));
    const minimum=Math.min(...scores.map(p=>p.maxRegret));
    const winners=scores.filter(p=>Math.abs(p.maxRegret-minimum)<1e-9).map(p=>p.mask);
    const record=certificate.leaveOneWorldOut[omit];
    assert.equal(record.omittedWorld,WORLDS[omit].id);
    assert.equal(record.retainedWorlds,WORLDS.length-1);
    assert.equal(record.minimumMaxRegret,Number(minimum.toFixed(6)));
    assert.deepEqual(record.optimalMasks,winners);
    assert.equal(record.fullSelectionStillOptimal,winners.includes(result.minimax.mask));
  }
});

test("ambiguous or unstable policy selections force a no-unique-claim status",()=>{
  const c=robustAnalysis({}).decisionCertificate;
  assert.deepEqual(c.disagreementWorlds,
    c.leaveOneWorldOut.filter(x=>!x.fullSelectionStillOptimal).map(x=>x.omittedWorld));
  const mustAbstain=c.multipleGlobalOptima||c.disagreementWorlds.length>0;
  assert.equal(c.status,mustAbstain?"abstain_from_unique_policy_claim":
    "stable_within_declared_synthetic_worlds_only");
  assert.ok(c.allWorldsOptimalMasks.length>=1);
});
