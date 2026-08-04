from lolm.repo_context import (
    ReadBeforeEditGuard,
    SourceDocument,
    build_repository_map,
    extract_symbols,
    rank_repository_context,
)


def test_extracts_python_signatures_and_imports():
    document = SourceDocument(
        "src/service.py",
        """from .store import Store\n\nclass Service:\n    def __init__(self, store: Store):\n        self.store = store\n\n    def fetch(self, key: str) -> str:\n        return self.store.get(key)\n""",
    )
    record = extract_symbols(document)
    names = {symbol.name for symbol in record.symbols}
    assert "Service" in names
    assert "Service.fetch" in names
    fetch = next(symbol for symbol in record.symbols if symbol.name == "Service.fetch")
    assert "key: str" in fetch.signature
    assert "store" in fetch.references
    assert "store" in record.imports


def test_invalid_python_is_mapped_without_crashing():
    record = extract_symbols(SourceDocument("broken.py", "def nope(:\n"))
    assert record.language == "python"
    assert record.symbols == ()
    assert record.line_count == 2


def test_extracts_javascript_and_typescript_symbols():
    document = SourceDocument(
        "src/api.ts",
        """import {client} from './client';\nexport async function loadUser(id) { return client.get(id); }\nexport class UserCache {}\nconst normalize = (value) => value.trim();\n""",
    )
    record = extract_symbols(document)
    names = {symbol.name for symbol in record.symbols}
    assert {"loadUser", "UserCache", "normalize"} <= names
    assert "./client" in record.imports


def test_extracts_dom_ids_and_inline_javascript():
    document = SourceDocument(
        "index.html",
        """<!doctype html><button id="startButton">Start</button><script>function startGame(){ return true; }</script>""",
    )
    record = extract_symbols(document)
    names = {symbol.name for symbol in record.symbols}
    assert "startButton" in names
    assert "startGame" in names
    assert record.language == "html"


def test_repository_map_counts_incoming_symbol_references():
    documents = [
        SourceDocument("a.py", "def shared():\n    return 1\n"),
        SourceDocument("b.py", "from a import shared\n\ndef run():\n    return shared()\n"),
        SourceDocument("c.py", "from a import shared\n\ndef other():\n    return shared()\n"),
    ]
    repo = build_repository_map(documents)
    assert "shared" in repo.symbol_index
    assert repo.incoming_references["shared"] >= 2


def test_context_ranking_selects_matching_symbol_over_unrelated_file():
    documents = [
        SourceDocument(
            "src/auth.py",
            "def verify_token(token: str) -> bool:\n    return token == 'ok'\n",
        ),
        SourceDocument(
            "src/colors.py",
            "PALETTE = ['red', 'blue']\n",
        ),
    ]
    selection = rank_repository_context(
        "Fix verify_token authentication behavior",
        documents,
        token_budget=500,
    )
    assert selection.items
    assert selection.items[0].path == "src/auth.py"
    assert "verify_token" in selection.items[0].excerpt


def test_failing_path_receives_priority_even_when_query_is_ambiguous():
    documents = [
        SourceDocument("src/a.py", "def alpha():\n    return 1\n"),
        SourceDocument("src/b.py", "def beta():\n    return 2\n"),
    ]
    selection = rank_repository_context(
        "fix the failure",
        documents,
        failing_paths=["src/b.py"],
        token_budget=500,
    )
    assert selection.items[0].path == "src/b.py"
    assert "failing_path" in selection.items[0].reason


def test_context_selection_respects_budget():
    documents = [
        SourceDocument(
            f"src/file_{index}.py",
            "\n".join([f"def target_{index}_{line}(): return {line}" for line in range(20)]),
        )
        for index in range(10)
    ]
    selection = rank_repository_context(
        "target",
        documents,
        token_budget=180,
        max_files=10,
    )
    assert selection.used_tokens <= 180
    assert len(selection.items) < len(documents)
    assert selection.omitted_paths


def test_read_before_edit_requires_exact_revision():
    guard = ReadBeforeEditGuard()
    original = "value = 1\n"
    blocked = guard.decide("config.py", original)
    assert blocked.allowed is False
    assert blocked.reason == "read_required_before_edit"

    digest = guard.record_read("config.py", original)
    allowed = guard.decide("config.py", original)
    assert allowed.allowed is True
    assert allowed.expected_hash == digest

    stale = guard.decide("config.py", "value = 2\n")
    assert stale.allowed is False
    assert stale.reason == "file_changed_since_read"


def test_new_file_can_be_created_without_prior_read():
    guard = ReadBeforeEditGuard()
    decision = guard.decide("new_module.py", "", creating=True)
    assert decision.allowed is True
    assert decision.reason == "new_file"
