from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_production_release_shell_scripts_parse():
    for relative in ("deploy/deploy_box.sh", "deploy/rollback_box.sh"):
        path = ROOT / relative
        result = subprocess.run(
            ["bash", "-n", str(path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"{relative}: {result.stderr}"


def test_rollback_is_bound_to_paired_app_and_web_snapshot():
    deploy = (ROOT / "deploy" / "deploy_box.sh").read_text(encoding="utf-8")
    rollback = (ROOT / "deploy" / "rollback_box.sh").read_text(encoding="utf-8")
    assert "rollback-snapshot" in deploy
    assert "rollback-snapshot" in rollback
    assert "web backup" in deploy
    assert "restoring website" in rollback
    assert "refusing partial rollback" in rollback


def test_deploy_script_arms_and_executes_automatic_rollback_after_snapshot():
    deploy = (ROOT / "deploy" / "deploy_box.sh").read_text(encoding="utf-8")
    assert "ROLLBACK_ARMED=0" in deploy
    assert "rollback_on_error()" in deploy
    assert "trap rollback_on_error ERR" in deploy
    assert "ROLLBACK_ARMED=1" in deploy
    assert 'bash deploy/rollback_box.sh' in deploy
    assert "ROLLBACK_ARMED=0\ntrap - ERR" in deploy
    assert deploy.index("ROLLBACK_ARMED=1") < deploy.index("syncing code")
