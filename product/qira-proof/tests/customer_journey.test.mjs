import test from "node:test";
import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import {build} from "../build.mjs";
import {SCHEMA,proof,verifyProof} from "../core.mjs";
import {renderHumanReport} from "../report.mjs";
if(!globalThis.crypto)globalThis.crypto=webcrypto;

const origin="https://qira.example";
const sessionKey=Buffer.alloc(32,12).toString("base64url");
const providerToken="ghu_"+"X".repeat(64);
const env={
 QIRA_PUBLIC_ORIGIN:origin,
 GITHUB_APP_CLIENT_ID:"Iv1.test-client-only",
 GITHUB_APP_CLIENT_SECRET:"fake-key-only-for-unit-tests",
 QIRA_SESSION_KEY:sessionKey,GITHUB_APP_SLUG:"qira-proof-research"
};
const file=".github/workflows/deploy.yml";
const repository="example-owner/example-repo";
const source=`name: Build
on:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
      - run: echo success
`;
function cookieFrom(response,name){
 const raw=response.headers.get("set-cookie")||"";
 const match=raw.match(new RegExp(name+"=([^;]+)"));
 assert.ok(match,"Missing expected cookie "+name);
 return name+"="+match[1];
}
function request(path,options={}){return new Request(origin+path,options);}
function mockProvider(url,options={}){
 const text=String(url);
 let payload;
 if(text==="https://github.com/login/oauth/access_token"){
  assert.equal(options.method,"POST");
  assert.match(options.body,/code_verifier=/);
  payload={access_token:providerToken,token_type:"bearer",expires_in:3600};
 } else if(text.includes("/user/installations/123/repositories?")){
  payload={total_count:1,repositories:[{full_name:repository,default_branch:"main"}]};
 } else if(text.includes("/user/installations?")){
  payload={total_count:1,installations:[{id:123,account:{login:"example-owner"},repository_selection:"selected"}]};
 } else if(text.includes("/repos/example-owner/example-repo/contents/.github/workflows?")){
  payload=[{type:"file",path:file}];
 } else if(text.includes("/repos/example-owner/example-repo/contents/.github/workflows/deploy.yml?")){
  payload={encoding:"base64",content:Buffer.from(source).toString("base64")};
 } else throw Error("Unexpected provider URL: "+text);
 if(text.startsWith("https://api.github.com/")){
  assert.equal(options.method,"GET");
  assert.equal(options.headers?.authorization,"Bearer "+providerToken);
 }
 return Promise.resolve(new Response(JSON.stringify(payload),{status:200,
  headers:{"content-type":"application/json"}}));
}
test("full compiled Worker journey: OAuth → installation → repo → workflow → review → printable receipt → disconnect",async()=>{
 const original=globalThis.fetch;
 globalThis.fetch=mockProvider;
 try{
  build();
  const worker=(await import("../dist/worker.mjs?journey=full")).default;
  const start=await worker.fetch(request("/connect/github"),env);
  assert.equal(start.status,303);
  const authorization=new URL(start.headers.get("location"));
  assert.equal(authorization.hostname,"github.com");
  assert.equal(authorization.searchParams.get("code_challenge_method"),"S256");
  const state=authorization.searchParams.get("state");
  const pending=cookieFrom(start,"__Host-qira_git_state");
  const callback=await worker.fetch(request("/oauth/github/callback?state="+encodeURIComponent(state)+"&code=fixture123456789",{
   headers:{cookie:pending}
  }),env);
  assert.equal(callback.status,303);
  assert.equal(new URL(callback.headers.get("location")).searchParams.get("github"),"connected");
  const session=cookieFrom(callback,"__Host-qira_git_session");
  assert.ok(!session.includes(providerToken),"Token must be encrypted within the session cookie");
  const status=await worker.fetch(request("/api/github/status",{headers:{cookie:session}}),env);
  const stateDoc=await status.json();
  assert.equal(stateDoc.configured,true);assert.equal(stateDoc.connected,true);
  assert.ok(stateDoc.csrf);
  assert.ok(!JSON.stringify(stateDoc).includes(providerToken));

  const installations=await worker.fetch(request("/api/github/installations",{headers:{cookie:session}}),env);
  const list=await installations.json();
  assert.equal(list.items[0].id,123);
  async function post(path,body){
   return worker.fetch(request(path,{method:"POST",headers:{
    cookie:session,origin,"content-type":"application/json","x-qira-csrf":stateDoc.csrf
   },body:JSON.stringify(body)}),env);
  }
  const repos=await post("/api/github/repos",{installation_id:123});
  assert.equal(repos.status,200);
  assert.equal((await repos.json()).repos[0].name,repository);
  const workflows=await post("/api/github/workflows",{installation_id:123,repo:repository});
  assert.deepEqual((await workflows.json()).workflows,[{path:file}]);
  const review=await post("/api/github/assessment",{installation_id:123,repo:repository,workflow:file});
  assert.equal(review.status,200);
  const {snapshot}=await review.json();
  assert.equal(snapshot.schema,SCHEMA);
  assert.ok(snapshot.facts.some(f=>f.signal==="workflow_unpinned_actions"&&f.value===true));
  assert.ok(snapshot.facts.some(f=>f.signal==="repo_branch_protection_verifiable"&&f.value==="unknown"));
  assert.ok(!JSON.stringify(snapshot).includes(providerToken));
  const receipt=await proof(snapshot);
  assert.equal(await verifyProof(receipt),true);
  const html=await renderHumanReport(receipt);
  assert.match(html,/Third-party CI actions use mutable version references/);
  assert.match(html,/Branch protection could not be verified/);
  assert.ok(!html.includes(providerToken));
  assert.ok(html.includes(receipt.sha256));
  const reportModule=await worker.fetch(request("/report.mjs"),env);
  assert.equal(reportModule.status,200);
  assert.match(await reportModule.text(),/renderHumanReport/);

  const csrfDenied=await worker.fetch(request("/api/github/disconnect",{
   method:"POST",headers:{cookie:session,origin,"content-type":"application/json"},body:"{}"
  }),env);
  assert.equal(csrfDenied.status,403);
  const disconnected=await post("/api/github/disconnect",{});
  assert.equal(disconnected.status,200);
  assert.equal((await disconnected.json()).server_side_token_revoked,false);
  assert.match(disconnected.headers.get("set-cookie"),/__Host-qira_git_session=;/);
  const oldCookieAfterDisconnect=await worker.fetch(request("/api/github/status",{
   headers:{cookie:disconnected.headers.get("set-cookie")}
  }),env);
  assert.equal((await oldCookieAfterDisconnect.json()).connected,false);
  // Do not claim that a stolen former cookie cannot be replayed: there is
  // no server-side token revocation in this stateless pilot.
 }finally{globalThis.fetch=original;}
});
