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
 }else if(url.includes("/repos/TheArtOfSound/lolm/contents/.github/workflows?")){
   value=[{path:".github/workflows/deploy-production.yml",type:"file"},
          {path:".github/workflows/publish.yml",type:"file"},
          {path:".github/workflows/subfolder/malicious.yml",type:"dir"}];
 }else if(url.includes("/repos/TheArtOfSound/lolm/contents/")){
   const body="name: Deploy\njobs:\n  deploy:\n    steps:\n    - run: ssh-keyscan -H example.org >> ~/.ssh/known_hosts\n";
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
  const allowed=await handleGitHubApp(req("/api/github/repos?installation_id=123",{headers:s.headers}),
    env,{fetcher:mockFetch,clock});
  assert.deepEqual((await allowed.json()).repos,[{name:"TheArtOfSound/lolm",branch:"main"}]);
  const spoofed=await handleGitHubApp(req("/api/github/repos?installation_id=999",{headers:s.headers}),
    env,{fetcher:mockFetch,clock});
  assert.equal(spoofed.status,403);
});
test("Remote content is read only from a proven accessible repo and selected workflow",async()=>{
  const s=await session();
  visited=[];
  const assessment=await handleGitHubApp(req("/api/github/assessment?installation_id=123&repo=TheArtOfSound%2Flolm&workflow=.github%2Fworkflows%2Fdeploy-production.yml",
    {headers:s.headers}),env,{fetcher:mockFetch,clock});
  assert.equal(assessment.status,200);
  const out=await assessment.json();
  assert.equal(out.snapshot.facts.find(x=>x.signal==="runtime_ssh_keyscan").value,true);
  assert.equal(out.snapshot.facts.find(x=>x.signal==="ssh_host_key_pinned").value,"unknown");
  assert.ok(out.snapshot.facts.every(f=>f.provider==="github"));
  assert.ok(!JSON.stringify(out).includes(tok));
  assert.ok(!JSON.stringify(out).includes("ssh-keyscan"));
  assert.ok(visited.every(v=>v.method==="GET"&&v.url.startsWith("https://api.github.com/")));
});
test("Malformed repo and injection selectors are rejected",async()=>{
  const s=await session();
  for(const params of [
   "installation_id=123&repo=other%2Frepo&workflow=.github%2Fworkflows%2Fdeploy.yml",
   "installation_id=123&repo=TheArtOfSound%2Flolm&workflow=..%2F..%2Fsecrets.yml",
   "installation_id=123&repo=TheArtOfSound%2Flolm&workflow=.github%2Fworkflows%2Fa.yml%3Fquery",
   "installation_id=foo&repo=TheArtOfSound%2Flolm&workflow=.github%2Fworkflows%2Fdeploy.yml",
  ]){
    const resp=await handleGitHubApp(req("/api/github/assessment?"+params,{headers:s.headers}),env,{fetcher:mockFetch,clock});
    assert.ok(resp.status===400||resp.status===502,resp.status);
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


test("Workflow picker only lists authorized YAML files in the selected installation",async()=>{
 const s=await session();
 const response=await handleGitHubApp(req(
  "/api/github/workflows?installation_id=123&repo=TheArtOfSound%2Flolm",
  {headers:s.headers}),env,{fetcher:mockFetch,clock});
 assert.equal(response.status,200);
 const data=await response.json();
 assert.equal(data.repo,"TheArtOfSound/lolm");
 assert.deepEqual(data.workflows,[
  {path:".github/workflows/deploy-production.yml"},
  {path:".github/workflows/publish.yml"}
 ]);
 const denied=await handleGitHubApp(req(
  "/api/github/workflows?installation_id=123&repo=another%2Frepo",
  {headers:s.headers}),env,{fetcher:mockFetch,clock});
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
