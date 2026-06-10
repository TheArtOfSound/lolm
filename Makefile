.PHONY: hf-smoke hf-train-tiny hf-train-stream hf-compare hf-compare-ablations hf-tests local-ui agent-ui nfet-tests nfet-controller nfet-smoke nfet-mcp

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

agent-ui:
	PYTHONPATH=. python local_ui/server_agent.py

nfet-tests:
	PYTHONPATH=. pytest -q tests/test_nfet_policy.py tests/test_nfet_agent.py tests/test_nfet_controller_train.py tests/test_claude_reasoner.py tests/test_mcp_server.py

nfet-controller:
	PYTHONPATH=. python scripts/train_nfet_controller.py --synthetic 400 --d-model 1024 --epochs 10 --out runs/nfet_controller/bootstrap_qwen06b.pt

nfet-smoke:
	PYTHONPATH=. python scripts/smoke_nfet_agent.py --ckpt runs/nfet_controller/bootstrap_qwen06b.pt

nfet-mcp:
	PYTHONPATH=. python local_ui/mcp_server.py
