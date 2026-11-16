import test from "node:test";
import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import {handleGitHubApp} from "../github_app.mjs";
if(!globalThis.crypto)globalThis.crypto=webcrypto;
const origin="https://qira.example";
const t=1_800_000_000_000;
const allow={limit:async()=>({success:true})};
const env={
 QIRA_AUTH_RATE_LIMITER:allow,
 QIRA_READ_RATE_LIMITER:allow,
 QIRA_PUBLIC_ORIGIN:origin,
 GITHUB_APP_CLIENT_ID:"Iv1.123456789abcdef",
 GITHUB_APP_CLIENT_SECRET:"placeholder-not-a-real-secret",
 GITHUB_APP_SLUG:"qira-proof-research",
 QIRA_SESSION_KEY:Buffer.from(Array.from({length:32},(_,i)=>i+1)).toString("base64url")
};
function request(path,options={}){return new Request(origin+path,options);}
function reason(response){
 const url=new URL(response.headers.get("location"));
 assert.equal(url.origin,origin);
 assert.equal(url.searchParams.get("github"),"failed");
 assert.ok(!url.search.includes("access_token"));
 assert.ok(!url.search.includes("code="));
 return url.searchParams.get("reason");
}
async function start(){
 const res=await handleGitHubApp(request("/connect/github"),env,{clock:()=>t});
 assert.equal(res.status,303);
 const state=new URL(res.headers.get("location")).searchParams.get("state");
 const stateCookie=res.headers.get("set-cookie").match(/__Host-qira_git_state=([^;]+)/)?.[1];
 assert.ok(stateCookie);
 return {state,stateCookie};
}
async function finish({state,stateCookie},fetcher=async()=>new Response("{}",{status:503}),at=t,extra=""){
 return handleGitHubApp(request("/oauth/github/callback?state="+state+"&code=validcode12345"+extra,
  {headers:{cookie:"__Host-qira_git_state="+stateCookie}}),env,
  {fetcher,clock:()=>at});
}
test("denied authorization is distinguishable, with no provider-supplied text in URL",async()=>{
 const s=await start();
 const res=await finish(s,undefined,t,"&error=access_denied&error_description=never-reflect-this");
 assert.equal(reason(res),"authorization_denied");
 assert.doesNotMatch(res.headers.get("location"),/never-reflect/);
});
test("missing, expired and tampered authorization state receive distinct fixed reasons",async()=>{
 const s=await start();
 const missing=await handleGitHubApp(request("/oauth/github/callback?state="+s.state+"&code=validcode12345"),env,{clock:()=>t});
 assert.equal(reason(missing),"state_missing");
 const expired=await finish(s,undefined,t+11*60*1000);
 assert.equal(reason(expired),"state_expired");
 const wrong=await finish({...s,state:"not-the-original-state"});
 assert.equal(reason(wrong),"state_mismatch");
});
test("known GitHub provider errors never expose response payloads",async()=>{
 const s=await start();
 for(const [providerError,expected] of [
  ["incorrect_client_credentials","client_credentials"],
  ["redirect_uri_mismatch","callback_mismatch"],
  ["bad_verification_code","authorization_code_rejected"],
  ["unverified_user_email","email_unverified"],
  ["application_suspended","app_suspended"],
  ["unexpected_server_specific_error","provider_rejected"]
 ]){
  const fetcher=async()=>new Response(JSON.stringify({error:providerError,
   error_description:"secret-sensitive-details"}),{status:200});
  const res=await finish(s,fetcher);
  assert.equal(reason(res),expected);
  assert.doesNotMatch(res.headers.get("location"),/sensitive|incorrect_client_credentials/);
 }
});
test("nonexpiring user tokens are rejected with an actionable configuration reason",async()=>{
 const s=await start();
 const fetcher=async()=>new Response(JSON.stringify({access_token:"ghu_"+"T".repeat(55),
  token_type:"bearer"}),{status:200});
 assert.equal(reason(await finish(s,fetcher)),"token_expiration_disabled");
});
test("provider errors, invalid bodies and outages remain fail closed",async()=>{
 const s=await start();
 const invalid=await finish(s,async()=>new Response("not json",{status:200}));
 assert.equal(reason(invalid),"token_invalid");
 const network=await finish(s,async()=>{throw Error("private-network-detail")});
 assert.equal(reason(network),"exchange_transport");
});

test("OAuth exchange explicitly rejects redirects without following them",async()=>{
 const ctx=await start();
 const fetcher=async(url,opts)=>{
  assert.equal(opts.redirect,"manual");
  assert.equal(opts.method,"POST");
  return new Response(null,{status:302,headers:{location:"https://attacker.invalid/capture"}});
 };
 const res=await finish(ctx,fetcher);
 assert.equal(reason(res),"exchange_http_4xx");
 assert.ok(!res.headers.get("location").includes("attacker.invalid"));
});
test("provider codes are classified even when GitHub returns non-2xx HTTP statuses",async()=>{
 const ctx=await start();
 for(const [status,error,expected] of [
  [400,"incorrect_client_credentials","client_credentials"],
  [401,"bad_verification_code","authorization_code_rejected"],
  [403,"redirect_uri_mismatch","callback_mismatch"],
  [503,"temporarily_unavailable","provider_rejected"]
 ]){
  const res=await finish(ctx,async()=>new Response(JSON.stringify({
   error,error_description:"SENSITIVE-PROVIDER-TEXT-never-public"
  }),{status}));
  assert.equal(reason(res),expected);
  assert.doesNotMatch(res.headers.get("location"),/SENSITIVE|bad_verification_code/);
 }
});
test("non-JSON HTTP errors are classified without copying provider bodies",async()=>{
 const ctx=await start();
 for(const [status,expected] of [
  [403,"exchange_http_4xx"],
  [502,"exchange_http_5xx"]
 ]){
  const res=await finish(ctx,async()=>new Response("<html>never-share-secret</html>",{status}));
  assert.equal(reason(res),expected);
  assert.doesNotMatch(res.headers.get("location"),/never-share-secret/);
 }
});
