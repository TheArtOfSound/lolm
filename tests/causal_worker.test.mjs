import test from 'node:test';
import assert from 'node:assert/strict';
import worker from '../cloudflare/causal-observatory/worker.js';

async function call(path, input) {
  const init = input === undefined ? {} : {
    method: 'POST',
    headers: {'content-type': 'application/json'},
    body: JSON.stringify(input),
  };
  const response = await worker.fetch(new Request('https://example.invalid' + path,init));
  return {status: response.status, payload: await response.json()};
}

test('health identifies fixed fictional model and no storage',async()=>{
  const r=await call('/api/health');
  assert.equal(r.status,200);
  assert.equal(r.payload.dataset,'fixed-fictional-only');
  assert.equal(r.payload.neural_checkpoint,false);
  assert.equal(r.payload.storage,'none');
});

test('baseline results expose four assumed sensitive pathways',async()=>{
  const r=await call('/api/replay',{controls:[]});
  assert.equal(r.status,200);
  assert.equal(r.payload.experiment.robust_prevention,false);
  assert.equal(r.payload.experiment.prevented_variants.length,0);
  assert.equal(Object.keys(r.payload.experiment.counterfactual).length,4);
  assert.equal(r.payload.receipts_verified,true);
  assert.equal(r.payload.model_generated,false);
});

test('one assumed defense is robust over all modeled variants',async()=>{
  const r=await call('/api/replay',{controls:['least_privilege']});
  assert.equal(r.status,200);
  assert.equal(r.payload.experiment.robust_prevention,true);
  assert.equal(r.payload.experiment.prevented_variants.length,4);
});

test('single assumption can fail against a bypass variant',async()=>{
  const r=await call('/api/replay',{controls:['step_up_auth']});
  assert.equal(r.payload.experiment.counterfactual.primary.adverse_outcome,false);
  assert.equal(r.payload.experiment.counterfactual.token_fallback.adverse_outcome,true);
  assert.equal(r.payload.experiment.counterfactual.combined.adverse_outcome,true);
});

test('frontier solutions are robust and Pareto undominated',async()=>{
  const r=await call('/api/replay',{controls:[]});
  const frontier=r.payload.frontier;
  assert.ok(frontier.length>0);
  for(const candidate of frontier){
    assert.equal((await call('/api/replay',{controls:candidate.controls})).payload.experiment.robust_prevention,true);
    assert.ok(!frontier.some(x=>x.cost<candidate.cost && x.count<=candidate.count));
  }
});

test('invalid controls and extra payload fields are rejected',async()=>{
  for(const p of [
    {controls:['not_a_real_control']},
    {controls:['step_up_auth','step_up_auth']},
    {controls:[],log:'production-secret'},
    {controls:'step_up_auth'},
    {controls:[true]},
  ]){
    const r=await call('/api/replay',p);
    assert.equal(r.status,400);
  }
});

test('result is reproducible for exactly identical declared interventions',async()=>{
  const a=(await call('/api/replay',{controls:['least_privilege','step_up_auth']})).payload;
  const b=(await call('/api/replay',{controls:['step_up_auth','least_privilege']})).payload;
  assert.deepEqual(a,b);
});

test('HTML has real controls and no non-research data input',async()=>{
  const response=await worker.fetch(new Request('https://example.invalid/'));
  assert.equal(response.status,200);
  const html=await response.text();
  assert.match(html,/Causal Observatory/);
  assert.match(html,/id="controls"/);
  assert.match(html,/id="download"/);
  assert.match(response.headers.get('content-security-policy'),/frame-ancestors 'none'/);
});
