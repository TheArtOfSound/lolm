# Show HN draft

**Title:**
Show HN: An agent that measures its own uncertainty instead of asking itself

**URL:** https://lolm.imagineqira.com/try.html

**Comment to post with it:**

Most agents decide to use tools by prompting the model: "are you sure? should
you search?" — a self-report, and models are famously bad at those. We built
an agent where those decisions come from measurement instead.

While the model writes, we read four signals off its own activations on every
token: next-token entropy, hidden-state drift, the surface/latent gate balance
of our architecture, and regime entropy. A small trained head maps them to
five actions: continue, retrieve, verify, branch, finalize. Entropy spikes →
it goes and checks its notes mid-generation. Representation jumps while
uncertain → it re-reads its own draft. Calm and stable → it stops on its own.

A few things we tried to get right:

- Every run produces a receipt comparing against the same model in plain
  chatbot mode. Some receipts honestly say "this didn't beat the chatbot."
- The provenance ("used 2 notes", "self-checked once") is assembled by the
  harness from the action log — the model physically can't claim checks it
  didn't do.
- The controller bootstraps from calibrated heuristics, then retrains on the
  workspace's own logged traffic with outcome labels (a retrieve that found
  nothing relevant becomes a "should have continued" example). After three
  turns of that flywheel it makes about half the decisions in production.
- It runs on your own notes, fully local: point the importer at a markdown
  folder and uncertainty-driven retrieval works against your facts.

The public demo runs two lines: a 0.6B on a tiny shared 2-vCPU box
(~90s/run), and a 4B served from the lab machine through a tunnel when it's
online. The honest caveat is on the page: a 0.6B research model writes modest
prose — the claim is the control mechanism, which is backbone-agnostic. One
genuinely interesting thing we measured: the 4B's telemetry is *calmer* than
the 0.6B's, so the same controller finishes earlier on the bigger model.

The underlying architecture (LOLM, a hybrid Transformer-SSM with five fused
streams) is patent-pending and the repo is private during review, but the
agent protocol is documented, there's an npm client (lolm-nfet-client), and
the whole workspace speaks MCP so it plugs into Claude Code/Desktop.

Happy to answer anything — especially skeptical questions about whether
measured uncertainty actually beats prompted self-assessment.

---
**Field-verification note (2026-06-11):** we surveyed the source of 127 public
agent frameworks/repos (autogen, semantic-kernel, MetaGPT, crewAI, OpenHands,
cline, aider, google-adk, AutoGPT, plus 100+ smaller agent/memory projects).
Every confidence signal we found is self-reported by the model in its own
output (regex-parsed "Confidence: 0.8" lines, JSON fields the model wrote) or
an embedding-similarity score; every `logprobs` reference is a pass-through
API option that no decision logic consumes. We found no public agent that
drives control decisions from measured model internals. If you know of one,
we genuinely want to hear about it.
