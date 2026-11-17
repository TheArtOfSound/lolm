// Qira Proof technical field notes. Factual documentation, not programmatic SEO pages.
// Every route provides an individual purpose, source references, scope and examples.
export const GUIDES=[
 {slug:"/methodology",title:"How the Qira Proof workflow review works",desc:"Scope, evidence handling, human adjudication, scanner limitations and deliverables in the Qira Proof GitHub Actions configuration review.",kind:"method",updated:"2026-11-16"},
 {slug:"/guides",title:"GitHub Actions security field notes",desc:"Practical GitHub Actions guides covering token permissions, action dependency provenance, SSH host-key trust and release controls.",kind:"index",updated:"2026-11-16"},
 {slug:"/guides/github-actions-permissions",title:"Review GitHub Actions GITHUB_TOKEN permissions",desc:"How to inspect and reduce GitHub Actions GITHUB_TOKEN write permissions, including job scopes and the special id-token: write permission.",kind:"article",updated:"2026-11-16"},
 {slug:"/guides/github-actions-dependency-pinning",title:"GitHub Actions pinning: tags, SHAs and lockfiles",desc:"A practical review of GitHub Actions action reference pinning, SHA digests, dependency lockfiles and supply-chain provenance limitations.",kind:"article",updated:"2026-11-16"},
 {slug:"/guides/ssh-host-key-verification",title:"Verify SSH host keys in GitHub Actions deployments",desc:"Why ssh-keyscan alone is not independent host authentication and how to review a secure known_hosts trust bootstrap in CI.",kind:"article",updated:"2026-11-16"},
 {slug:"/guides/release-gate-failure-modes",title:"Fail-closed CI release gates: audit, merge and deploy",desc:"How to find fail-open security checks and publish paths that are not bound to verified merges, with a real pinned LOLM example.",kind:"article",updated:"2026-11-16"}
];
export const REFERENCE_LINKS={
 syntax:"https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax",
 security:"https://docs.github.com/en/actions/reference/security/secure-use",
 token:"https://docs.github.com/en/actions/concepts/security/github_token",
 ssh:"https://docs.github.com/en/authentication/connecting-to-github-with-ssh/testing-your-ssh-connection"
};
const e=v=>String(v).replace(/[&<>"']/g,x=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[x]));
const link=(href,label,ext=false)=>'<a href="'+e(href)+'"'+(ext?' target="_blank" rel="noopener noreferrer"':'')+'>'+e(label)+'</a>';
const paras=items=>items.map(t=>"<p>"+t+"</p>").join("");
const section=(heading,body,id)=>'<section class="field-section" id="'+e(id||heading.toLowerCase().replace(/[^a-z0-9]+/g,"-"))+'"><h2>'+e(heading)+'</h2>'+body+'</section>';
const code=(s)=>'<pre class="field-code"><code>'+e(s)+'</code></pre>';
const bullet=(items)=>'<ul class="field-list">'+items.map(x=>'<li>'+x+'</li>').join("")+'</ul>';
const resources=()=>'<div class="field-back"><a href="/guides">Browse all field notes</a> <a href="/case-study">Verified public source case</a> <a href="/#pricing">Request a founding review</a></div>';
function wrapper(label,title,dek,body){
 const sections=[...body.matchAll(/<section class="field-section" id="([^"]+)"><h2>([^<]+)<\/h2>/g)];
 const toc=sections.length>1?'<nav class="field-toc" aria-label="On this page"><strong>On this page</strong>'+sections.map(m=>'<a href="#'+e(m[1])+'">'+m[2]+'</a>').join("")+'</nav>':"";
 return '<div class="field-page"><header class="field-hero"><div class="shell"><p class="field-kicker">'+e(label)+'</p><h1>'+e(title)+'</h1><p class="field-intro">'+e(dek)+'</p></div></header><div class="shell field-container">'+toc+body+resources()+'</div></div>';
}
function related(items){return '<aside class="field-related" aria-label="Read next"><h2>Related reading</h2><div>'+items.map(x=>link(x[0],x[1])).join("")+'</div></aside>';}
function methodology(){
 return wrapper("Qira Proof / review protocol","What we check—and what we do not","The boundaries, method and evidence of the founding GitHub Actions configuration review.",
 section("Scope and authorization",paras([
 "The founding review covers <strong>one customer-authorized GitHub repository and up to 20 GitHub Actions workflow files</strong>. Repository access is opt-in and read-only where available. A customer should never email GitHub tokens, passwords, private keys or cloud credentials to us.",
 "The subject is workflow configuration: action references, declared permissions, selected triggers and text patterns related to trust. It is not an assessment of application source-code correctness, infrastructure penetration testing, runtime account privileges, or all possible supply-chain exposures.",
 "Changes after the collected snapshot may alter the results. A deliverable should identify the repository, commit or revision, coverage and collection date. Findings not backed by a source location are not acceptable evidence."
 ])+"<p><strong>Current paid handoff:</strong> Stripe's hosted checkout is followed by manual receipt verification, customer identity confirmation, scoped repository authorization, and human delivery. The website return page does not grant access automatically.</p>","scope")
 +section("How an observation becomes a finding",bullet([
 "<strong>Collect bounded evidence.</strong> Inspect the authorized workflow files without downloading unrelated customer content.",
 "<strong>Run the bounded workflow pattern checks.</strong> They identify selected text and YAML structures, not the full effective runtime context.",
 "<strong>Corroborate against source.</strong> A reviewer checks the line, its YAML placement, and whether the relevant step or job can actually execute.",
 "<strong>Document uncertainty.</strong> Separate the directly observed configuration from possible outcomes, conditional branches and unexamined controls.",
 "<strong>Deliver prioritized next steps.</strong> Explain which checks the engineering team should perform and what must be verified before claiming remediation."
 ])+"<p>For example, an action referenced by a version tag can be reported as a mutable reference; the source line does not prove that the action is malicious. A declared <code>id-token: write</code> scope can be reported as a capability request; it does not prove an external cloud role was assumed.</p>","process")
 +section("What a customer receives",bullet([
 "Source-linked findings with file and line references, not just a severity badge.",
 "A description of what was directly observed and what remains unknown.",
 "A prioritized written set of review or remediation recommendations.",
 "A coverage and limitations statement for the selected snapshot.",
 "A machine-readable JSON integrity receipt for the reported evidence."
 ])+"<p>Delivery timing and repository scope are confirmed after purchase. The $299 founding product is a <strong>one-time human-reviewed service</strong>, not an automated monitoring subscription or a security certification.</p>","deliverables")
 +section("Where the scanner stops",paras([
 "The research scanner has a deliberately bounded parser. It does not perform full YAML semantic evaluation for all anchors, aliases, inline expressions or unusual syntax. Unsupported patterns should be marked uncertain rather than converted into a confident negative.",
 "A workflow file is not a faithful record of every security control that applies at runtime. Effective permissions can be affected by repository and organization policy, event context, third-party infrastructure, environment protections and credential configuration."
 ])+"<p>Our "+link("/case-study","pinned LOLM source review")+" demonstrates three source-corroborated workflow observations. Two additional Python control-flow defects on that page were found manually, <strong>not</strong> by the workflow scanner. The study is first-party and not independently certified.</p>","limits")
 +section("Evidence standard and conflicts",paras([
 "A reviewer must be able to reconstruct the claim from a stable source line. When the source contradicts a generated explanation, the explanation must change. Where uncertainty cannot be resolved without access not granted by the customer, we label the limit.",
 "The strongest next evidence is independently adjudicated representative workflows and a completed paid order-to-deliverable pilot. We do not claim either has already been completed."
 ])+related([["/case-study","Read the real pinned workflow case"],["/sample-report","Explore the explicitly synthetic report specimen"],["/guides","Browse technical field notes"]]),"evidence"));
}
function permissions(){
 return wrapper("Field note / access control","GitHub Actions permissions: review the real scope","The difference between YAML permission declarations, effective token authority and the minimum access a job needs.",
 section("Start with the distinction",paras([
 "Every GitHub Actions job may receive a <code>GITHUB_TOKEN</code> for the repository. The <code>permissions</code> key controls its requested scopes. A top-level declaration can apply across jobs; a job-level declaration allows narrower privileges for a specific task. It is not enough to locate the word <code>write</code> and announce a breach.",
 "The practical question is: <em>which job must perform which operation using which identity?</em> A test job that only downloads source usually needs much less authority than a release job that creates a tag, opens a PR or publishes provenance."
 ]),"distinction")
 +section("A baseline and a privileged exception",code("permissions:\n  contents: read\n\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@<reviewed-revision>\n      - run: npm test\n\n  publish:\n    permissions:\n      contents: read\n      id-token: write\n    runs-on: ubuntu-latest\n    # Only enable the scopes and trust path this job needs.")
 +"<p>This is an <strong>illustrative pattern</strong>, not copy-and-paste deployable YAML; replace placeholder action revisions with actual trusted references and verify the permissions required by your publishing workflow. GitHub notes that explicitly specifying some permissions generally sets unspecified scopes to <code>none</code>.</p>","example")
 +section("Four reviews worth making",bullet([
 "Locate every workflow-level and job-level <code>permissions</code> mapping; record which event invokes the job.",
 "Identify which step actually needs <code>contents: write</code>, <code>issues: write</code>, <code>pull-requests: write</code> or another elevated scope. Move privileges to a narrower job where feasible.",
 "Treat <code>id-token: write</code> separately: it enables eligible jobs to request an OIDC token, but does not independently confirm that any cloud trust policy accepts it.",
 "Inspect triggers, fork behavior, reusable workflows and organizational restrictions before making claims about effective authorization."
 ]),"checks")
 +section("Example: a documented real repository",paras([
 "At a pinned historical LOLM commit, the daily release workflow declares <code>contents</code>, <code>pull-requests</code>, <code>issues</code> and <code>id-token</code> with <code>write</code> access at the workflow level. Qira Proof's bounded scanner flags the declaration. A human reading the file can corroborate it directly.",
 "That establishes the declared scopes, <strong>not</strong> an exploit, leaked token or proof that every job actually exercised those privileges. The next useful work is mapping each write scope to the operations that genuinely require it."
 ])+link("/case-study","Inspect the pinned LOLM case study"),"example-repository")
 +section("Primary reference",paras(["GitHub describes permissions and job inheritance in "+link(REFERENCE_LINKS.syntax,"Workflow syntax",true)+" and the per-job token model in "+link(REFERENCE_LINKS.token,"GITHUB_TOKEN",true)+". Read the current platform guidance before modifying a sensitive release workflow."])+related([["/guides/github-actions-dependency-pinning","Action pinning and provenance"],["/guides/release-gate-failure-modes","Fail-closed release gates"]]),"sources"));
}
function pinning(){
 return wrapper("Field note / dependency provenance","GitHub Actions pinning: what a tag does not prove","A useful assessment of mutable action references, trusted revisions, dependency lockfiles and the limits of a single YAML line.",
 section("What a version tag means",paras([
 "A reference such as <code>actions/checkout@v7</code> identifies an action by its tag. Tags are convenient for version management, but a tag is not the same assurance as a reviewed immutable revision. A pinned full commit SHA identifies a specific Git object.",
 "Qira Proof identifies selected executable <code>uses:</code> references that lack a 40-character commit digest. That observation signals an action dependency deserving provenance review, not a proven supply-chain attack."
 ]),"tags")
 +section("Which protection to choose",bullet([
 "<strong>Workflow dependency lockfiles:</strong> GitHub's current secure-use guidance identifies dependency lockfiles as the stronger protection where supported, because they also record transitive dependencies and verify source identity. Evaluate current availability and policy fit.",
 "<strong>Full commit SHA:</strong> Where no lockfile is available, review the action publisher and a full-length commit SHA from its actual source repository. Track updates intentionally.",
 "<strong>Trusted tag:</strong> Where you rely on a tag, document why its maintainer and update path are trusted. A version label alone cannot establish the revision that was executed on a past run."
 ]),"options")
 +section("Review without breaking your pipelines",paras([
 "Inventory external action dependencies across relevant workflows and reusable workflows. For each, record the purpose, source repository, current reference, intended update process, and whether an organization policy enforces digest pinning.",
 "Before replacing a tag, confirm the commit belongs to the intended repository and represents a supported version. Avoid substituting unverified hashes from an unrelated fork. Then run the workflow in a controlled environment and document the rollout.",
 "An action reference found inside a comment, an environment value or ordinary prose is not proof that the action executes. Correct YAML placement matters. The scanner's bounded parser must be checked when the syntax is ambiguous."
 ]),"workflow")
 +section("What we observed",paras([
 "The public LOLM daily release workflow at a pinned commit includes <code>actions/checkout@v7</code>, <code>actions/setup-python@v7</code>, and <code>actions/setup-node@v7</code>. Each is a version-tagged reference rather than a full digest.",
 "That does not demonstrate any compromise. It gives an engineer a reproducible inventory and a concrete change to evaluate."
 ])+link("/case-study","See exact immutable source lines"),"real-case")
 +section("Primary reference",paras(["Consult GitHub's "+link(REFERENCE_LINKS.security,"secure use reference",true)+" for the current preference ordering of dependency lockfiles, SHA pinning and trusted tags, and GitHub's "+link(REFERENCE_LINKS.syntax,"workflow syntax",true)+" for executable step context."])+related([["/guides/github-actions-permissions","GITHUB_TOKEN permissions"],["/methodology","Qira Proof review methodology"]]),"sources"));
}
function ssh(){
 return wrapper("Field note / deployment trust","SSH host-key verification in CI deployments","Separate key discovery from key authentication before a deployment trusts a remote server.",
 section("Why ssh-keyscan is not a complete trust check",paras([
 "<code>ssh-keyscan</code> asks a remote endpoint for its public SSH host keys. It is useful for collecting a key, but collection over the same network path does not independently establish that the key belongs to the intended host.",
 "A workflow that appends that result directly to <code>~/.ssh/known_hosts</code> may accept whatever key was observed during bootstrap. Whether that produces an exploitable failure depends on network conditions, prior verification and other controls; a YAML line alone cannot establish a man-in-the-middle attack."
 ]),"why")
 +section("A more defensible bootstrap",bullet([
 "Obtain the expected SSH host public key or fingerprint through an authenticated, independent operator or provider channel.",
 "Keep that expected identity in a controlled configuration location rather than blindly trusting the value returned by the first deployment-time connection.",
 "Compare the received host key with the expected key or prepopulate a verified known_hosts entry; stop deployment if the identity differs.",
 "Protect the deploy credential separately and review the user/host mapping and whether deployment is restricted to trusted branches or environments."
 ]),"bootstrap")
 +section("A failure mode worth examining",code("mkdir -p ~/.ssh\n# This discovers a key, but does not independently authenticate it:\nssh-keyscan -H \"$HOST\" >> ~/.ssh/known_hosts\n\n# Better pattern: provision a reviewed, independently verified\n# known_hosts entry through your controlled deployment configuration.")
 +"<p>Do not replace a real host fingerprint with a placeholder and treat it as a working deployment configuration. A valid approved key is environment-specific and needs a verifiable source.</p>","example")
 +section("Pinned source evidence",paras([
 "The historical LOLM daily workflow conditionally creates an SSH key file and executes <code>ssh-keyscan</code>, appending its output to <code>known_hosts</code> with a <code>|| true</code> fallback.",
 "The conditional branch matters: the snippet does not prove it ran on any particular deployment. The real review records the source line and asks whether a separately verified key was available."
 ])+link("/case-study","Read the workflow's pinned source evidence"),"case")
 +section("Primary reference",paras(["GitHub's "+link(REFERENCE_LINKS.ssh,"SSH connection test guidance",true)+" illustrates comparing observed host-key fingerprints with authenticated published fingerprints before accepting a host."])+related([["/guides/release-gate-failure-modes","Release gates and fail-closed behavior"],["/methodology","Our review methodology"]]),"sources"));
}
function releaseGates(){
 return wrapper("Field note / release integrity","Fail-closed release gates: audit, merge and deploy","A release gate is only meaningful when malformed evidence and failed prerequisites stop later high-impact operations.",
 section("The difference between 'clean' and 'unknown'",paras([
 "Security audits can return structured findings, exit nonzero, time out or fail to produce a usable report. Those outcomes are not interchangeable. A gate that catches any JSON parse failure and substitutes zero high-severity advisories may turn 'could not inspect' into 'passed'.",
 "To fail closed, require a well-formed supported audit result, explicit vulnerability counts, and a documented policy for nonzero exits. Return a separately labeled unavailable or invalid state when the report cannot be trusted."
 ]),"audit")
 +section("A minimal acceptance matrix",bullet([
 "<strong>Valid no high/critical findings:</strong> pass only when the output schema is complete and the tool execution is understood.",
 "<strong>High or critical findings:</strong> block or follow an explicit controlled exception policy.",
 "<strong>Malformed JSON, unexpected schema or failed audit invocation:</strong> block and label the result 'unavailable' rather than clean.",
 "<strong>Missing required lockfile or unavailable dependency graph:</strong> block, or use a separately justified equivalent control without claiming the original audit passed."
 ]),"matrix")
 +section("Publishing is a dependency chain",paras([
 "A successful test step alone does not establish that the intended commit was merged, that the expected branch protection checks ran, or that the artifact being published matches that reviewed commit.",
 "A release orchestrator should verify each git command result, the intended PR/base/commit, the actual merge result, and the immutable identity of the publish or deploy artifact. A skipped or failed merge must not be treated as an optional note if publishing depends on it.",
 "Avoid privileged administrative merge flags in automated paths unless a narrowly documented policy genuinely requires them. Prefer standard checks, reviews and protected-branch rules."
 ]),"publish")
 +section("Public LOLM example",paras([
 "At a pinned LOLM source revision, the Python release orchestrator catches an <code>npm audit</code> JSON parsing exception and sets the high/critical count to zero. Its merge helper requests <code>--admin</code>, while a later publishing path can be entered without checking <code>merged.ok</code>.",
 "These are <strong>manual Python control-flow findings</strong>, not outputs of Qira Proof's workflow-pattern scanner. No actual unsafe publish, bypass of branch protection or production exploit was demonstrated. We documented the separate remediation as public GitHub issue #72."
 ])+link("/case-study","Read the source-backed example")+" · "+link("https://github.com/TheArtOfSound/lolm/issues/72","Review public issue #72",true),"case")
 +section("Verification tests that matter",bullet([
 "Test invalid JSON and missing metadata independently of genuinely zero results.",
 "Inject an audit-process failure and assert that publish is not invoked.",
 "Inject failed git checkout, push or PR merge operations and assert that every later publish/deploy call remains blocked.",
 "Test a successful run against the exact merged commit, with an auditable receipt recording what actually happened."
 ])+related([["/guides/github-actions-permissions","GITHUB_TOKEN permission boundaries"],["/case-study","Historical source review"],["/methodology","Founding service methodology"]]),"tests"));
}
export function renderGuide(path){
 if(path==="/methodology")return methodology();
 if(path==="/guides/github-actions-permissions")return permissions();
 if(path==="/guides/github-actions-dependency-pinning")return pinning();
 if(path==="/guides/ssh-host-key-verification")return ssh();
 if(path==="/guides/release-gate-failure-modes")return releaseGates();
 if(path==="/guides"){
  const articles=GUIDES.filter(x=>x.kind==="article");
  return wrapper("Qira Proof / field notes","GitHub Actions security field notes","Focused engineering references on configurations we can actually observe, how to review them, and what the evidence does not prove.",
   '<section class="field-section"><h2>Read by configuration concern</h2><div class="field-cards">'+articles.map((x,i)=>'<article><span>NOTE 0'+(i+1)+'</span><h3>'+link(x.slug,x.title)+'</h3><p>'+e(x.desc)+'</p><a href="'+e(x.slug)+'">Read note →</a></article>').join("")+'</div></section>'
   +section("The review behind the examples",paras([
    "The guides explain the inspection principles used in Qira Proof's bounded configuration assessment. They are not intended as proof that any particular repository is vulnerable.",
    "Our "+link("/case-study","public LOLM case study")+" includes direct line citations and a clear distinction between scanner-corroborated YAML and manually reviewed Python control flow. The "+link("/methodology","methodology page")+" explains the paid-review boundaries."
   ]),"about"));
 }
 return null;
}
