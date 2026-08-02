from local_ui.code_loop_guard import command_blocked_by_language


def check(command, *, language="html", files=None, contents=None):
    return command_blocked_by_language(
        command,
        primary_language=language,
        files_written=files or ["index.html"],
        file_contents=contents or {"index.html": "<html><script>console.log(1)</script></html>"},
    )


def test_live_guard_rejects_human_browser_instruction():
    blocked, reason = check("Open index.html in a web browser to play the game.")
    assert blocked is True
    assert "natural_language" in reason


def test_live_guard_rejects_bash_process_substitution_under_sh():
    blocked, reason = check(
        "node --check <(sed -n '/<script>/,/<\\/script>/p' index.html)"
    )
    assert blocked is True
    assert "shell_dialect" in reason
    assert "process_substitution" in reason


def test_live_guard_rejects_python_execution_of_html():
    blocked, reason = check("python3 index.html")
    assert blocked is True
    assert "cross_language" in reason


def test_live_guard_rejects_py_compile_of_html_body_in_py_path():
    blocked, reason = check(
        "python3 -m py_compile main.py",
        files=["index.html", "main.py"],
        contents={
            "index.html": "<html></html>",
            "main.py": "<!doctype html><html></html>",
        },
    )
    assert blocked is True
    assert "HTML content" in reason or "cross_language" in reason


def test_live_guard_allows_posix_javascript_check():
    blocked, reason = check(
        "node --check app.js",
        language="javascript",
        files=["app.js"],
        contents={"app.js": "console.log(1);"},
    )
    assert blocked is False
    assert reason == ""


def test_live_guard_allows_real_python_test_on_python_task():
    blocked, reason = check(
        "python3 -m pytest -q",
        language="python",
        files=["main.py", "test_main.py"],
        contents={"main.py": "def add(a,b): return a+b"},
    )
    assert blocked is False
    assert reason == ""
