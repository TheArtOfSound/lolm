"""Import your own notes into the LOLM-NFET workspace memory.

Point this at a folder of markdown/text files (an Obsidian vault, a notes
directory, a docs folder) and the agent gains a private, local knowledge
base — its retrieve action starts finding *your* facts when its uncertainty
spikes. Nothing leaves your machine.

    PYTHONPATH=. python scripts/import_notes.py ~/notes
    PYTHONPATH=. python scripts/import_notes.py ~/vault --tag work --min-chars 40

Splitting: files are split on markdown headings and blank-line paragraph
gaps, so one note ≈ one fact/claim/section — the granularity the agent's
keyword retrieval works best with. YAML frontmatter `tags:` are honoured.
Re-running is safe: notes are deduplicated by content hash.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

SUPPORTED = {".md", ".markdown", ".txt", ".text"}
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)


def parse_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    """Extract a minimal {key: value} dict from YAML-ish frontmatter."""
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    meta: Dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip().lower()] = value.strip().strip("\"'")
    return meta, text[match.end():]


def split_into_chunks(text: str, min_chars: int, max_chars: int) -> Iterator[str]:
    """Heading-aware paragraph chunks sized for keyword retrieval."""
    sections = re.split(r"(?=^#{1,6}\s)", text, flags=re.MULTILINE)
    for section in sections:
        section = section.strip()
        if not section:
            continue
        heading = ""
        head_match = HEADING_RE.match(section)
        if head_match:
            heading = head_match.group(1).strip()
            section = section[head_match.end():].strip()
        for para in re.split(r"\n\s*\n", section):
            para = re.sub(r"\s+", " ", para).strip()
            if len(para) < min_chars:
                continue
            prefix = f"{heading}: " if heading and not para.lower().startswith(heading.lower()) else ""
            chunk = (prefix + para)[:max_chars]
            yield chunk


def guess_importance(chunk: str) -> int:
    """3 = default; 4 for definition/decision-looking notes; 2 for logs."""
    lowered = chunk.lower()
    if re.search(r"\b(is defined as|means|always|never|must|rule:|decision:|important)\b", lowered):
        return 4
    if re.search(r"\b(todo|log|journal|yesterday|today i)\b", lowered):
        return 2
    return 3


def iter_files(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED and not path.name.startswith("."):
            yield path


def existing_hashes(notes_path: Path) -> set:
    seen = set()
    if not notes_path.exists():
        return seen
    for line in notes_path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        digest = row.get("content_hash")
        if digest:
            seen.add(digest)
        else:
            seen.add(hashlib.sha256(row.get("text", "").encode()).hexdigest()[:16])
    return seen


def import_folder(root: Path, memory, *, tag: Optional[str] = None,
                  min_chars: int = 60, max_chars: int = 600,
                  limit: Optional[int] = None) -> Dict[str, int]:
    """Import a folder into a MemoryStore. Returns counters."""
    seen = existing_hashes(memory.paths.notes)
    stats = {"files": 0, "chunks": 0, "imported": 0, "duplicates": 0}
    for path in iter_files(root):
        stats["files"] += 1
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        meta, body = parse_frontmatter(raw)
        file_tag = tag or (meta.get("tags", "").split(",")[0].strip().strip("[]") or None) or path.parent.name or "note"
        for chunk in split_into_chunks(body, min_chars, max_chars):
            stats["chunks"] += 1
            digest = hashlib.sha256(chunk.encode()).hexdigest()[:16]
            if digest in seen:
                stats["duplicates"] += 1
                continue
            seen.add(digest)
            memory._append_line(memory.paths.notes, {
                "id": digest[:8],
                "ts": time.time(),
                "tag": file_tag[:40],
                "importance": guess_importance(chunk),
                "text": chunk,
                "source": str(path.name),
                "content_hash": digest,
            })
            stats["imported"] += 1
            if limit and stats["imported"] >= limit:
                return stats
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a notes folder into the workspace memory.")
    parser.add_argument("folder", help="folder of .md/.txt notes (searched recursively)")
    parser.add_argument("--data-dir", default=None, help="workspace data dir (default: local_ui/data)")
    parser.add_argument("--tag", default=None, help="force one tag for every imported note")
    parser.add_argument("--min-chars", type=int, default=60)
    parser.add_argument("--max-chars", type=int, default=600)
    parser.add_argument("--limit", type=int, default=None, help="stop after N imported notes")
    args = parser.parse_args()

    root = Path(args.folder).expanduser()
    if not root.is_dir():
        raise SystemExit(f"not a folder: {root}")

    from local_ui.memory_store import MemoryStore
    data_dir = Path(args.data_dir) if args.data_dir else Path(__file__).resolve().parents[1] / "local_ui" / "data"
    memory = MemoryStore(data_dir)
    stats = import_folder(root, memory, tag=args.tag, min_chars=args.min_chars,
                          max_chars=args.max_chars, limit=args.limit)
    print(json.dumps(stats, indent=2))
    print(f"\nMemory now at: {memory.paths.notes}")
    print("Run the agent against it:  make agent-ui   then POST /api/agent/nfet/run")


if __name__ == "__main__":
    main()
