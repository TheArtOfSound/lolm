# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Track 2: mutation gateway — RBE, CAS, authorization, receipts."""

from __future__ import annotations

from pathlib import Path

import pytest

from lolm.mutation_gateway import (
    MutationGateway,
    MutationOp,
    MutationState,
    normalize_repo_path,
)
from lolm.repo_context import content_hash


class FakeSandbox:
    def __init__(self) -> None:
        self.files: dict[str, str] = {}

    def write_file(self, rel: str, content: str, reason: str = ""):
        self.files[rel] = content
        return {"path": rel, "diff": "", "reason": reason}

    def read_file(self, rel: str):
        if rel not in self.files:
            raise FileNotFoundError(rel)
        return self.files[rel]

    def list_files(self, limit: int = 800):
        return list(self.files.keys())[:limit]

    def delete_file(self, rel: str):
        self.files.pop(rel, None)
        return {"deleted": True, "path": rel}


def test_01_edit_without_read_rejected():
    sb = FakeSandbox()
    sb.files["src/a.py"] = "x = 1\n"
    gw = MutationGateway(sb, task="fix a")
    with pytest.raises(PermissionError, match="read_required|read"):
        gw.authorize_edit("src/a.py", "x = 2\n")


def test_02_stale_revision_between_read_and_write():
    sb = FakeSandbox()
    sb.files["src/a.py"] = "x = 1\n"
    gw = MutationGateway(sb, task="fix a")
    gw.read("src/a.py")
    # External change after read
    sb.files["src/a.py"] = "x = 99\n"
    with pytest.raises(PermissionError, match="changed|read"):
        gw.authorize_edit("src/a.py", "x = 2\n")


def test_03_read_one_file_edit_another_rejected():
    sb = FakeSandbox()
    sb.files["a.py"] = "a=1\n"
    sb.files["b.py"] = "b=1\n"
    gw = MutationGateway(sb)
    gw.read("a.py")
    with pytest.raises(PermissionError):
        gw.authorize_edit("b.py", "b=2\n")


def test_04_excerpt_scope_blocks_huge_rewrite():
    sb = FakeSandbox()
    big = "line\n" * 200
    sb.files["big.py"] = big
    gw = MutationGateway(sb)
    gw.read("big.py", scope="range", line_start=1, line_end=5)
    # Attempt full rewrite much larger relative to... auth.scope is range
    # Our check: scope range/symbol and new content > 2*size
    huge = "x\n" * 5000
    with pytest.raises(PermissionError, match="full rewrite|scope"):
        gw.authorize_edit(
            "big.py", huge, operation=MutationOp.FULL_REWRITE,
        )


def test_05_create_html_task_blocks_python_product_file():
    sb = FakeSandbox()
    gw = MutationGateway(sb, primary_language="html", task="snake game")
    with pytest.raises(PermissionError, match="HTML-primary|Python"):
        gw.authorize_create("main.py", "print(1)\n")


def test_06_create_allowed_index_html():
    sb = FakeSandbox()
    gw = MutationGateway(sb, primary_language="html", required_paths=["index.html"])
    prop = gw.authorize_create("index.html", "<html></html>")
    rec = gw.apply(prop)
    assert rec.state == MutationState.APPLIED.value
    assert rec.compare_and_swap_passed is True
    assert "index.html" in sb.files


def test_07_exact_count_blocks_extra_create():
    sb = FakeSandbox()
    sb.files["index.html"] = "<html></html>"
    gw = MutationGateway(
        sb, primary_language="html", exact_count=1, required_paths=["index.html"],
    )
    with pytest.raises(PermissionError, match="exact_count"):
        gw.authorize_create("extra.html", "<html>other</html>")


def test_08_cas_passes_on_fresh_edit():
    sb = FakeSandbox()
    sb.files["a.py"] = "x = 1\n"
    gw = MutationGateway(sb)
    gw.read("a.py")
    rec = gw.write("a.py", "x = 2\n", creating=False, selection_reason="fix")
    assert rec.compare_and_swap_passed is True
    assert rec.post_apply_sha256 == content_hash("x = 2\n")
    assert sb.files["a.py"] == "x = 2\n"
    assert rec.read_before_edit is True


def test_09_path_escape_rejected():
    with pytest.raises(ValueError):
        normalize_repo_path("../etc/passwd")
    with pytest.raises(ValueError):
        normalize_repo_path("/abs/path")


