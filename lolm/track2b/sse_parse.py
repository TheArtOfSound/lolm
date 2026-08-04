# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Robust SSE frame parser (split/multiline data fields)."""

from __future__ import annotations

import json
from typing import Any, Dict, Iterator, List, Optional, Tuple


def parse_sse_chunk(
    buffer: str,
    chunk: str,
) -> Tuple[str, List[Dict[str, Any]]]:
    """Append chunk to buffer; return (remainder, complete events).

    Supports:
    * ``event:`` + single or multi-line ``data:``
    * blank-line frame terminator
    * frames split across TCP chunks
    """
    buffer = (buffer or "") + (chunk or "")
    events: List[Dict[str, Any]] = []
    while "\n\n" in buffer or "\r\n\r\n" in buffer:
        if "\r\n\r\n" in buffer and (
            "\n\n" not in buffer or buffer.index("\r\n\r\n") < buffer.index("\n\n")
        ):
            frame, buffer = buffer.split("\r\n\r\n", 1)
        else:
            frame, buffer = buffer.split("\n\n", 1)
        ev = _parse_frame(frame)
        if ev is not None:
            events.append(ev)
    return buffer, events


def _parse_frame(frame: str) -> Optional[Dict[str, Any]]:
    if not frame or frame.strip().startswith(":"):
        return None
    event_name = "message"
    data_lines: List[str] = []
    for raw in frame.replace("\r\n", "\n").split("\n"):
        if raw.startswith("event:"):
            event_name = raw[6:].strip() or "message"
        elif raw.startswith("data:"):
            # Spec: optional single leading space after data:
            line = raw[5:]
            if line.startswith(" "):
                line = line[1:]
            data_lines.append(line)
        elif raw.startswith("id:") or raw.startswith("retry:"):
            continue
        elif raw.startswith(":"):
            continue
    if not data_lines:
        return None
    data_raw = "\n".join(data_lines)
    try:
        data = json.loads(data_raw) if data_raw else {}
    except json.JSONDecodeError:
        data = {"_raw": data_raw, "_json_error": True}
    return {"event": event_name, "data": data if isinstance(data, dict) else {"value": data}}


def iter_sse_events(byte_iter: Iterator[bytes], *, encoding: str = "utf-8") -> Iterator[Dict[str, Any]]:
    buf = ""
    for chunk in byte_iter:
        text = chunk.decode(encoding, errors="replace") if isinstance(chunk, (bytes, bytearray)) else str(chunk)
        buf, events = parse_sse_chunk(buf, text)
        for ev in events:
            yield ev
    # trailing frame without final blank line — ignore incomplete
