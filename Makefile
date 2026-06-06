.PHONY: hf-smoke hf-train-tiny hf-compare hf-tests

PROFILE ?= qwen3_0_6b_smoke
DEVICE ?=
STEPS ?= 20
CKPT ?= runs/hf_graft_tiny/ckpt.pt

hf-smoke:
	python scripts/run_hf_graft_smoke.py --profile $(PROFILE) $(if $(DEVICE),--device $(DEVICE),)

hf-train-tiny:
	python scripts/train_hf_graft_tiny.py --profile $(PROFILE) --steps $(STEPS) $(if $(DEVICE),--device $(DEVICE),)

hf-compare:
	python scripts/eval_hf_graft_compare.py --profile $(PROFILE) --checkpoint $(CKPT) $(if $(DEVICE),--device $(DEVICE),)

hf-tests:
	pytest -q tests/test_hf_registry_and_graft.py
