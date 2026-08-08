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


def test_deploy_enforces_docs_only_product_and_retired_execution_boundary():
    deploy = (ROOT / "deploy" / "deploy_box.sh").read_text(encoding="utf-8")
    assert "config['product']['mode'] == 'open_source_cli'" in deploy
    assert "{'website': False, 'cli': True, 'hosted_api': False}" in deploy
    assert "config['commercial_license']['public_prices'] is False" in deploy
    assert 'check "old status retired"' in deploy
    assert 'run_code" = "410"' in deploy
    assert "'plans' not in config and 'billing' not in config" in deploy
    assert "smoke_pdf_delivery.py" not in deploy


def test_deploy_independently_proves_the_live_qira_launcher_bytes():
    deploy = (ROOT / "deploy" / "deploy_box.sh").read_text(encoding="utf-8")
    assert 'check "shared design system"' in deploy
    assert 'cmp -s site/lolm-ds.js "$live_design_tmp"' in deploy
    assert "qira-product-launcher" in deploy
    assert 'current-product", "lolm"' in deploy
