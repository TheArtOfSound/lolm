import {CONTROL_INFO,SCENARIOS} from "./engine.mjs";
const fields=Object.fromEntries(CONTROL_INFO.map(c=>[c.id,{type:"boolean",description:c.cost,default:false}]));
export const OPENAPI={
 openapi:"3.1.0",
 info:{title:"Qira Event Horizon — Synthetic Research API",version:"0.2.0",
  description:"Public fictional security-policy simulation. Read-only effects; no live targeting, customer telemetry, or validated prevention claims."},
 servers:[{url:"https://horizon.imagineqira.com"}],
 tags:[{name:"Synthetic simulation",description:"Deterministic models with arbitrary utility units"}],
 paths:{
  "/health":{get:{tags:["Synthetic simulation"],summary:"Health and research mode",responses:{"200":{description:"Live synthetic-only service",content:{"application/json":{schema:{type:"object",properties:{ok:{type:"boolean"},mode:{const:"read-only"},data:{const:"fictional"}}}}}}}}},
  "/api/meta":{get:{tags:["Synthetic simulation"],summary:"Available scenarios and defensive controls",responses:{"200":{description:"Fixed fictional manifest"}}}},
  "/api/evaluate":{post:{tags:["Synthetic simulation"],summary:"Evaluate fixed scenario and hypothetical policy",description:"Changes no customer state. Enumerates 32 portfolios and six assumption worlds; includes SHA-256 integrity receipt.",requestBody:{required:true,content:{"application/json":{schema:{type:"object",properties:{scenarioId:{type:"string",enum:SCENARIOS.map(s=>s.id)},policy:{$ref:"#/components/schemas/Policy"}},required:["scenarioId"],additionalProperties:false}}}},responses:{"200":{description:"Reproducible hypothetical result",content:{"application/json":{schema:{type:"object",properties:{schema:{type:"string"},selected:{type:"object"},summary:{type:"object"},frontier:{type:"array",items:{type:"object"}},robustness:{type:"object"},receipt:{$ref:"#/components/schemas/Receipt"}}}}}},"400":{description:"Unknown scenario or invalid control"},"413":{description:"Request size exceeds 4KB"},"415":{description:"Unsupported media type"}}}},
  "/mcp":{post:{tags:["Synthetic simulation"],summary:"Stateless experimental Streamable HTTP MCP tool endpoint",description:"Only initialize, ping, tools/list, tools/call and initialized notification. Tools are read-only, synthetic-only. Not a full MCP conformance claim.",requestBody:{required:true,content:{"application/json":{schema:{type:"object",description:"One JSON-RPC 2.0 request"}}}},responses:{"200":{description:"JSON-RPC response"},"202":{description:"Initialized notification accepted"},"400":{description:"Rejected protocol request"},"404":{description:"Unknown MCP method"}}}}
 },
 components:{schemas:{
  Policy:{type:"object",properties:fields,additionalProperties:false,description:"Optional boolean fictional defensive controls"},
  Receipt:{type:"object",properties:{algorithm:{const:"SHA-256"},digest:{type:"string",pattern:"^[0-9a-f]{64}$"},meaning:{type:"string"}},required:["algorithm","digest","meaning"],description:"Integrity of returned synthetic payload, not a digital signature or real outcome"}
 }}
};
