from __future__ import annotations

from local_ui.contract_medium_patch import install_patch
from lolm.reliability.evidence import content_sha256


LIVE_TASK = (
    "First write main.py in the sandbox workspace root. main.py must use only Python "
    "standard library code to generate a valid one-page binary PDF named output.pdf "
    "visibly labeled UNOFFICIAL LOLM P0 CLOSURE BROWSER TEST. After writing main.py, "
    "run python3 main.py. The program must print PDF_READY output.pdf. Do not run "
    "main.py before writing it and do not create another user-facing document."
)


def _valid_pdf() -> bytes:
    return b"%PDF-1.4\n" + (b"0" * 96) + b"\n%%EOF\n"


def test_pdf_content_label_does_not_compile_html_render_requirement():
    install_patch()
    from lolm.reliability.contract_compiler import compile_contract

    contract = compile_contract(LIVE_TASK)

    assert contract.primary_language == "pdf"
    assert contract.required_paths == ["main.py", "output.pdf"]
    assert not any(
        clause.hardness == "hard" and clause.verifier == "html.render"
        for clause in contract.clauses
    )
    assert any(
        clause.hardness == "hard" and clause.verifier == "pdf.exists"
        for clause in contract.clauses
    )


def test_live_pdf_contract_closes_from_real_bytes_without_browser_validator():
    install_patch()
    from lolm.reliability.run_state import RunReliabilityState

    state = RunReliabilityState.open(LIVE_TASK, max_steps=8)
    pdf = _valid_pdf()
    contents = {
        "main.py": "from pathlib import Path\nPath('output.pdf').write_bytes(b'%PDF-1.4')\n",
        "output.pdf": pdf,
    }
    result = state.evaluate_and_maybe_close(
        list(contents),
        file_contents=contents,
        claimed_hashes={path: content_sha256(body) for path, body in contents.items()},
        validators_green=True,
        verifier_outputs={
            "pdf.exists": {
                "ok": True,
                "valid_magic": True,
                "path": "output.pdf",
            }
        },
        step=1,
    )

    assert result["manifest_check"]["ok"] is True
    assert result["manifest_check"]["open_hard"] == 0
    assert result["validators_ok"] is True
    assert result["closure"]["closed"] is True
    assert result["closure"]["preconditions"]["type_bytes_ok"] is True


def test_actual_html_request_keeps_html_render_requirement():
    install_patch()
    from lolm.reliability.contract_compiler import compile_contract

    contract = compile_contract(
        "Create a playable browser canvas game as index.html with keyboard controls."
    )

    assert contract.primary_language == "html"
    assert any(
        clause.hardness == "hard" and clause.verifier == "html.render"
        for clause in contract.clauses
    )


def test_python_log_label_with_browser_word_stays_python_only():
    install_patch()
    from lolm.reliability.contract_compiler import compile_contract

    contract = compile_contract(
        "Create main.py that prints the literal label BROWSER TEST and exits."
    )

    assert contract.primary_language == "python"
    assert not any(
        clause.hardness == "hard" and clause.verifier == "html.render"
        for clause in contract.clauses
    )
