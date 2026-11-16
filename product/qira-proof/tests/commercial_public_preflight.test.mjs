import test from "node:test";
import assert from "node:assert/strict";
import {parseRepository,publicRepositoryPreflight} from "../commercial/public_preflight.mjs";
import worker from "../commercial/landing.mjs";
const base="https://proof.imagineqira.com/api/public-repository?repo=";
const json=(body,status=200)=>new Response(JSON.stringify(body),{status,headers:{"content-type":"application/json"}});
const repo={private:false,full_name:"TheArtOfSound/lolm",default_branch:"main"};
const workflows=(count)=>Array.from({length:count},(_,i)=>({type:"file",name:"workflow"+i+".yml"}));
const request=(value,method="GET")=>new Request(base+encodeURIComponent(value),{method});
const mock=(directory,count=2)=>async(url,init)=>{
 assert.ok(url.startsWith("https://api.github.com/repos/TheArtOfSound/lolm"));
 assert.equal(init.method,"GET");
 assert.equal(init.redirect,"manual");
 assert.equal(init.headers["User-Agent"],"Qira-Proof-Public-Inventory");
 assert.equal(init.headers.authorization,undefined);
 return url.includes("/contents/.github/workflows")?directory??json(workflows(count)):json(repo);
};

test("accepts only two validated GitHub repository path segments and never arbitrary origins",()=>{
 for(const entry of ["https://github.com/TheArtOfSound/lolm","github.com/TheArtOfSound/lolm","TheArtOfSound/lolm"])
  assert.deepEqual(parseRepository(entry),{owner:"TheArtOfSound",name:"lolm",key:"theartofsound/lolm"});
 for(const entry of ["","https://evil.example/user/repo","https://github.com.evil.example/x/y",
  "http://github.com/x/y","https://login:pw@github.com/x/y","https://github.com/x/y?token=123",
  "https://github.com/x/y#secret","github.com/x/y/extra","not-a-repository",
  "../escape","https://github.com/%2E%2E/repo"]){
  assert.equal(parseRepository(entry),null,entry);
 }
});

test("public repo count is sourced from real directory response, not generated risks",async()=>{
 let calls=0;
 const fetcher=async(url,options)=>{calls++;return mock(null,2)(url,options);};
 const response=await publicRepositoryPreflight(request("github.com/TheArtOfSound/lolm"),{},fetcher);
 assert.equal(response.status,200);
 const body=await response.json();
 assert.equal(body.status,"within_scope");
 assert.equal(body.repository,"TheArtOfSound/lolm");
 assert.equal(body.workflow_count,2);
 assert.equal(body.workflow_count_limit,20);
 assert.equal(body.workflow_count_complete,true);
 assert.match(body.notice,/No security scan/);
 assert.equal(calls,2);
 assert.equal(response.headers.get("cache-control"),"no-store");
 assert.equal(response.headers.get("x-robots-tag"),"noindex,nofollow");
});

test("YAML-only file counting ignores unrelated README and JSON files",async()=>{
 const entries=[{type:"file",name:"build.yml"},{type:"file",name:"deploy.yaml"},
 {type:"file",name:"README.md"},{type:"file",name:"build.json"},{type:"dir",name:"other.yaml"}];
 const response=await publicRepositoryPreflight(request("TheArtOfSound/lolm"),{},mock(json(entries)));
 assert.equal((await response.json()).workflow_count,2);
});

test("21 workflows return out-of-scope, not automatic purchase approval",async()=>{
 const response=await publicRepositoryPreflight(request("TheArtOfSound/lolm"),{},mock(null,21));
 assert.equal((await response.json()).status,"outside_standard_scope");
});

test("empty directory and oversized response are explicitly differentiated",async()=>{
 const empty=await publicRepositoryPreflight(request("TheArtOfSound/lolm"),{},mock(json([],404)));
 assert.equal((await empty.json()).status,"no_workflows");
 const truncated=Array.from({length:1000},(_,i)=>({type:"file",name:"file"+i+".txt"}));
 const unavailable=await publicRepositoryPreflight(request("TheArtOfSound/lolm"),{},mock(json(truncated)));
 assert.equal((await unavailable.json()).status,"inventory_unavailable");
});

test("private or absent repository is never represented as public or safe",async()=>{
 const absent=await publicRepositoryPreflight(request("TheArtOfSound/lolm"),{},async()=>json({message:"Not Found"},404));
 assert.equal(absent.status,404);
 assert.equal((await absent.json()).status,"not_public");
 const privateRepo=await publicRepositoryPreflight(request("TheArtOfSound/lolm"),{},async()=>json({...repo,private:true}));
 assert.equal(privateRepo.status,404);
 assert.equal((await privateRepo.json()).status,"not_public");
});

test("rate limits and parse errors fail transparently without security findings",async()=>{
 const limited=await publicRepositoryPreflight(request("TheArtOfSound/lolm"),{},async()=>json({message:"Rate limit"},403));
 assert.equal(limited.status,503);
 assert.equal((await limited.json()).status,"rate_limited");
 const malformed=await publicRepositoryPreflight(request("TheArtOfSound/lolm"),{},async()=>new Response("not json"));
 assert.equal(malformed.status,503);
 assert.equal((await malformed.json()).status,"unavailable");
});

test("untrusted URL never triggers outbound API calls",async()=>{
 let called=0;
 const response=await publicRepositoryPreflight(request("https://unknown.example/anything"),{},async()=>{called++;throw Error("unexpected");});
 assert.equal(response.status,400);
 assert.equal(called,0);
});

test("experimental public GitHub API is not routed in the production storefront",async()=>{
 const response=await worker.fetch(request("TheArtOfSound/lolm"));
 assert.equal(response.status,404);
 assert.equal(response.headers.get("x-robots-tag"),"noindex");
});

test("public endpoint is not a paid entitlement or repository scanner",async()=>{
 const text=(await (await worker.fetch(new Request("https://proof.imagineqira.com/"))).text());
 assert.match(text,/No repository is accessed/);
 assert.doesNotMatch(text,/fetch\s*\(/);
 assert.match(text,/Private repository\? Continue directly/);
 const health=await worker.fetch(new Request("https://proof.imagineqira.com/health"));
 assert.equal((await health.json()).product,"qira-proof-commercial");
});
