# LinkedIn post draft

We just put something live that I've wanted to exist for a long time: an AI
agent whose decisions come from **measurement, not self-report**.

Today's agents decide to search or verify by prompting the model — "are you
confident?" — and trusting the answer. Our agent reads four signals directly
off the model's own activations on every token it writes (next-token entropy,
hidden-state drift, our architecture's surface/latent gate balance, regime
entropy). A trained controller turns those signals into five actions:
continue, retrieve, verify, branch, finalize.

When its uncertainty spikes, it stops mid-generation and checks its notes.
When something shifts in its internal representation, it re-reads its own
draft. When it's calm and confident, it finishes — by its own decision.

Three design choices I'm proud of:

1. **Receipts, not vibes.** Every run is compared against the same model in
   plain chatbot mode, and the verdict is published — including the runs
   where the agent didn't win.

2. **Provenance the model can't fake.** "What I used / what I checked" is
   assembled by the harness from the actual action log. Claiming a check
   that never ran is structurally impossible.

3. **A self-improvement flywheel.** The controller bootstraps from
   calibrated rules, then retrains on the workspace's own logged usage with
   outcome labels. Three turns in, the learned head makes about half of all
   production decisions — and we can show you which ones.

It's live on two model lines (a 0.6B on a tiny shared server, a 4B from our
lab machine), it runs privately on your own notes, and the whole workspace
speaks the Model Context Protocol so it plugs into modern agent stacks.

Honest caveat, stated on the page itself: the demo models are small and the
prose shows it. The claim is the control mechanism — and it's model-agnostic.

Try it (no signup): https://lolm.imagineqira.com/try.html
The science: https://lolm.imagineqira.com

LOLM is patent-pending. Built at Qira — two brothers, Arizona, no venture
capital.
