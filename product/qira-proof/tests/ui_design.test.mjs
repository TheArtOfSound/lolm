import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {fileURLToPath} from "node:url";
import {dirname,join} from "node:path";
const here=dirname(fileURLToPath(import.meta.url));
const html=readFileSync(join(here,"../index.html"),"utf8");
test("hero explains a customer outcome instead of presenting another security dashboard",()=>{
 assert.match(html,/Know what's running/);
 assert.match(html,/Know what matters/);
 assert.match(html,/Review my GitHub/);
 assert.match(html,/Three steps\. A clearer picture/);
 assert.match(html,/Read-only by design/);
 assert.match(html,/not a certified security service/i);
});
test("all original functional controls remain uniquely addressable",()=>{
 const required=[
 "gitBadge","gitConnect","gitInstall","gitDisconnect","gitStatus","gitMessage",
 "gitPicker","gitInstallation","gitRepository","gitWorkflow","gitAssess","startCard",
 "baselineInput","followupInput","demoButton","demoRecheck","clearFollowup",
 "baselineState","baselineName","followupState","followupName","workTitle",
 "assetsCount","reviewCount","unknownCount","factsCount","findings","deltas",
 "exportButton","verifyButton","verifyInput","digestValue","verificationState","status",
 "jumpDemo","sampleBanner"
 ];
 const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(x=>x[1]);
 for(const id of required)assert.equal(ids.filter(x=>x===id).length,1,"unique id: "+id);
 assert.equal(new Set(ids).size,ids.length,"duplicate IDs must not exist");
});
test("fictional sample cannot be confused with real findings",()=>{
 assert.match(html,/Example report/);
 assert.match(html,/fictional infrastructure/);
 assert.match(html,/Connect GitHub or import your own evidence/);
 assert.match(html,/A cleared indicator is not proof of safety/);
});
test("mobile, keyboard and reduced-motion design gates",()=>{
 assert.match(html,/@media\(max-width:850px\)/);
 assert.match(html,/@media\(max-width:520px\)/);
 assert.match(html,/@media\(prefers-reduced-motion:reduce\)/);
 assert.match(html,/:focus-visible/);
 assert.match(html,/aria-label="Main navigation"/);
 assert.match(html,/role="tabpanel"/);
 assert.match(html,/aria-live="polite"/);
 assert.match(html,/details class="advanced"/);
});
test("no secrets or simulated revenue/success claims are baked into landing",()=>{
 assert.doesNotMatch(html,/GITHUB_APP_CLIENT_SECRET|QIRA_SESSION_KEY|ghu_[A-Za-z0-9]+/);
 assert.doesNotMatch(html,/guaranteed prevention|billions earned|unhackable/i);
});
