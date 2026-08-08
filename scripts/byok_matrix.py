#!/usr/bin/env python3
# Copyright (c) 2026 Qira LLC. All rights reserved.
"""BYOK power matrix — which keys are set RIGHT NOW and what each one upgrades.

Usage:  python3 scripts/byok_matrix.py
Prints key -> set? -> flows it powers. The offline routing proofs live in
tests/test_byok_matrix.py; this is the operator-friendly live view.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from local_ui.byok import KEY_SPECS  # noqa: E402

FLOWS = {
    "ANTHROPIC_API_KEY": "chat leads + math-fix + skeptic + operator/code answers + streaming builds + ensemble candidate",
    "GROQ_API_KEY": "direct brain + streaming + ensemble (gpt-oss-120b / llama-4-scout / llama-70b)",
    "CEREBRAS_API_KEY": "direct brain + streaming + ensemble (zai-glm-4.7 / gpt-oss-120b)",
    "OPENAI_API_KEY": "direct brain + ensemble candidate",
    "TOGETHER_API_KEY": "direct brain + ensemble candidate",
    "OPENROUTER_API_KEY": "direct brain + ensemble candidate",
    "WORKERS_AI_URL": "the 70B gateway cascade (chat/stream/ensemble)",
    "WORKERS_AI_SECRET": "auth for the gateway",
    "LOLM_BRAIN": "pins the voice (claude/local/70b)",
    "LOLM_LOCAL_MODEL": "your local model — chat + operator planning, fully sovereign",
    "LOLM_LOCAL_URL": "where the local model serves",
    "LOLM_LOCAL_API": "ollama | openai (LM Studio / vLLM / evolved :11435)",
    "LOLM_LOCAL_API_KEY": "bearer for keyed local/remote OpenAI-compatible endpoints",
    "BRAVE_SEARCH_API_KEY": "every search: chat grounding, research, freshness, operator, life",
    "TAVILY_API_KEY": "same searches (2nd in the fallback chain)",
    "SEARXNG_URL": "same searches via your SearXNG",
}

print(f"{'key':26} {'set':4} unlocks")
print("-" * 100)
for spec in KEY_SPECS:
    env = spec["env"]
    is_set = "YES" if os.environ.get(env, "").strip() else "-"
    print(f"{env:26} {is_set:4} {FLOWS.get(env, spec.get('unlocks', ''))}")
print("-" * 100)
print("keys apply instantly when saved in the Keys panel (no restart). "
      "Routing proofs: pytest tests/test_byok_matrix.py")
