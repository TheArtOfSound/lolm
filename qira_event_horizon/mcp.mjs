/* Deliberately minimal, stateless, read-only MCP over HTTP; not full protocol certification. */
import {CONTROL_INFO,SCENARIOS,normalizePolicy,evaluate,pareto} from "./engine.mjs";
import {robustAnalysis} from "./robustness.mjs";
const VERSIONS=new Set(["2026-07-28","2025-06-18","2025-03-26"]);
const FIELDS=Object.fromEntries(CONTROL_INFO.map(c=>[c.id,{type:"boolean",description:c.cost}]));
const POLICY={type:"object",properties:FIELDS,additionalProperties:false};
const COMMON={policy:POLICY};
const TOOLS=[
 {name:"horizon.evaluate_policy",title:"Evaluate a fictional defensive policy",
  description:"Read-only analysis of a fixed synthetic security scenario. Does not interact with networks, people or production systems.",
  inputSchema:{type:"object",properties:{scenarioId:{type:"string",enum:SCENARIOS.map(s=>s.id)},...COMMON},required:["scenarioId"],additionalProperties:false},
  annotations:{readOnlyHint:true,destructiveHint:false,idempotentHint:true,openWorldHint:false}},
 {name:"horizon.control_frontier",title:"Enumerate a simulated defensive policy frontier",
  description:"Return nondominated fictional portfolios across harm, legitimate friction and implementation complexity.",
  inputSchema:{type:"object",properties:{},additionalProperties:false},
  annotations:{readOnlyHint:true,destructiveHint:false,idempotentHint:true,openWorldHint:false}},
 {name:"horizon.stress_assumptions",title:"Stress a defensive policy against hypothetical control failures",
  description:"Explore six fictional uncertainty worlds and exact minimax regret. No real-world probabilities or attack actions.",
  inputSchema:{type:"object",properties:COMMON,additionalProperties:false},
  annotations:{readOnlyHint:true,destructiveHint:false,idempotentHint:true,openWorldHint:false}}
];
function response(result,status=200){
 return new Response(JSON.stringify(result),{status,headers:{"Content-Type":"application/json; charset=utf-8","Cache-Control":"no-store","X-Content-Type-Options":"nosniff","Access-Control-Expose-Headers":"MCP-Protocol-Version","MCP-Protocol-Version":"2026-07-28"}});
}
function error(id,code,message,status=400){
 return response({jsonrpc:"2.0",id:id??null,error:{code,message}},status);
}
function validArgs(args,allowed){
 if(args===undefined)return{};
 if(!args||typeof args!=="object"||Array.isArray(args)||Object.keys(args).some(k=>!allowed.includes(k)))throw new Error("Tool arguments have unknown fields");
 return args;
}
export async function handleMcp(request){
 if(request.method!=="POST")return error(null,-32600,"MCP endpoint accepts POST only",405);
 const origin=request.headers.get("Origin");
 if(origin){try{const value=new URL(origin);
  if(value.protocol!=="https:" || !["horizon.imagineqira.com","qira-event-horizon-research.bryanleonard237.workers.dev"].includes(value.hostname))return error(null,-32600,"Origin not allowed",403);
 }catch{return error(null,-32600,"Invalid Origin",403);}}
 const type=(request.headers.get("Content-Type")||"").toLowerCase();
 if(!type.startsWith("application/json"))return error(null,-32600,"Content-Type must be application/json",415);
 const v=request.headers.get("MCP-Protocol-Version")||"2025-03-26";
 if(!VERSIONS.has(v))return error(null,-32600,"Unsupported MCP-Protocol-Version",400);
 if(Number(request.headers.get("Content-Length")||0)>8192)return error(null,-32600,"Request too large",413);
 const raw=await request.text();if(raw.length>8192)return error(null,-32600,"Request too large",413);
 let data;try{data=JSON.parse(raw);}catch{return error(null,-32700,"Invalid JSON-RPC JSON");}
 if(!data||typeof data!=="object"||Array.isArray(data)||data.jsonrpc!=="2.0"||typeof data.method!=="string"
  ||data.method.length>90||!["string","number","undefined"].includes(typeof data.id)||typeof data.id==="number"&&!Number.isSafeInteger(data.id))
  return error(null,-32600,"Invalid JSON-RPC request");
 const id=data.id??null,method=data.method,params=data.params??{};
 if(!params||typeof params!=="object"||Array.isArray(params))return error(id,-32602,"Invalid params");
 if(v==="2026-07-28"){
  if(request.headers.get("Mcp-Method")!==method)return error(id,-32600,"Mcp-Method header must match JSON-RPC method");
  if(method==="tools/call"&&request.headers.get("Mcp-Name")!==params.name)return error(id,-32600,"Mcp-Name header must match selected tool");
 }
 if(method==="notifications/initialized"&&data.id===undefined)return new Response(null,{status:202});
 if(data.id===undefined)return error(null,-32600,"Unsupported notification");
 if(method==="initialize"){
  return response({jsonrpc:"2.0",id,result:{protocolVersion:v,capabilities:{tools:{listChanged:false}},serverInfo:{name:"qira-event-horizon",version:"0.1.0"},instructions:"This tool serves fictional synthetic policy experiments only. Never interpret results as verified real-world cybersecurity outcomes."}});
 }
 if(method==="ping")return response({jsonrpc:"2.0",id,result:{}});
 if(method==="tools/list"){
  const result=v==="2026-07-28"?{resultType:"complete",tools:TOOLS,cacheScope:"public",ttlMs:300000}:{tools:TOOLS};
  return response({jsonrpc:"2.0",id,result});
 }
 if(method==="tools/call"){
  const name=params.name;
  if(typeof name!=="string"||!TOOLS.some(t=>t.name===name))return error(id,-32602,"Unsupported read-only tool");
  try{
    let result;
    if(name==="horizon.evaluate_policy"){
      const args=validArgs(params.arguments,["scenarioId","policy"]);
      if(typeof args.scenarioId!=="string")throw new Error("scenarioId is required");
      result=evaluate(normalizePolicy(args.policy||{}),args.scenarioId);
    }else if(name==="horizon.control_frontier"){
      validArgs(params.arguments,[]);
      const p=pareto();result={schema:"qira-event-horizon/frontier-v1",source:"synthetic",totalPolicies:p.all.length,frontier:p.frontier,unit:"arbitrary modeled harm and friction"};
    }else{
      const args=validArgs(params.arguments,["policy"]);
      result=robustAnalysis(normalizePolicy(args.policy||{}));
    }
    const body=v==="2026-07-28"?{resultType:"complete",content:[{type:"text",text:JSON.stringify(result)}],isError:false}
     :{content:[{type:"text",text:JSON.stringify(result)}],isError:false};
    return response({jsonrpc:"2.0",id,result:body});
  }catch(e){return error(id,-32602,typeof e?.message==="string"?e.message:"Invalid tool arguments");}
 }
 return error(id,-32601,"Method not found",404);
}
