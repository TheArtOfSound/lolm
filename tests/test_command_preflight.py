from lolm.command_preflight import (
    FailureClass,
    ShellDialect,
    classify_failure,
    inspect_command,
    verifier_plan,
)


def test_rejects_human_open_instruction():
    result = inspect_command("Open index.html in a web browser to play the game.")
    assert result.accepted is False
    assert result.primary_failure == FailureClass.NATURAL_LANGUAGE


def test_rejects_headless_desktop_opener():
    result = inspect_command("xdg-open index.html")
    assert result.accepted is False
    assert result.primary_failure == FailureClass.DESKTOP_CAPABILITY


def test_rejects_process_substitution_under_posix_sh():
    result = inspect_command(
        "node --check <(sed -n '/<script>/,/<\\/script>/p' index.html)",
        shell=ShellDialect.POSIX_SH,
    )
    assert result.accepted is False
    assert result.primary_failure == FailureClass.SHELL_DIALECT
    assert any(issue.code == "process_substitution" for issue in result.issues)


def test_allows_process_substitution_when_bash_is_explicit():
    result = inspect_command(
        "node --check <(printf 'console.log(1)')",
        shell=ShellDialect.BASH,
    )
    assert result.accepted is True


def test_rejects_python_execution_of_html():
    result = inspect_command("python3 index.html", primary_language="html")
    assert result.accepted is False
    assert result.primary_failure == FailureClass.CROSS_LANGUAGE


def test_rejects_py_compile_of_html_body_path():
    result = inspect_command("python3 -m py_compile index.html")
    assert result.accepted is False
    assert result.primary_failure == FailureClass.CROSS_LANGUAGE


def test_rejects_python_on_html_primary_without_python_harness():
    result = inspect_command(
        "python3 verify.py",
        primary_language="html",
        known_files=["index.html"],
    )
    assert result.accepted is False
    assert result.primary_failure == FailureClass.CROSS_LANGUAGE


def test_allows_python_harness_on_html_primary_when_present():
    result = inspect_command(
        "python3 verify.py",
        primary_language="html",
        known_files=["index.html", "verify.py"],
    )
    assert result.accepted is True


def test_rejects_markdown_wrapped_command():
    result = inspect_command("```sh\npython3 main.py\n```")
    assert result.accepted is False
    assert result.primary_failure == FailureClass.FORMAT


def test_rejects_unbalanced_quotes():
    result = inspect_command("python3 -c \"print('x')")
    assert result.accepted is False
    assert result.primary_failure == FailureClass.COMMAND_SYNTAX


def test_posix_command_is_accepted():
    result = inspect_command("python3 -m py_compile main.py")
    assert result.accepted is True
    assert result.executable == "python3"


def test_html_verifiers_are_internal_and_artifact_appropriate():
    plans = verifier_plan("index.html", primary_language="html")
    assert [plan.verifier for plan in plans[:2]] == ["html.render", "html.static_lint"]
    assert all(plan.internal for plan in plans[:2])
    assert not any("python" in plan.command for plan in plans)


def test_failure_taxonomy_distinguishes_shell_from_source_syntax():
    shell_cls, shell_fp = classify_failure(
        command="node --check <(cat app.js)",
        exit_code=2,
        stderr='/bin/sh: 1: Syntax error: "(" unexpected',
    )
    source_cls, source_fp = classify_failure(
        command="python3 main.py",
        exit_code=1,
        stderr="SyntaxError: invalid syntax",
    )
    assert shell_cls == FailureClass.SHELL_DIALECT
    assert source_cls == FailureClass.SOURCE_SYNTAX
    assert shell_fp != source_fp


def test_preflight_failure_has_stable_fingerprint():
    first = inspect_command("Open index.html in a web browser to play the game.")
    second = inspect_command("Open index.html in a web browser to play the game.")
    assert first.fingerprint == second.fingerprint
    cls, fingerprint = classify_failure(preflight=first)
    assert cls == FailureClass.NATURAL_LANGUAGE
    assert fingerprint == f"preflight:{first.fingerprint}"
