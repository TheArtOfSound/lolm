import test from "node:test";
import assert from "node:assert/strict";
import worker from "./worker.mjs";

const endpoint="https://horizon.imagineqira.com/mcp";
function rpc(id,method,params={},options={}){
 const request={jsonrpc:"2.0",id,method,params};
 const headers={"Content-Type":"application/json","Accept":"application/json, text/event-stream",
                "MCP-Protocol-Version":"2026-07-28","Mcp-Method":method,...options.headers};
 if(method==="tools/call")headers["Mcp-Name"]=params.name;
 return worker.fetch(new Request(endpoint,{method:"POST",headers,body:JSON.stringify(request)}));
}
test("2026 MCP initializes with stateless, read-only tools",async()=>{
 const response=await rpc(1,"initialize",{protocolVersion:"2026-07-28",capabilities:{},clientInfo:{name:"lab",version:"1"}});
 assert.equal(response.status,200);
 const x=await response.json();
 assert.equal(x.result.protocolVersion,"2026-07-28");
 assert.equal(x.result.serverInfo.name,"qira-event-horizon");
 const list=await (await rpc(2,"tools/list")).json();
 assert.equal(list.result.resultType,"complete");
 assert.equal(list.result.tools.length,3);
 assert.ok(list.result.tools.every(tool=>tool.annotations.readOnlyHint===true && tool.annotations.destructiveHint===false));
});
test("safe tool returns fixed synthetic scenario, no remote target",async()=>{
 const response=await rpc(3,"tools/call",{name:"horizon.evaluate_policy",arguments:{scenarioId:"credential-cascade",policy:{mfa:true}}});
 assert.equal(response.status,200);
 const data=await response.json();
 assert.equal(data.result.resultType,"complete");
 const payload=JSON.parse(data.result.content[0].text);
 assert.equal(payload.selected.current.harm,0);
 assert.equal(payload.selected.scenario.id,"credential-cascade");
 assert.match(payload.disclaimer,/Synthetic/);
});
test("tools support full frontier and robustness",async()=>{
 const frontier=JSON.parse((await (await rpc(4,"tools/call",{name:"horizon.control_frontier",arguments:{}})).json()).result.content[0].text);
 assert.equal(frontier.totalPolicies,32);
 const robust=JSON.parse((await (await rpc(5,"tools/call",{name:"horizon.stress_assumptions",arguments:{policy:{mfa:true}}})).json()).result.content[0].text);
 assert.equal(robust.worlds.length,6);
 assert.equal(robust.schema,"qira-event-horizon/assumption-robustness-v1");
});
test("invalid fields, arbitrary target instructions and unknown tool refused",async()=>{
 for(const params of [
  {name:"horizon.evaluate_policy",arguments:{scenarioId:"credential-cascade",policy:{extraTarget:"example.com"}}},
  {name:"horizon.evaluate_policy",arguments:{scenarioId:"credential-cascade",script:"rm -rf /"}},
  {name:"horizon.scan_external",arguments:{url:"https://example.com"}}
 ]){
  const response=await rpc(8,"tools/call",params);assert.equal(response.status,400);
  assert.equal((await response.json()).error.code,-32602);
 }
});
test("origin and MCP metadata enforced",async()=>{
 const rejected=await rpc(9,"tools/list",{}, {headers:{"Origin":"https://attacker.example"}});
 assert.equal(rejected.status,403);
 const mismatch=await rpc(10,"tools/list",{}, {headers:{"Mcp-Method":"initialize"}});
 assert.equal(mismatch.status,400);
 const wrongName=await rpc(11,"tools/call",{name:"horizon.control_frontier",arguments:{}},{headers:{"Mcp-Name":"horizon.scan_external"}});
 assert.equal(wrongName.status,400);
});
test("unknown method is HTTP 404 with JSON-RPC method-not-found",async()=>{
 const response=await rpc(12,"tools/execute");
 assert.equal(response.status,404);
 assert.equal((await response.json()).error.code,-32601);
 const get=await worker.fetch(new Request(endpoint));
 assert.equal(get.status,405);
});
test("2025 minimal compatibility and notification acceptance",async()=>{
 const r=await worker.fetch(new Request(endpoint,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({jsonrpc:"2.0",id:15,method:"tools/list"})}));
 assert.equal(r.status,200);
 const x=await r.json();assert.equal(x.result.tools.length,3);
 assert.equal(x.result.resultType,undefined);
 const n=await worker.fetch(new Request(endpoint,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({jsonrpc:"2.0",method:"notifications/initialized"})}));
 assert.equal(n.status,202);
});
