# LOLM-NFET Hugging Face Build Path

This is the practical checkpoint plan for building LOLM-NFET on top of existing open-weight models.

## Selected checkpoints

| Role | Profile | Hugging Face model | License | Why it exists in the build |
|---|---|---|---|---|
| Smoke base | `qwen3_0_6b_smoke` | `Qwen/Qwen3-0.6B` | Apache-2.0 | Smallest runnable hidden-state extraction and graft smoke test. |
| Lab base | `qwen3_4b_lab` | `Qwen/Qwen3-4B` | Apache-2.0 | First serious adapter-training target. |
| Main base | `qwen3_8b_main` | `Qwen/Qwen3-8B` | Apache-2.0 | Main scale target after the 4B graft shows signal. |
| Scale base | `qwen3_32b_scale` | `Qwen/Qwen3-32B` | Apache-2.0 | Large open-weight base for serious adapter comparisons. |
| Memory encoder | `qwen3_embedding_memory` | `Qwen/Qwen3-Embedding-0.6B` | Apache-2.0 | External memory and retrieval embeddings. |
| Teacher | `glm_5_1_teacher` | `zai-org/GLM-5.1` | MIT | High-end teacher for distillation and adversarial comparison. |
| Teacher | `glm_5_1_fp8_teacher` | `zai-org/GLM-5.1-FP8` | MIT | Lower-memory teacher-serving option. |
| Edge teacher | `kimi_k2_thinking_teacher` | `moonshotai/Kimi-K2-Thinking` | Other | Largest reasoning teacher. Use for traces, not finetuning. |
| Edge teacher | `kimi_k2_instruct_teacher` | `moonshotai/Kimi-K2-Instruct-0905` | Other | Instruction trace teacher. Use for distillation pressure. |

## First run

```bash
pip install -r requirements.txt
python scripts/run_hf_graft_smoke.py --profile qwen3_0_6b_smoke
```

Expected result: JSON summary with hidden-state shape, corrected-hidden shape, gate mean, regime entropy, logit entropy, and NFET control logits.

## Architecture committed in this pass

```text
Frozen Hugging Face causal LM
  -> final hidden states
  -> LOLM latent path stub
  -> regime detector
  -> manifestation adapter
  -> residual correction
  -> NFET controller observables
```

Files:

```text
configs/hf_models.yaml        # checkpoint registry
lolm/hf_registry.py           # typed registry loader
lolm/hf_backbone.py           # frozen HF backbone wrapper
lolm/nfet_graft.py            # LOLM-NFET graft skeleton
scripts/run_hf_graft_smoke.py # first executable smoke test
```

## Next engineering moves

1. Replace `LatentSSMStub` with the repository's full selective SSM module.
2. Add adapter training against token loss using frozen Qwen hidden states.
3. Add teacher trace generation from GLM/Kimi.
4. Add eval matrix: base vs base+LOLM graft vs base+NFET vs base+LOLM+NFET.
5. Add ablations for latent path, regime, gate, NFET controller, and memory.

## Rule

Do not touch trillion-parameter teacher weights. Use them as trace generators and adversarial judges. Prove the graft on Qwen first.
