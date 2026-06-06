# Odysseus asset map for LOLM-NFET

Odysseus is a useful product blueprint, not the core identity. LOLM-NFET should absorb workspace patterns while making the latent-order system visible and trainable.

## Patterns to adapt

| Odysseus pattern | LOLM-NFET version |
|---|---|
| Chat workspace | Chat plus live LOLM/NFET introspection. |
| Agent/tools | NFET-controlled action loop: continue, retrieve, verify, branch, finalize. |
| Cookbook/model fit | Hardware-aware model loader with local-safe profiles and teacher profiles separated. |
| Compare | Base vs graft vs ablations, not just model A vs model B. |
| Memory/skills | Local trace memory: prompt, response, gate, regimes, control states, feedback. |
| Deep research | NFET branch/verify/retrieve loop with trace report. |
| Documents | Research notebook that stores experiments and turns chats into training cases. |
| Notes/tasks | Local run queue: train graft, evaluate graft, compare ablations, export dataset. |
| Settings | Profiles, device, max local params, teacher endpoints, privacy/export. |

## What must stay unique

LOLM-NFET is not just a local chat app. Its differentiator is that the user can see and shape the latent machinery:

- surface vs latent gate
- regime entropy and regime usage
- hidden drift
- NFET control decision
- base top token vs graft top token
- base entropy vs graft entropy
- base-to-graft movement
- feedback stored as local improvement data

## Build priorities

1. Introspection-first chat.
2. Local improvement log.
3. Graft training on local traces.
4. Base/graft/ablation compare UI.
5. Hardware-aware model cookbook.
6. Tool runner controlled by NFET.
7. Memory/skills backed by local vectors and trace events.
8. Deep research report mode.
