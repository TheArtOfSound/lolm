import test from "node:test";
import assert from "node:assert/strict";
import worker from "../commercial/landing.mjs";
const origin="https://proof.imagineqira.com";
const request=(path="/",options={})=>new Request(origin+path,options);
test("commercial page is branded and commercial health is explicit",async()=>{
 const page=await worker.fetch(request());
 assert.equal(page.status,200);
 const html=await page.text();
 assert.match(html,/GitHub Actions Security Configuration Review \| Qira Proof/);
 assert.match(html,/A tool in the ImagineQira ecosystem/i);
 assert.match(html,/Founding workflow review/i);
 assert.match(html,/\$299/);
 assert.match(html,/https:\/\/imagineqira.com/);
 assert.match(html,/Try the read-only preview/);
 const health=await worker.fetch(request("/health"));
 assert.deepEqual(await health.json(),{status:"ready",product:"qira-proof-commercial",checkout_configured:false});
});
test("checkout is withheld when the merchant has not been selected",async()=>{
 const response=await worker.fetch(request());
 const html=await response.text();
 assert.match(html,/Request a secure checkout/);
 assert.match(html,/mailto:bryanleonard@imagineqira.com/);
 assert.match(html,/does not charge you/);
 assert.doesNotMatch(html,/href="https:\/\/buy\.stripe\.com\//);
});
test("only Stripe-hosted HTTPS checkout links can activate purchase",async()=>{
 const target="https://buy.stripe.com/example123";
 const r=await worker.fetch(request(),{QIRA_PROOF_CHECKOUT_URL:target});
 const text=await r.text();
 assert.match(text,/Buy founding review/);
 assert.match(text,/href="https:\/\/buy\.stripe\.com\/example123"/);
 const h=await worker.fetch(request("/health"),{QIRA_PROOF_CHECKOUT_URL:target});
 assert.equal((await h.json()).checkout_configured,true);
});
test("untrusted checkout URLs never become purchase links",async()=>{
 for(const url of ["https://evil.example/pay","http://buy.stripe.com/example",
  "https://buy.stripe.com.attacker.example/link",
  "javascript:alert(1)","https://user:pass@buy.stripe.com/a",
  "https://buy.stripe.com/link#evil"]){
  const resp=await worker.fetch(request(),{QIRA_PROOF_CHECKOUT_URL:url});
  const html=await resp.text();
  assert.match(html,/Request a secure checkout/);
  assert.doesNotMatch(html,/Buy founding review →/);
 }
});
test("privacy and terms pages include clear scope limitations",async()=>{
 const privacy=await worker.fetch(request("/privacy"));
 const terms=await worker.fetch(request("/terms"));
 const p=await privacy.text(),t=await terms.text();
 assert.equal(privacy.status,200);
 assert.equal(terms.status,200);
 assert.match(p,/does not use tracking cookies/);
 assert.match(t,/not an incident-response service/);
 assert.match(t,/up to 20 GitHub Actions workflow files/);
 assert.match(t,/bryanleonard@imagineqira.com/);
});
test("routing protects unsupported methods and unknown pages",async()=>{
 const post=await worker.fetch(request("/",{method:"POST",body:"X"}));
 assert.equal(post.status,405);
 const unknown=await worker.fetch(request("/does-not-exist"));
 assert.equal(unknown.status,404);
 const head=await worker.fetch(request("/",{method:"HEAD"}));
 assert.equal(head.status,200);
 assert.equal(await head.text(),"");
});
test("commercial worker has no auth cookies or client-side data transmission",async()=>{
 const r=await worker.fetch(request());
 const html=await r.text();
 assert.equal(r.headers.get("set-cookie"),null);
 assert.match(r.headers.get("content-security-policy"),/connect-src 'none'/);
 assert.doesNotMatch(html,/fetch\s*\(/);
 assert.doesNotMatch(html,/<form\b/);
 assert.doesNotMatch(html,/<script src=/);
});

test("post-payment handoff is available without claiming the URL proves a payment",async()=>{
 const response=await worker.fetch(request("/start-review"));
 assert.equal(response.status,200);
 const html=await response.text();
 assert.match(html,/Start your Qira Proof review/);
 assert.match(html,/does not verify payment or grant an entitlement/);
 assert.match(html,/Trend Stripe/);
 assert.match(html,/Never email passwords/);
 assert.match(html,/up to 20 GitHub Actions workflow files/);
 assert.match(html,/mailto:bryanleonard@imagineqira.com/);
 assert.doesNotMatch(html,/session_id=/);
});

test("pending checkout identifies Trend merchant clearly",async()=>{const html=await (await worker.fetch(request())).text();assert.match(html,/Trend is selected as Qira Proof/);assert.doesNotMatch(html,/awaits confirmation of the Qira merchant/);});
