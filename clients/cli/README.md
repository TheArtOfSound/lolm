# lolm-cli

Command-line client for the [LOLM agent](https://lolm.imagineqira.com). Run a coding
task in a network-isolated sandbox, watch the real write → run → read-the-error → fix
loop, and end with a sealed receipt of what actually happened.

```bash
npx lolm-cli code "write fizzbuzz to 20 in solution.py and run it" --save ./out
```

```
· step 1/10
  write  solution.py (218b)
  run    python3 -m py_compile solution.py [verify]
         exit 0
  run    python3 solution.py
         exit 0
         │ 1
         │ 2
         │ Fizz

saved 1 file(s) → ./out

verdict   shipped
files     solution.py
runs      2 green / 0 failed
receipt   0f5e12f682d212b438a7d3ba
```

The package is `lolm-cli`; the command it installs is `lolm`. (npm rejects the bare
name `lolm` as too similar to existing packages.)

No API key needed for the free tier. Nothing is installed globally unless you want it:

```bash
npm install -g lolm-cli   # installs the `lolm` command
# or run it without installing:  npx lolm-cli <command>
```

## Commands

| Command | What it does |
|---|---|
| `lolm code <task>` | Agentic coding loop in a jail. `--save <dir>` writes the files it produced. |
| `lolm ask <question>` | Streams an answer plus the control decisions made while writing it. |
| `lolm build <app>` | Builds a self-contained HTML app. `-o <file>` (default `lolm-app.html`). |
| `lolm receipts` | Recent sealed receipts from the public audit ledger. |
| `lolm status` | Model/API status and current run limits. |
| `lolm memory list\|add\|forget` | Durable facts the agent remembers about you. |

## Flags

| Flag | Meaning |
|---|---|
| `--base <url>` | API base. Defaults to the hosted instance, or `$LOLM_BASE_URL`. Point it at your own box. |
| `--save <dir>` | `code`: write the produced files to disk. |
| `-o, --out <file>` | `build`: output path. |
| `--max-steps <n>` | `code`: cap the loop. |
| `--limit <n>` | `receipts`: row count. |
| `--json` | Machine-readable stdout; progress moves to stderr. |
| `-q, --quiet` | Outcome only, no live loop. |

## Exit codes

`lolm code` is safe to put in a script — it exits **non-zero unless the delivered code
actually compiled and ran**:

| Code | Meaning |
|---|---|
| 0 | Receipt verdict `shipped` |
| 1 | Run finished but the code was incomplete, broken, or the request failed |
| 2 | Usage error (unknown command or flag, missing argument) |

```bash
lolm code "$TASK" --save ./out --json | jq -r '.done.receipt.verdict'
```

## What the receipt covers

Every `code` run ends with a hashed record of the files written, the commands run,
their real exit codes, and whether the delivered code compiles. The syntax verdict is
inside the hashed core, so the seal covers it — a tree that does not compile is
reported as `broken`, never as `shipped`.

## Honest limits

- **The sandbox has no network and no pip.** Standard library only, no servers, no GUI.
  The task must run and exit in about 20 seconds. `pytest` is not available; ask for
  `unittest` if you want tests.
- **`--save` replays the streamed diffs**, and the API truncates each diff at 2500
  characters. For a large file the full body never arrives, so that file is *skipped
  with a reason* rather than written as corrupt content. Small and medium files
  reconstruct exactly.
- **This is a 70B-class model**, not a frontier coding model. On an internal 12-task
  hidden-test benchmark the agent scores about 61% — good for well-specified single-file
  work and small bug fixes, well short of a frontier coding agent on hard multi-file
  tasks. The receipt tells you which kind of run you got.

## Self-hosting

Point `--base` at your own instance and everything works the same:

```bash
LOLM_BASE_URL=http://localhost:7866 lolm status
```

## Library

For programmatic use, [`lolm-nfet-client`](https://www.npmjs.com/package/lolm-nfet-client)
is the underlying library this CLI wraps.

---

MIT © 2026 Qira LLC · [lolm.imagineqira.com](https://lolm.imagineqira.com) · patent pending
