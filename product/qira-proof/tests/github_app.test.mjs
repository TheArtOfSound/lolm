import test from "node:test";
import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import {handleGitHubApp} from "../github_app.mjs";
if(!globalThis.crypto)globalThis.crypto=webcrypto;

const origin="https://qira.example";
const clock=()=>1_800_000_000_000;
const b64=(bytes)=>Buffer.from(bytes).toString("base64url");
const env={
  QIRA_PUBLIC_ORIGIN:origin,
  GITHUB_APP_CLIENT_ID:"Iv1.123456789abcdef",
  GITHUB_APP_CLIENT_SECRET:"example-only-not-a-real-secret",
  QIRA_SESSION_KEY:b64(Buffer.from(Array.from({length:32},(_,i)=>i+1))),
  GITHUB_APP_SLUG:"qira-proof-lab"
};
const tok="ghu_"+"T".repeat(70);
let visited=[];
function mockFetch(input,options={}){
 const url=String(input);
 visited.push({url,method:options.method||"GET",headers:options.headers||{},body:options.body||""});
 let value;
 if(url==="https://github.com/login/oauth/access_token"){
   if(!options.body.includes("code_verifier="))throw Error("PKCE not forwarded");
   value={access_token:tok,token_type:"bearer",expires_in:3600};
 }else if(url.includes("/user/installations/123/repositories")){
   value={total_count:1,repositories:[{full_name:"TheArtOfSound/lolm",default_branch:"main"}]};
 }else if(url.includes("/user/installations?")){
   value={total_count:1,installations:[{id:123,account:{login:"example-org"},repository_selection:"selected"}]};
 }else if(url.includes("/repos/TheArtOfSound/lolm/commits/main")){
   value={sha:"0123456789abcdef0123456789abcdef01234567"};
 }else if(url.includes("/repos/TheArtOfSound/lolm/contents/.github/workflows?")){
   value=[{path:".github/workflows/deploy-production.yml",type:"file"},
          {path:".github/workflows/publish.yml",type:"file"},
          {path:".github/workflows/subfolder/malicious.yml",type:"dir"}];
 }else if(url.includes("/repos/TheArtOfSound/lolm/contents/")){
   const body="name: Deploy\njobs:\n  deploy:\n    steps:\n    - uses: actions/checkout@v4\n    - run: ssh-keyscan -H example.org >> ~/.ssh/known_hosts\n";
   value={encoding:"base64",content:Buffer.from(body).toString("base64")};
 }else throw Error("unexpected provider URL: "+url);
 return Promise.resolve(new Response(JSON.stringify(value),{status:200,headers:{"content-type":"application/json"}}));
}
const req=(path,options={})=>new Request(origin+path,options);
async function session(){
  visited=[];
  const start=await handleGitHubApp(req("/connect/github"),env,{fetcher:mockFetch,clock});
  assert.equal(start.status,303);
  const redirect=new URL(start.headers.get("location"));
  const state=redirect.searchParams.get("state");
  const pending=(start.headers.get("set-cookie")||"").match(/__Host-qira_git_state=([^;]+)/)?.[1];
  assert.ok(pending);
  const callback=await handleGitHubApp(req("/oauth/github/callback?code=1234567890ABCD&state="+state,{headers:{cookie:"__Host-qira_git_state="+pending}}),env,{fetcher:mockFetch,clock});
  assert.equal(callback.status,303);
  const cookieHeader=callback.headers.get("set-cookie")||"";
  const ciphertext=cookieHeader.match(/__Host-qira_git_session=([^;]+)/)?.[1];
  assert.ok(ciphertext);
  return {start,redirect,callback,state,pending,ciphertext,
     headers:{cookie:"__Host-qira_git_session="+ciphertext}};
}
async function scoped(s,path,selection,extra={}){
 const status=await handleGitHubApp(req("/api/github/status",{headers:s.headers}),env,{fetcher:mockFetch,clock});
 const csrf=(await status.json()).csrf;
 return handleGitHubApp(req(path,{method:"POST",headers:{
   ...s.headers,origin,"content-type":"application/json","x-qira-csrf":csrf,
   ...(extra.headers||{})},body:JSON.stringify(selection)}),env,{fetcher:extra.fetcher||mockFetch,clock});
}
test("disabled connector never redirects visitors to fake GitHub login",async()=>{
  const disabled=await handleGitHubApp(req("/api/github/status"),{},{fetcher:mockFetch,clock});
  const out=await disabled.json();
  assert.equal(out.configured,false);
  assert.equal(out.connected,false);
  const attempt=await handleGitHubApp(req("/connect/github"),{},{fetcher:mockFetch,clock});
  assert.equal(attempt.status,503);
});
test("OAuth uses strong state and GitHub App PKCE S256",async()=>{
  const s=await session();
  assert.equal(s.redirect.origin,"https://github.com");
  assert.equal(s.redirect.pathname,"/login/oauth/authorize");
  assert.equal(s.redirect.searchParams.get("code_challenge_method"),"S256");
  assert.equal(s.redirect.searchParams.get("redirect_uri"),origin+"/oauth/github/callback");
  assert.ok(s.state.length>=20);
  const status=await handleGitHubApp(req("/api/github/status",{headers:s.headers}),env,{fetcher:mockFetch,clock});
  const info=await status.json();
  assert.equal(info.connected,true);
  assert.equal(info.configured,true);
  assert.ok(info.csrf);
  assert.match(info.install_url,/^https:\/\/github.com\/apps\/qira-proof-lab\/installations\/new$/);
  assert.ok(!JSON.stringify(info).includes(tok));
  assert.ok(!s.callback.headers.get("set-cookie").includes(tok));
  assert.ok(!s.start.headers.get("set-cookie").includes("code_verifier"));
});
test("Callback rejects invalid state BEFORE token exchange",async()=>{
  const s=await session();
  visited=[];
  const bad=await handleGitHubApp(req("/oauth/github/callback?code=1234567890ABCD&state=badbadbadbadbadbad",
   {headers:{cookie:"__Host-qira_git_state="+s.pending}}),env,{fetcher:mockFetch,clock});
  assert.equal(bad.status,303);
  assert.equal(new URL(bad.headers.get("location")).searchParams.get("github"),"failed");
  assert.equal(visited.length,0);
});
test("Callback rejects expired state and missing cookies",async()=>{
  const s=await session();
  const tooLate=()=>clock()+11*60*1000;
  const expired=await handleGitHubApp(req("/oauth/github/callback?code=1234567890ABCD&state="+s.state,
   {headers:{cookie:"__Host-qira_git_state="+s.pending}}),env,{fetcher:mockFetch,clock:tooLate});
  assert.match(expired.headers.get("location"),/github=failed/);
  const missing=await handleGitHubApp(req("/oauth/github/callback?code=1234567890ABCD&state="+s.state),env,
    {fetcher:mockFetch,clock});
  assert.match(missing.headers.get("location"),/github=failed/);
});
test("User must be authenticated before listing installations",async()=>{
  const response=await handleGitHubApp(req("/api/github/installations"),env,{fetcher:mockFetch,clock});
  assert.equal(response.status,401);
});
test("Verified user installation controls accessible repositories",async()=>{
 const s=await session();
 const list=await handleGitHubApp(req("/api/github/installations",{headers:s.headers}),env,{fetcher:mockFetch,clock});
 assert.deepEqual((await list.json()).items,[{id:123,account:"example-org",selection:"selected"}]);
 const allowed=await scoped(s,"/api/github/repos",{installation_id:123});
 assert.deepEqual((await allowed.json()).repos,[{name:"TheArtOfSound/lolm",branch:"main"}]);
 const spoofed=await scoped(s,"/api/github/repos",{installation_id:999});
 assert.equal(spoofed.status,403);
});
test("Selected workflow content is fetched only after the installation and repo are authorized",async()=>{
 const s=await session();
 visited=[];
 const assessment=await scoped(s,"/api/github/assessment",{installation_id:123,
  repo:"TheArtOfSound/lolm",workflow:".github/workflows/deploy-production.yml"});
 assert.equal(assessment.status,200);
 const out=await assessment.json();
 assert.equal(out.snapshot.facts.find(x=>x.signal==="runtime_ssh_keyscan").value,true);
 assert.equal(out.snapshot.facts.find(x=>x.signal==="workflow_unpinned_actions").value,true);
 assert.equal(out.snapshot.facts.find(x=>x.signal==="ssh_host_key_pinned").value,"unknown");
 assert.ok(out.snapshot.facts.every(f=>f.provider==="github"));
 assert.ok(!JSON.stringify(out).includes(tok));
 assert.ok(!JSON.stringify(out).includes("ssh-keyscan"));
 assert.ok(visited.every(v=>v.method==="GET"&&v.url.startsWith("https://api.github.com/")));
});
test("Malformed paths and unauthorized repositories are rejected",async()=>{
 const s=await session();
 for(const selection of [
  {installation_id:123,repo:"other/repo",workflow:".github/workflows/deploy.yml"},
  {installation_id:123,repo:"TheArtOfSound/lolm",workflow:"../../secrets.yml"},
  {installation_id:123,repo:"TheArtOfSound/lolm",workflow:".github/workflows/a.yml?query"},
  {installation_id:"foo",repo:"TheArtOfSound/lolm",workflow:".github/workflows/deploy.yml"},
  {installation_id:123,repo:"TheArtOfSound/lolm",workflow:".github/workflows/deploy.yml",extra:"secret"}
 ]){
  const resp=await scoped(s,"/api/github/assessment",selection);
  assert.ok([400,403,502].includes(resp.status),resp.status);
 }
});

