from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

from local_ui.artifact_manifest_patch import corrected_artifact_manifest


class FakeSandbox:
    id = "sbx_pdf"

    def __init__(self, root: Path):
        self.dir = root

    def list_files(self, limit=500):
        return [
            "main.py",
            "output.pdf",
            "_lolm_contract_probe.py",
            "__pycache__/main.pyc",
        ][:limit]

    def _safe(self, rel: str) -> Path:
        path = (self.dir / rel).resolve()
        assert self.dir.resolve() in path.parents or path == self.dir.resolve()
        return path


def test_generated_binary_pdf_is_embedded_exactly_and_added_to_receipt_files(tmp_path: Path):
    pdf = b"%PDF-1.4\n\x00\xffbinary\n%%EOF\n"
    (tmp_path / "main.py").write_text("open('output.pdf','wb').write(b'x')\n")
    (tmp_path / "output.pdf").write_bytes(pdf)
    (tmp_path / "_lolm_contract_probe.py").write_text("print('CONTRACT_OK')\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "main.pyc").write_bytes(b"cache")

    agent = SimpleNamespace(
        sb=FakeSandbox(tmp_path),
        _files_written=["main.py"],
        reliability=SimpleNamespace(
            contract=SimpleNamespace(required_paths=["output.pdf"]),
        ),
    )
    manifest = corrected_artifact_manifest(
        agent,
        max_file_bytes=2_000_000,
        max_total_bytes=10_000_000,
    )
    assert manifest["complete"] is True
    assert agent._files_written == ["main.py", "output.pdf"]
    rows = {row["path"]: row for row in manifest["files"]}
    assert set(rows) == {"main.py", "output.pdf"}
    assert rows["output.pdf"]["encoding"] == "base64"
    assert rows["output.pdf"]["sha256"] == hashlib.sha256(pdf).hexdigest()
    assert rows["output.pdf"]["size"] == len(pdf)


def test_missing_required_pdf_makes_manifest_incomplete(tmp_path: Path):
    (tmp_path / "main.py").write_text("print('claimed pdf')\n")
    agent = SimpleNamespace(
        sb=FakeSandbox(tmp_path),
        _files_written=["main.py"],
        reliability=SimpleNamespace(
            contract=SimpleNamespace(required_paths=["output.pdf"]),
        ),
    )
    # Fake list names output.pdf but exact bytes are missing, so it cannot ship.
    manifest = corrected_artifact_manifest(agent)
    assert manifest["complete"] is False
    assert "output.pdf" not in {row["path"] for row in manifest["files"]}
