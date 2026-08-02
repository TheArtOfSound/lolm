# Copyright (c) 2026 Qira LLC. All rights reserved.
"""OpenAI-compatible chat transport: remote model turns + *local* CodeAgent.

Distinct experiment from ``lolm-code-sse``. Do not pool results.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any, Callable, Dict, List, Optional

from lolm.track2b.redact import redact_text


def make_openai_chat(
    base_url: str,
    api_key: str,
    model: str,
    *,
    timeout: float = 120.0,
) -> Callable[[List[Dict[str, str]]], str]:
    """Return a chat(messages) callable for local CodeAgent."""
    secrets = [api_key] if api_key else []
    base = base_url.rstrip("/")
    # Accept base with or without /v1
    if base.endswith("/chat/completions"):
        url = base
    elif base.endswith("/v1"):
        url = base + "/chat/completions"
    else:
        url = base + "/chat/completions"

    def chat(msgs: List[Dict[str, str]]) -> str:
        body = json.dumps({
            "model": model,
            "messages": msgs,
            "temperature": 0.2,
            "max_tokens": 2048,
        }).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
        except Exception as exc:
            raise RuntimeError(redact_text(str(exc), secrets)[:400]) from None

    return chat


TRANSPORT = "openai-chat"