test("Missing or inaccessible .github/workflows is a documented empty selector, not a 502",async()=>{
 const s=await session();
 for(const code of [404]){
  const fallback=async(input,options={})=>{
   const u=String(input);
   if(u.includes("/repos/TheArtOfSound/lolm/contents/.github/workflows?")){
    assert.equal(options.method,"GET");
    return new Response(JSON.stringify({message:"Not Found",sensitive:"should-not-surface"}),{
     status:code,headers:{"content-type":"application/json"}});
   }
   return mockFetch(input,options);
  };
  const result=await scoped(s,"/api/github/workflows",{
   installation_id:123,repo:"TheArtOfSound/lolm"
  },{fetcher:fallback});
  assert.equal(result.status,200);
  const json=await result.json();
  assert.deepEqual(json.workflows,[]);
  assert.equal(json.branch,"main");
  assert.equal(json.availability,"directory_not_found_or_inaccessible");
  assert.equal(json.truncated,false);
  assert.ok(!JSON.stringify(json).includes("sensitive"));
  assert.ok(!JSON.stringify(json).includes(tok));
 }
});
test("Workflow listing 403 or 500 is never silently relabeled as a missing directory",async()=>{
 const s=await session();
 for(const status of [401,403,500]){
  const fallback=(input,options={})=>String(input).includes("/repos/TheArtOfSound/lolm/contents/.github/workflows?")?
   Promise.resolve(new Response("private details", {status})):mockFetch(input,options);
  const result=await scoped(s,"/api/github/workflows",{
   installation_id:123,repo:"TheArtOfSound/lolm"
  },{fetcher:fallback});
  assert.equal(result.status,502);
  const body=await result.text();
  assert.ok(!body.includes("private details"));
 }
});
test("An existing directory without recognized YAML workflows is a valid empty selector",async()=>{
 const s=await session();
 const fallback=(input,options={})=>String(input).includes("/repos/TheArtOfSound/lolm/contents/.github/workflows?")?
  Promise.resolve(new Response(JSON.stringify([{type:"file",path:".github/workflows/README.txt"}]),{
   status:200,headers:{"content-type":"application/json"}})):mockFetch(input,options);
 const result=await scoped(s,"/api/github/workflows",{
  installation_id:123,repo:"TheArtOfSound/lolm"
 },{fetcher:fallback});
 assert.equal(result.status,200);
 const body=await result.json();
 assert.deepEqual(body.workflows,[]);
 assert.equal(body.availability,"no_supported_workflows");
});

