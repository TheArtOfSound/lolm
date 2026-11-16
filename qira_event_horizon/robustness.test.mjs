import test from "node:test";
import assert from "node:assert/strict";
import {CONTROL_INFO,compareAll,maskToPolicy} from "./engine.mjs";
import {WORLDS,evaluateWorld,robustAnalysis} from "./robustness.mjs";

test("six separate hypothesis worlds are declared",()=>{
 assert.equal(WORLDS.length,6);
 assert.equal(new Set(WORLDS.map(w=>w.id)).size,6);
 assert.equal(WORLDS[0].id,"nominal");
});
test("nominal world agrees exactly with original simulator",()=>{
 for(const mask of [0,1,4,11,31]){
  const p=maskToPolicy(mask);
  const expected=compareAll(p).summary;
  const result=evaluateWorld(p,WORLDS[0]);
  assert.equal(result.harm,expected.harm);
  assert.equal(result.friction,expected.friction);
  assert.equal(result.blocked,expected.legitimateBlocked);
 }
});
test("severe degradation cannot be treated as a better threat control",()=>{
 const all=maskToPolicy(31);
 const nominal=evaluateWorld(all,WORLDS[0]);
 const degraded=evaluateWorld(all,WORLDS.find(w=>w.id==="combined-degradation"));
 assert.ok(degraded.harm>=nominal.harm);
 assert.ok(nominal.harm>0,"insider residual risk remains");
});
test("minimax regret is exact over 32 control combinations",()=>{
 const r=robustAnalysis(maskToPolicy(31));
 assert.equal(r.controlCombinations,32);
 assert.equal(r.worlds.length,6);
 assert.equal(r.selected.worldOutcomes.length,6);
 const all=Array.from({length:32},(_,m)=>robustAnalysis(maskToPolicy(m)).selected.maxRegret);
 assert.equal(r.minimax.maxRegret,Math.min(...all));
 assert.ok(r.minimax.mask>=0&&r.minimax.mask<32);
});
test("exactly deterministic but does not claim real-world probabilities",()=>{
 const a=robustAnalysis({grant_review:true,mfa:true});
 assert.deepEqual(a,robustAnalysis({grant_review:true,mfa:true}));
 assert.match(a.validity,/not a calibrated/);
 assert.match(a.caution,/No zero-risk guarantee/);
});
