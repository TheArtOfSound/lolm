.PHONY: hf-smoke hf-train-tiny hf-train-stream hf-compare hf-compare-ablations hf-tests local-ui

PROFILE ?= qwen3_0_6b_smoke
DEVICE ?=
STEPS ?= 20
CKPT ?= runs/hf_graft_tiny/ckpt.pt
DATASET ?= HuggingFaceFW/fineweb-edu
SEQ_LEN ?= 256
BATCH_SIZE ?= 1
PYTHONPATH ?= .
export PYTHONPATH

hf-smoke:
	PYTHONPATH=. python scripts/run_hf_graft_smoke.py --profile $(PROFILE) $(if $(DEVICE),--device $(DEVICE),)

hf-train-tiny:
	PYTHONPATH=. python scripts/train_hf_graft_tiny.py --profile $(PROFILE) --steps $(STEPS) $(if $(DEVICE),--device $(DEVICE),)

hf-train-stream:
	PYTHONPATH=. python scripts/train_hf_graft_stream.py --profile $(PROFILE) --dataset $(DATASET) --steps $(STEPS) --seq-len $(SEQ_LEN) --batch-size $(BATCH_SIZE) $(if $(DEVICE),--device $(DEVICE),)

hf-compare:
	PYTHONPATH=. python scripts/eval_hf_graft_compare.py --profile $(PROFILE) --checkpoint $(CKPT) $(if $(DEVICE),--device $(DEVICE),)

hf-compare-ablations:
	PYTHONPATH=. python scripts/eval_hf_graft_compare.py --profile $(PROFILE) --checkpoint $(CKPT) --ablations $(if $(DEVICE),--device $(DEVICE),)

hf-tests:
	PYTHONPATH=. pytest -q tests/test_hf_registry_and_graft.py

local-ui:
	PYTHONPATH=. python local_ui/server.py