test("bounded repository workflow review keeps workflow-specific, immutable evidence",async()=>{
 const s=await session();
 visited=[];
 const response=await scoped(s,"/api/github/assessment",{
  installation_id:123,repo:"TheArtOfSound/lolm",workflow:"__all__"
 });
 assert.equal(response.status,200);
 const data=await response.json();
 assert.equal(data.coverage.mode,"bounded-repository-workflows");
 assert.equal(data.coverage.assessed,2);
 assert.equal(data.coverage.discovered,2);
 assert.equal(data.coverage.skipped,0);
 assert.equal(data.coverage.complete,true);
 assert.equal(data.coverage.truncated,false);
 assert.equal(data.coverage.commit,"0123456789abcdef0123456789abcdef01234567");
 const a=data.snapshot.facts;
 assert.equal(a.filter(x=>x.signal==="workflow_unpinned_actions").length,2);
 assert.equal(a.filter(x=>x.signal==="repo_branch_protection_verifiable").length,1);
 assert.ok(a.some(x=>x.asset==="TheArtOfSound/lolm:.github/workflows/deploy-production.yml"));
 assert.ok(a.some(x=>x.asset==="TheArtOfSound/lolm:.github/workflows/publish.yml"));
 assert.ok(a.filter(x=>x.signal==="workflow_unpinned_actions").every(x=>
  x.source_url.includes("/blob/0123456789abcdef0123456789abcdef01234567/")));
 assert.ok(visited.filter(v=>v.url.includes("/commits/main")).length===1);
 assert.ok(!JSON.stringify(data).includes(tok));
});
test("bounded scan is explicitly partial when one workflow becomes inaccessible",async()=>{
 const s=await session();
 const fake=(url,options={})=>String(url).includes("/contents/.github/workflows/publish.yml?")?
  Promise.resolve(new Response(JSON.stringify({message:"Not Found",private:"never-export"}),{status:404})):
  mockFetch(url,options);
 const response=await scoped(s,"/api/github/assessment",{installation_id:123,
  repo:"TheArtOfSound/lolm",workflow:"__all__"},{fetcher:fake});
 assert.equal(response.status,200);
 const data=await response.json();
 assert.equal(data.coverage.assessed,1);
 assert.equal(data.coverage.skipped,1);
 assert.equal(data.coverage.complete,false);
 assert.equal(data.coverage.truncated,false);
 assert.ok(!data.snapshot.facts.some(f=>f.asset.includes("publish.yml")));
 assert.ok(!JSON.stringify(data).includes("never-export"));
});
test("more than 20 workflows is reported as truncated; no more than 20 are read",async()=>{
 const s=await session();
 let fetches=0;
 const fake=(url,options={})=>{
  if(String(url).includes("/contents/.github/workflows?")){
   const workflows=Array.from({length:25},(_,i)=>({
    type:"file",path:".github/workflows/test-"+String(i).padStart(2,"0")+".yml"}));
   return Promise.resolve(Response.json(workflows));
  }
  if(String(url).includes("/contents/.github/workflows/test-"))fetches++;
  return mockFetch(url,options);
 };
 const response=await scoped(s,"/api/github/assessment",{
  installation_id:123,repo:"TheArtOfSound/lolm",workflow:"__all__"
 },{fetcher:fake});
 assert.equal(response.status,200);
 const data=await response.json();
 assert.equal(data.coverage.discovered,25);
 assert.equal(data.coverage.assessed,20);
 assert.equal(data.coverage.selected,20);
 assert.equal(data.coverage.truncated,true);
 assert.equal(data.coverage.complete,false);
 assert.equal(fetches,20);
 assert.ok(data.snapshot.facts.length<=150);
});
test("bulk review refuses false success when every file fetch fails",async()=>{
 const s=await session();
 const fake=(url,options={})=>String(url).includes("/contents/.github/workflows/")?
  Promise.resolve(new Response("access unavailable",{status:403})):mockFetch(url,options);
 const response=await scoped(s,"/api/github/assessment",{
  installation_id:123,repo:"TheArtOfSound/lolm",workflow:"__all__"
 },{fetcher:fake});
 assert.equal(response.status,502);
 assert.ok(!(await response.text()).includes("access unavailable"));
});

