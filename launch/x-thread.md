# X / Twitter thread draft

**1/**
Most AI agents decide to search or double-check by *asking the model if it's
sure.* Self-report, from systems famous for confident nonsense.

We built one that measures instead. Live demo, no signup:
https://lolm.imagineqira.com/try.html

**2/**
Every token, four signals come straight off the model's activations:
→ next-token entropy
→ hidden-state drift
→ surface/latent gate balance
→ regime entropy

A trained head turns them into five moves: continue · retrieve · verify ·
branch · finalize.

**3/**
Watch it happen: uncertainty spikes mid-sentence and the agent stops writing,
pulls relevant notes, and keeps going with them in context.

When it's calm and stable, it decides — on its own — that it's done.

**4/**
Every run ends with a receipt vs. the same model in plain-chatbot mode.

Some receipts say "this run didn't beat the chatbot." We kept those.
An agent you can trust has to be allowed to lose visibly.

**5/**
The "what I used / what I checked" line isn't generated — the harness
assembles it from the action log. The model *cannot* claim a check it never
ran. Fabricated provenance is a structural impossibility, not a prompt
request.

**6/**
The controller starts as calibrated heuristics, then retrains on its own
logged traffic with outcome labels (a retrieve that found nothing useful
becomes a "should have continued" example).

Three flywheel turns in, it makes ~half the decisions in production.

**7/**
It's running publicly on two backbones right now: a 0.6B on a $20/mo shared
box, and a 4B served off our lab machine through a tunnel.

Fun measured finding: the bigger model's telemetry is *calmer*, so the same
controller finishes earlier on it.

**8/**
Runs on your own notes too — point it at a markdown folder, fully local,
nothing leaves your machine.

npm: lolm-nfet-client · MCP server included · patent pending (Qira)

Built by two brothers in Arizona. Zero VC. Receipts on everything.