def test_10_rollback_restores_bytes_and_removes_create():
    sb = FakeSandbox()
    gw = MutationGateway(sb, primary_language="python")
    rec_c = gw.write("new.py", "print(1)\n", creating=True)
    assert "new.py" in sb.files
    rb = gw.rollback(rec_c.mutation_id)
    assert rb is not None
    assert rb.rollback is True
    assert "new.py" not in sb.files

    sb.files["old.py"] = "a=1\n"
    gw2 = MutationGateway(sb)
    gw2.read("old.py")
    rec_e = gw2.write("old.py", "a=2\n", creating=False)
    assert sb.files["old.py"] == "a=2\n"
    gw2.rollback(rec_e.mutation_id)
    assert sb.files["old.py"] == "a=1\n"


def test_11_map_refreshes_after_accepted_edit():
    sb = FakeSandbox()
    sb.files["svc.py"] = "def run():\n    return 1\n"
    gw = MutationGateway(sb)
    gw.refresh_map()
    assert "svc.py" in gw._map_entries
    old_sha = gw._map_entries["svc.py"].sha256
    gw.read("svc.py")
    gw.write("svc.py", "def run():\n    return 2\n", creating=False)
    assert gw._map_entries["svc.py"].sha256 != old_sha
    assert gw._map_entries["svc.py"].last_modified_step >= 0


def test_12_selection_exposes_reasons():
    sb = FakeSandbox()
    sb.files["auth.py"] = "def verify_token(t):\n    return True\n"
    sb.files["colors.py"] = "PALETTE=['red']\n"
    gw = MutationGateway(sb, task="fix verify_token")
    picks = gw.select_targets("fix verify_token authentication")
    assert picks
    assert picks[0]["path"] == "auth.py"
    assert picks[0]["reason"]


def test_13_auto_sanitizer_path_requires_read():
    sb = FakeSandbox()
    sb.files["a.py"] = "x=1\n"
    gw = MutationGateway(sb)
    # Direct authorize_edit without read fails — sanitizer must read first
    with pytest.raises(PermissionError):
        gw.authorize_edit("a.py", "x=1\n# fixed\n")


def test_14_receipt_blob_shape():
    sb = FakeSandbox()
    gw = MutationGateway(sb, primary_language="python")
    gw.write("n.py", "print(1)\n", creating=True)
    blob = gw.receipt_blob()
    assert "mutation_gateway" in blob
    assert blob["mutation_gateway"]["mutations"]
    m = blob["mutation_gateway"]["mutations"][-1]
    assert m["operation"] == "create"
    assert m["compare_and_swap_passed"] is True


def test_15_assert_no_blind_edits():
    sb = FakeSandbox()
    sb.files["a.py"] = "x=1\n"
    gw = MutationGateway(sb)
    gw.read("a.py")
    gw.write("a.py", "x=2\n", creating=False)
    assert gw.assert_no_blind_existing_edits() is True


def test_16_duplicate_basename_create_rejected():
    sb = FakeSandbox()
    sb.files["pkg/util.py"] = "x=1\n"
    gw = MutationGateway(sb)
    with pytest.raises(PermissionError, match="duplicate"):
        gw.authorize_create("other/util.py", "y=2\n")


def test_17_rename_preserves_content():
    sb = FakeSandbox()
    sb.files["old.py"] = "hello\n"
    gw = MutationGateway(sb)
    prop = gw.authorize_rename("old.py", "new.py")
    rec = gw.apply(prop)
    assert rec.state == MutationState.APPLIED.value
    assert "new.py" in sb.files
    assert sb.files["new.py"] == "hello\n"
    assert "old.py" not in sb.files


def test_18_edit_fragment_path():
    sb = FakeSandbox()
    sb.files["a.py"] = "foo = 1\nbar = 2\n"
    gw = MutationGateway(sb)
    gw.read("a.py")
    rec = gw.write(
        "a.py", "9", creating=False, old_fragment="foo = 1",
        selection_reason="fragment",
    )
    assert rec.state == MutationState.APPLIED.value
    assert "foo = 9" in sb.files["a.py"] or sb.files["a.py"].startswith("9")


def test_19_concurrent_style_double_apply_second_stale():
    sb = FakeSandbox()
    sb.files["a.py"] = "v=1\n"
    gw = MutationGateway(sb)
    gw.read("a.py")
    prop1 = gw.authorize_edit("a.py", "v=2\n")
    r1 = gw.apply(prop1)
    assert r1.compare_and_swap_passed
    # Re-applying the original proposal is a stale-revision CAS failure
    r2 = gw.apply(prop1)
    assert r2.state == MutationState.REJECTED.value
    assert r2.rejection_reason == "stale_revision"


def test_20_binary_rejected():
    sb = FakeSandbox()
    gw = MutationGateway(sb)
    with pytest.raises(PermissionError, match="binary"):
        gw.authorize_create("blob.bin", "\x00\x01\x02binary")
