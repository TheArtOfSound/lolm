/**
 * Selected real-source case study. This is a first-party Qira Proof validation
 * exercise on a public repository, NOT an independently commissioned audit.
 * Sources are immutable GitHub blob views pinned to a single commit.
 * The scanner covers YAML configuration patterns only; Python control-flow
 * observations below were manually corroborated and are NOT scanner output.
 */
export const REAL_CASE=Object.freeze({
 repository:"TheArtOfSound/lolm",
 commit:"f9700d2e661640da4a8d0cf2bb9c046d77f8a06b",
 workflow:".github/workflows/daily-lolm-learned-update.yml",
 workflowBlob:"631de3d0fe3ae22bfdf6881a15349a85ef6629ed",
 control:"scripts/agent_daily_update.py",
 controlBlob:"07f2905691928cce87ba7a751b7889e6813cd7c8",
 coverage:"One workflow file and its release-control Python orchestrator; not a complete repository or runtime security audit.",
 methodology:"Qira Proof's workflow pattern output was compared against direct reading of pinned YAML lines. The supplementary Python notes were manually reviewed outside the workflow scanner.",
 externalReview:false,
 observations:[
  {
   id:"QP-REAL-01",mode:"scanner corroborated",label:"Workflow permission scope",
   title:"Write permissions declared at workflow level",
   observation:"The workflow declares contents, pull-requests, issues, and id-token with write access.",
   excerpt:"contents: write · pull-requests: write · issues: write · id-token: write",
   source:[{path:".github/workflows/daily-lolm-learned-update.yml",start:18,end:22}],
   interpretation:"These are declared token scopes. Effective privileges depend on the triggering context, repository configuration and job execution.",
   next:"Review each job's actual minimum permission needs and scope write grants to the necessary jobs.",
   notProven:"No privilege abuse, compromise or effective runtime authorization was demonstrated."
  },
  {
   id:"QP-REAL-02",mode:"scanner corroborated",label:"Third-party action reference",
   title:"Actions are referenced by version tags",
   observation:"The workflow uses actions/checkout@v7, actions/setup-python@v7 and actions/setup-node@v7 rather than full 40-character commit digests.",
   excerpt:"actions/checkout@v7 · actions/setup-python@v7 · actions/setup-node@v7",
   source:[{path:".github/workflows/daily-lolm-learned-update.yml",start:30,end:40}],
   interpretation:"A tag is a movable reference. This is a provenance and supply-chain review prompt, not a claim that any referenced action is malicious.",
   next:"Identify trusted resolved revisions and evaluate pinning to reviewed immutable commit digests.",
   notProven:"No malicious action, tag movement or exploit was established."
  },
  {
   id:"QP-REAL-03",mode:"scanner corroborated",label:"SSH host-key trust",
   title:"SSH host keys are collected at runtime",
   observation:"When the optional deploy-key branch runs, ssh-keyscan output is appended to known_hosts, with a command-level || true fallback.",
   excerpt:"ssh-keyscan -H ... >> ~/.ssh/known_hosts ... || true",
   source:[{path:".github/workflows/daily-lolm-learned-update.yml",start:53,end:65}],
   interpretation:"Trust-on-first-use key discovery may need an independently verified expected host fingerprint. The branch is conditional; this is a source observation.",
   next:"Verify the expected host-key fingerprint out of band and fail closed when host identity cannot be established.",
   notProven:"No network interception, incorrect host key or production exploit was observed."
  }
 ],
 companion:[
  {
   id:"QP-MANUAL-01",mode:"manual source review only",label:"Audit gate control flow",
   title:"An npm audit parsing failure can be counted as zero findings",
   observation:"The security gate catches a parsing exception and assigns high = 0, then evaluates high == 0 as a passing result.",
   excerpt:"except Exception: ... high = 0 ... high == 0",
   source:[{path:"scripts/agent_daily_update.py",start:147,end:162}],
   interpretation:"Malformed or unusable audit output can be treated as a clean result. This is a confirmed source-level fail-open path, not evidence that an unsafe release occurred.",
   next:"Require valid audit results and fail closed for subprocess or schema errors. Add malformed-output and nonzero-exit tests.",
   notProven:"No actual vulnerable artifact was shown to pass through the gate."
  },
  {
   id:"QP-MANUAL-02",mode:"manual source review only",label:"Publish / merge control flow",
   title:"Release operations do not require a confirmed successful merge",
   observation:"The script requests a merge with --admin, assigns its result to merged, but can enter the separate publish and deploy paths without checking merged.ok first.",
   excerpt:"gh pr merge ... --admin · merged = do_merge(...) · if pg.passed:",
   source:[
    {path:"scripts/agent_daily_update.py",start:172,end:184},
    {path:"scripts/agent_daily_update.py",start:277,end:316}
   ],
   interpretation:"Publishing and deployment remain conditional on other gates and credentials. The missing merge-success dependency and administrative bypass request are control-flow concerns.",
   next:"Remove --admin, require a verified merge of the intended commit and stop on failed git operations before publishing.",
   notProven:"No bypass of branch protection or unmerged production release was demonstrated."
  }
 ]
});
const escapeText=v=>String(v).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
export const sourceUrl=(file,start,end)=>"https://github.com/TheArtOfSound/lolm/blob/"+REAL_CASE.commit+"/"+file+"#L"+start+"-L"+end;
function sourceLinks(entry){
 return entry.source.map(s=>'<a href="'+escapeText(sourceUrl(s.path,s.start,s.end))+'" target="_blank" rel="noopener noreferrer">'+escapeText(s.path)+" · lines "+s.start+"–"+s.end+'</a>').join(" ");
}
function record(entry){
 return '<article class="rc-record" id="'+escapeText(entry.id)+'" aria-labelledby="'+escapeText(entry.id)+'-title">'
  +'<div class="rc-record-meta"><span>'+escapeText(entry.id)+'</span><span>'+escapeText(entry.mode)+'</span></div>'
  +'<h3 id="'+escapeText(entry.id)+'-title">'+escapeText(entry.title)+'</h3>'
  +'<p class="rc-lead">'+escapeText(entry.observation)+'</p>'
  +'<div class="rc-pairs">'
  +'<div><h4>Source evidence</h4><p class="rc-evidence">'+escapeText(entry.excerpt)+'</p><div class="rc-sources">'+sourceLinks(entry)+'</div></div>'
  +'<div><h4>What it means</h4><p>'+escapeText(entry.interpretation)+'</p></div>'
  +'<div><h4>Next review step</h4><p>'+escapeText(entry.next)+'</p></div>'
  +'<div><h4>Not established</h4><p>'+escapeText(entry.notProven)+'</p></div>'
  +'</div></article>';
}
export function renderRealCaseStudy(){
 const r=REAL_CASE;
 return '<div class="rc-page">'
 +'<section class="rc-hero"><div class="shell"><p class="rc-eyebrow">Public repository / pinned source review</p>'
 +'<h1>What we found in a real release workflow.</h1>'
 +'<p class="rc-intro">A selected source review of the public LOLM repository. Three workflow configuration observations were reproduced by Qira Proof and checked against pinned lines. Two additional release-control observations came from manual source review, outside the scanner&#39;s scope.</p>'
 +'<div class="rc-meta"><div><span>Repository</span><strong><a href="https://github.com/TheArtOfSound/lolm" rel="noopener noreferrer">TheArtOfSound/lolm</a></strong></div>'
 +'<div><span>Snapshot commit</span><strong><a href="https://github.com/TheArtOfSound/lolm/commit/'+r.commit+'" rel="noopener noreferrer"><code>'+r.commit.slice(0,12)+'</code></a></strong></div>'
 +'<div><span>Coverage</span><strong>1 workflow + 1 supporting script</strong></div>'
 +'<div><span>Verification</span><strong>First-party source cross-check</strong></div></div></div></section>'
 +'<div class="shell rc-content"><aside class="rc-note" aria-label="What this review does and does not establish">'
 +'<h2>A real source review. Not a certification.</h2>'
 +'<p>These observations refer to the repository&#39;s state at the commit above. They are not current-state findings, a customer assessment, a live exploitation test, or an independent third-party audit. No secrets, cloud credentials, branch protections or actual production release outcomes were verified.</p>'
 +'<p>We compared the workflow scanner&#39;s flags with the exact YAML lines. The Python findings were assessed separately by reading source control flow; the scanner does not claim to find them.</p>'
 +'<p>Remediation is tracked in <a href="https://github.com/TheArtOfSound/lolm/issues/72" target="_blank" rel="noopener noreferrer">public issue #72</a>.</p></aside>'
 +'<section class="rc-section" aria-labelledby="rcWorkflow"><div class="rc-section-head"><div><p class="rc-eyebrow">01 / Workflow scanner scope</p><h2 id="rcWorkflow">Three observations corroborated against source</h2></div><p>Configuration indicators, not severity scores or claims of exploitation.</p></div>'
 +r.observations.map(record).join("\n")+'</section>'
 +'<section class="rc-section rc-manual" aria-labelledby="rcManual"><div class="rc-section-head"><div><p class="rc-eyebrow">02 / Separate manual review</p><h2 id="rcManual">Release-control defects found outside the scanner</h2></div><p>These findings required reading Python control flow. They must not be presented as Qira Proof workflow-scanner detections.</p></div>'
 +r.companion.map(record).join("\n")+'</section>'
 +'<section class="rc-method" aria-label="Method and reproducibility"><div><p class="rc-eyebrow">Method</p><h2>How to reproduce the review</h2>'
 +'<p>Open the immutable GitHub links above, inspect the referenced source lines, then compare the three workflow observations against the scanner&#39;s recorded output. Check the separate Python claims against the exception and merge/publish branches. All claims are bounded to those files and commit.</p></div>'
 +'<div><p class="rc-eyebrow">Limitations</p><p>'+escapeText(r.coverage)+'</p><p>'+escapeText(r.methodology)+'</p><p>No external reviewer has yet adjudicated the results.</p></div></section>'
 +'<div class="rc-close"><div><h2>Want the same clarity for your repository?</h2><p>The founding service covers one authorized repository and up to 20 workflow files, with human review and a written report.</p></div>'
 +'<a href="/#pricing">See the $299 review <span aria-hidden="true">→</span></a></div></div></div>';
}
