# Copyright (c) 2026 Qira LLC. All rights reserved.
"""BYOK key store: set/persist/load/mask, env-wins, invalid keys rejected."""

import os

from local_ui import byok


def test_set_persist_load_and_mask(tmp_path, monkeypatch):
    kf = tmp_path / "keys.env"
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    n = byok.set_keys({"BRAVE_SEARCH_API_KEY": "bsk_secret_1234567890",
                       "LOLM_LOCAL_MODEL": "qwen2.5:7b",
                       "NOT_A_REAL_KEY": "ignored"}, path=kf)
    assert n == 2                                   # bogus key ignored
    assert oct(kf.stat().st_mode)[-3:] == "600"     # keyfile is private
    assert os.environ["BRAVE_SEARCH_API_KEY"] == "bsk_secret_1234567890"  # live env updated

    # masked status never leaks the raw value
    brave = next(k for k in byok.status()["keys"] if k["env"] == "BRAVE_SEARCH_API_KEY")
    assert brave["set"] and brave["preview"] == "bsk_…7890"
    assert "secret" not in brave["preview"]


def test_env_wins_over_file(tmp_path, monkeypatch):
    kf = tmp_path / "keys.env"
    kf.write_text("TAVILY_API_KEY=from_file\n")
    monkeypatch.setenv("TAVILY_API_KEY", "from_real_env")
    byok.load_into_env(kf)
    assert os.environ["TAVILY_API_KEY"] == "from_real_env"   # real env not clobbered


def test_clear_key(tmp_path, monkeypatch):
    kf = tmp_path / "keys.env"
    byok.set_keys({"LOLM_LOCAL_URL": "http://127.0.0.1:11434"}, path=kf)
    assert os.environ.get("LOLM_LOCAL_URL")
    byok.set_keys({"LOLM_LOCAL_URL": ""}, path=kf)            # empty clears
    assert not os.environ.get("LOLM_LOCAL_URL")
    assert "LOLM_LOCAL_URL" not in kf.read_text()
