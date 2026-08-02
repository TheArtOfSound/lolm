# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Out-of-band mutation trust classes and recovery transactions."""

from __future__ import annotations

import tempfile
from pathlib import Path

from lolm.privileged_mutation import (
    MutationTrustClass,
    PrivilegedMutationLog,
    build_recovery_transaction,
    privileged_write,
    read_sandbox_tree,
    require_privileged_token,
    tree_manifest,
)
from local_ui.sandbox import Sandbox


def test_privileged_write_requires_token():
    with tempfile.TemporaryDirectory() as td:
        sb = Sandbox(td)
        try:
            privileged_write(
                sb, "a.py", "x=1\n",
                trust_class=MutationTrustClass.PRIVILEGED_OPERATOR,
                capability_token_present=False,
                require_token=True,
            )
            assert False, "should have raised"
        except PermissionError as exc:
            assert "capability token" in str(exc)


def test_privileged_write_receipt_and_tree():
    with tempfile.TemporaryDirectory() as td:
        log_path = Path(td) / "priv.jsonl"
        # redirect default log by constructing write after inject is hard —
        # just exercise return shape
        sb = Sandbox(Path(td) / "sb")
        result = privileged_write(
            sb, "a.py", "x=1\n",
            trust_class=MutationTrustClass.PRIVILEGED_OPERATOR,
            reason="test",
            capability_token_present=True,
        )
        assert "privileged_receipt" in result
        rec = result["privileged_receipt"]
        assert rec["trust_class"] == MutationTrustClass.PRIVILEGED_OPERATOR.value
        assert rec["pre_tree"]["tree_hash"]
        assert rec["post_tree"]["tree_hash"]
        assert rec["pre_tree"]["tree_hash"] != rec["post_tree"]["tree_hash"]
        assert sb.read_file("a.py") == "x=1\n"
        # Not a CodeAgent gateway receipt
        assert rec["schema"] == "lolm.privileged_mutation.v1"


def test_recovery_transaction_no_edit_auth():
    with tempfile.TemporaryDirectory() as td:
        sb = Sandbox(Path(td) / "sb")
        sb.write_file("old.py", "1\n", reason="seed")
        before = read_sandbox_tree(sb)
        sb.write_file("new.py", "2\n", reason="restore")
        if hasattr(sb, "delete_file"):
            sb.delete_file("old.py")
        after = read_sandbox_tree(sb)
        tx = build_recovery_transaction(
            sb,
            checkpoint_id="ckpt1",
            expected_pre_tree_hash=tree_manifest(before)["tree_hash"],
            before_files=before,
            after_files=after,
            trust_class=MutationTrustClass.RECOVERY_LGTS,
        )
        d = tx.to_dict()
        assert d["operation"] == "restore_checkpoint"
        assert d["grants_edit_authorization"] is False
        assert d["checkpoint_id"] == "ckpt1"
        assert "new.py" in d["files_created"]
        assert "old.py" in d["files_deleted"]


def test_token_check():
    import os
    os.environ["SANDBOX_SECRET"] = "sekrit"
    try:
        assert require_privileged_token("Bearer sekrit") is True
        assert require_privileged_token("Bearer wrong") is False
        assert require_privileged_token(None) is False
    finally:
        os.environ.pop("SANDBOX_SECRET", None)
