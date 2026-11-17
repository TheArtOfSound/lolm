import test from "node:test";
import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import operator,{verifyOperator} from "../commercial/operator_desk.mjs";
if(!globalThis.crypto)globalThis.crypto=webcrypto;
const owner="operator@example.invalid",aud="c".repeat(64),issuer="https://autohustle.cloudflareaccess.com";
const url="https://ops.proof.imagineqira.com/";
const env={QIRA_PROOF_OPS_AUD:aud,QIRA_PROOF_OPS_EMAIL:owner};
const enc=value=>Buffer.from(typeof value==="string"||value instanceof Uint8Array?value:JSON.stringify(value)).toString("base64url");
const req=(url,token)=>new Request(url,{headers:token?{"Cf-Access-Jwt-Assertion":token}:{}});
async function mint(override={}){
 const keys=await crypto.subtle.generateKey({name:"RSASSA-PKCS1-v1_5",modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:"SHA-256"},true,["sign","verify"]);
 const publicJwk={...(await crypto.subtle.exportKey("jwk",keys.publicKey)),kid:"qira-test-key",alg:"RS256",use:"sig"};
 const time=Math.floor(Date.now()/1000);
 const header={alg:"RS256",typ:"JWT",kid:"qira-test-key"};
 const claims={iss:issuer,aud:[aud],email:owner,sub:"access_operator_1234567890",iat:time-10,exp:time+3600,...override};
 const payload=enc(header)+"."+enc(claims);
 const signature=enc(Buffer.from(await crypto.subtle.sign("RSASSA-PKCS1-v1_5",keys.privateKey,new TextEncoder().encode(payload))));
 const jwt=payload+"."+signature;
 return {jwt,publicJwk,certs:async()=>({ok:true,status:200,json:async()=>({keys:[publicJwk]})})};
}
test("cryptographically verifies valid Access JWT audience, issuer, operator email, time and RSA signature",async()=>{
 const x=await mint();
 const identity=await verifyOperator(req(url,x.jwt),env,x.certs);
 assert.equal(identity.email,owner);
 assert.equal(identity.sub,"access_operator_1234567890");
});
test("rejects wrong audience, different email, expired and future-dated Access tokens",async()=>{
 for(const override of [
  {aud:["1".repeat(64)]},{email:"attacker@example.invalid"},
  {iss:"https://other.cloudflareaccess.com"},
  {exp:Math.floor(Date.now()/1000)-1},
  {iat:Math.floor(Date.now()/1000)+300},
  {sub:"short"}
 ]){
  const x=await mint(override);
  assert.equal(await verifyOperator(req(url,x.jwt),env,x.certs),null,JSON.stringify(override));
 }
});
test("rejects forged Access signatures and missing or wrong JWT verification keys",async()=>{
 const x=await mint(),y=await mint();
 assert.equal(await verifyOperator(req(url,x.jwt),env,y.certs),null);
 const parts=x.jwt.split(".");
 parts[1]=enc({...JSON.parse(Buffer.from(parts[1],"base64url").toString("utf8")),email:"attacker@example.invalid"});
 assert.equal(await verifyOperator(req(url,parts.join(".")),env,x.certs),null);
 assert.equal(await verifyOperator(req(url,x.jwt),env,async()=>({ok:false,status:500})),null);
});
test("refuses direct workers.dev host bypass, malformed headers and missing configuration",async()=>{
 const x=await mint();
 assert.equal(await verifyOperator(req("https://qira-proof-ops.workers.dev/",x.jwt),env,x.certs),null);
 assert.equal(await verifyOperator(req(url),env,x.certs),null);
 assert.equal(await verifyOperator(req(url,x.jwt),{},x.certs),null);
 assert.equal((await operator.fetch(req(url),{})).status,401);
});
test("rejects algorithm-none JWT even when a plausible Access identity is encoded",async()=>{
 const t=Math.floor(Date.now()/1000);
 const jwt=enc({alg:"none",kid:"qira-test-key"})+"."+enc({iss:issuer,aud:[aud],email:owner,sub:"access_operator_1234567890",iat:t-3,exp:t+1200})+".sig";
 assert.equal(await verifyOperator(req(url,jwt),env,async()=>{throw Error("do not fetch certs")}),null);
});