test("Selection endpoints forbid GET URLs and CSRF-less cross-site POSTs",async()=>{
 const s=await session();
 for(const path of ["/api/github/repos","/api/github/workflows","/api/github/assessment"]){
  const get=await handleGitHubApp(req(path+"?repo=secret-org%2Frepo",{headers:s.headers}),env,{fetcher:mockFetch,clock});
  assert.equal(get.status,405);
  const noCSRF=await handleGitHubApp(req(path,{
   method:"POST",headers:{...s.headers,origin,"content-type":"application/json"},
   body:JSON.stringify({installation_id:123})}),env,{fetcher:mockFetch,clock});
  assert.equal(noCSRF.status,403);
 }
});
test("Disconnect needs origin and session CSRF; it never claims remote token revocation",async()=>{
  const s=await session();
  const check=await handleGitHubApp(req("/api/github/status",{headers:s.headers}),env,{fetcher:mockFetch,clock});
  const csrf=(await check.json()).csrf;
  const missing=await handleGitHubApp(req("/api/github/disconnect",{method:"POST",headers:s.headers}),env,{fetcher:mockFetch,clock});
  assert.equal(missing.status,403);
  const forged=await handleGitHubApp(req("/api/github/disconnect",{method:"POST",headers:{...s.headers,origin:"https://attacker.example","x-qira-csrf":csrf}}),env,{fetcher:mockFetch,clock});
  assert.equal(forged.status,403);
  const valid=await handleGitHubApp(req("/api/github/disconnect",{method:"POST",headers:{...s.headers,origin,"x-qira-csrf":csrf}}),env,{fetcher:mockFetch,clock});
  assert.equal(valid.status,200);
  assert.equal((await valid.json()).server_side_token_revoked,false);
  assert.match(valid.headers.get("set-cookie"),/__Host-qira_git_session=;/);
});
test("Session expires and cannot be reused after its TTL",async()=>{
  const s=await session();
  const expired=await handleGitHubApp(req("/api/github/installations",{headers:s.headers}),env,{fetcher:mockFetch,clock:()=>clock()+16*60*1000});
  assert.equal(expired.status,401);
});
test("Public origin and secret configuration must be complete",async()=>{
  const alt={...env,QIRA_PUBLIC_ORIGIN:"https://evil.example/path"};
  assert.equal((await (await handleGitHubApp(req("/api/github/status"),alt,{fetcher:mockFetch,clock})).json()).configured,false);
  const cross=await handleGitHubApp(new Request("https://other.example/connect/github"),env,{fetcher:mockFetch,clock});
  assert.equal(cross.status,503);
});


test("Workflow picker lists only authorized YAML files",async()=>{
 const s=await session();
 const response=await scoped(s,"/api/github/workflows",{installation_id:123,repo:"TheArtOfSound/lolm"});
 assert.equal(response.status,200);
 const data=await response.json();
 assert.equal(data.repo,"TheArtOfSound/lolm");
 assert.deepEqual(data.workflows,[
  {path:".github/workflows/deploy-production.yml"},
  {path:".github/workflows/publish.yml"}
 ]);
 const denied=await scoped(s,"/api/github/workflows",{installation_id:123,repo:"another/repo"});
 assert.equal(denied.status,502);
});
test("Unknown API routes return not-found rather than granting metadata access",async()=>{
 const s=await session();
 const r=await handleGitHubApp(req("/api/github/debug?installation_id=123",{headers:s.headers}),env,{fetcher:mockFetch,clock});
 assert.equal(r.status,404);
});

test("Unrelated app and static routes bypass the OAuth subsystem",async()=>{
 assert.equal(await handleGitHubApp(req("/"),{}),null);
 assert.equal(await handleGitHubApp(req("/app.mjs"),{}),null);
 assert.equal(await handleGitHubApp(req("/health"),{}),null);
});
