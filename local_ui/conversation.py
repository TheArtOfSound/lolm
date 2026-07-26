"""Conversation intelligence for LOLM chat.

The public agent used to treat every prompt as a cold "COMMAND" — including
short replies like "idk", "yes", "no". That produced dictionary definitions,
amnesiac answers, and pointless web searches.

This module:
  * classifies turns (social | dialog | question | task)
  * resolves short / anaphoric follow-ups against conversation history
  * decides when web search should stay off
  * builds proper multi-turn message lists for the writer
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# Pure greetings / thanks — answer directly, no tools, no web.
GREETING_RE = re.compile(
    r"^(hi+|hello+|hey+|yo|sup|howdy|hiya|good\s+(morning|afternoon|evening|day)|"
    r"what'?s\s+up|how\s+are\s+you|how'?s\s+it\s+going|thanks?|thank\s+you|"
    r"ok(ay)?|cool|nice|bye|goodbye|see\s+ya|later)"
    r"\b[\s!,.?]*$",
    re.IGNORECASE,
)

# Short replies that ONLY make sense against prior context.
SHORT_REPLY_RE = re.compile(
    r"^\s*("
    r"i\s*don'?t\s*know|idk|dunno|no\s*idea|not\s*sure|n/?a|"
    r"yes|yep|yeah|yup|yea|sure|ok(ay)?|k|kk|alright|all\s*right|"
    r"no|nope|nah|not\s*really|never|negative|"
    r"maybe|perhaps|i\s*guess|probably|possibly|"
    r"more|go\s*on|continue|keep\s*going|and\s*then|"
    r"why|how|what|when|where|who|which|"
    r"that|this|it|those|these|"
    r"do\s*it|go\s*ahead|please|sounds?\s*good|lgtm|ship\s*it|"
    r"same|again|retry|try\s*again|"
    r"wait|hold\s*on|hmm+|huh|what\?|"
    r"tell\s*me\s*more|explain|simpler|eli5|"
    r"(?:option\s*)?[abc123]|"
    r"the\s+(?:first|second|third|last)(?:\s+one)?|"
    r"(?:first|second|third|last)(?:\s+one)?"
    r")[\s!.?]*$",
    re.IGNORECASE,
)

# Slang / non-answers that must NEVER be treated as definition requests.
UNKNOWN_RE = re.compile(
    r"^\s*(i\s*don'?t\s*know|idk|i\s*dunno|dunno|no\s*idea|not\s*sure|n/?a|"
    r"beats\s*me|no\s*clue|couldn'?t\s*say)\s*[!.?]*\s*$",
    re.IGNORECASE,
)

AFFIRM_RE = re.compile(
    r"^\s*(yes|yep|yeah|yup|yea|sure|ok(ay)?|k|kk|alright|all\s*right|"
    r"do\s*it|go\s*ahead|please|sounds?\s*good|lgtm|ship\s*it|absolutely|"
    r"correct|right|exactly)\s*[!.?]*\s*$",
    re.IGNORECASE,
)

NEGATE_RE = re.compile(
    r"^\s*(no|nope|nah|not\s*really|never|negative|don'?t|"
    r"stop|cancel|never\s*mind|nvm)\s*[!.?]*\s*$",
    re.IGNORECASE,
)

# User picks a lettered/numbered option the assistant offered (A/B/C, 1/2/3, first…).
OPTION_PICK_RE = re.compile(
    r"^\s*(?:"
    r"(?:option\s*)?([abc123])|"
    r"the\s+(first|second|third|last|1st|2nd|3rd)\s*(?:one|option|choice)?|"
    r"(first|second|third|last)\s*(?:one|option|choice)?"
    r")\s*[!.?]*\s*$",
    re.IGNORECASE,
)

QMARKS = "?？¿؟;՞"


def _clean_turns(history: Optional[List[Dict[str, Any]]], limit: int = 12) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    if not isinstance(history, list):
        return out
    for t in history[-limit:]:
        if not isinstance(t, dict):
            continue
        role = "user" if t.get("role") == "user" else "assistant"
        content = str(t.get("content") or "").strip()
        if content:
            out.append({"role": role, "content": content[:2000]})
    return out


def last_role_content(history: Optional[List[Dict[str, Any]]], role: str) -> str:
    for t in reversed(_clean_turns(history, limit=20)):
        if t["role"] == role:
            return t["content"]
    return ""


def is_short_reply(command: str) -> bool:
    c = (command or "").strip()
    if not c or len(c) > 80:
        return False
    if SHORT_REPLY_RE.match(c):
        return True
    # bare 1–3 word follow-ups without a question mark often need context
    words = c.split()
    return len(words) <= 3 and not any(ch in c for ch in QMARKS) and len(c) < 40


def should_skip_web_search(command: str, history: Optional[List[Dict[str, Any]]] = None) -> bool:
    """Web search on every prompt is a major source of dumb answers.

    Skip for social, short dialog follow-ups, pure math-ish one-liners without
    time words, and when the user is clearly continuing a thread with a pronoun.
    """
    c = (command or "").strip()
    if not c:
        return True
    if GREETING_RE.match(c) or is_short_reply(c):
        return True
    profile = classify_command(c, history)
    if profile in ("social", "dialog"):
        return True
    # pure arithmetic / code snippet without research need
    if re.fullmatch(r"[\d\s\+\-\*/\(\)\.=x×÷^%]+", c):
        return True
    time_words = ("today", "latest", "current", "now", "2024", "2025", "2026",
                  "news", "price", "who is the", "ceo of", "released")
    lower = c.lower()
    if any(w in lower for w in time_words):
        return False
    # anaphora + history present → resolve from conversation, not the web
    if history and re.search(r"\b(it|that|this|those|these|he|she|they|them)\b", lower):
        if len(c.split()) <= 12:
            return True
    return False


def classify_command(command: str, history: Optional[List[Dict[str, Any]]] = None) -> str:
    """social | dialog | question | task"""
    c = (command or "").strip()
    if not c:
        return "social"
    if GREETING_RE.match(c):
        return "social"
    words = c.split()
    if len(words) <= 4 and not any(ch in c for ch in QMARKS) and len(c) < 30:
        lowered = c.lower()
        if any(w in lowered for w in (
            "hi", "hello", "hey", "thanks", "thank", "bye", "goodbye", "morning", "evening",
        )):
            return "social"
    # Short follow-ups with history are dialog, not cold tasks.
    if history and is_short_reply(c):
        return "dialog"
    if c.endswith(tuple(QMARKS)) and len(words) <= 20:
        return "question"
    # anaphoric short questions without "?" still dialog if history exists
    if history and len(words) <= 8 and re.search(
        r"\b(it|that|this|those|these|why|how|what about)\b", c, re.I
    ):
        return "dialog"
    return "task"


def resolve_followup(
    command: str,
    history: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[str, str, Optional[str]]:
    """Expand short / anaphoric user turns into a full instruction for the model.

    Returns (effective_user_text, profile, tag).
    The effective text is what the finalizer should answer — still natural language,
    never a dictionary lookup of slang.
    """
    c = (command or "").strip()
    turns = _clean_turns(history)
    profile = classify_command(c, turns)
    if not turns:
        return c, profile, None

    last_asst = last_role_content(turns, "assistant")
    last_user = last_role_content(turns, "user")

    if UNKNOWN_RE.match(c):
        prior = last_asst or last_user
        prior_bit = f'\nYour previous message was:\n"""{prior[:700]}"""\n' if prior else "\n"
        text = (
            f"The user replied with a short 'I don't know' style answer ({c!r})."
            f"{prior_bit}"
            "They are uncertain about YOUR last question — not asking what the slang means.\n"
            "Do this:\n"
            "1) One short acknowledgment (e.g. 'No problem.'). Do NOT define, expand, or gloss the slang.\n"
            "2) Stay on the SAME topic as your previous message.\n"
            "3) Offer 2–3 concrete next options they can pick (A/B/C), or pick a sensible default and proceed.\n"
            "4) One line max of meta. No lectures. No dictionary entries."
        )
        return text, "dialog", "unknown"

    if AFFIRM_RE.match(c):
        prior = last_asst or ""
        text = (
            f'The user affirmed with "{c}".'
            + (f' This is in response to you saying:\n"""{prior[:700]}"""\n' if prior else " ")
            + "Interpret as YES. Proceed with the natural next step you proposed "
            "(or ask one precise confirmation if nothing was proposed). "
            "Do not restart the conversation from scratch."
        )
        return text, "dialog", "affirm"

    if NEGATE_RE.match(c):
        prior = last_asst or ""
        text = (
            f'The user declined with "{c}".'
            + (f' This is in response to:\n"""{prior[:700]}"""\n' if prior else " ")
            + "Interpret as NO. Acknowledge, stop the declined path, and offer a useful alternative."
        )
        return text, "dialog", "negate"

    if OPTION_PICK_RE.match(c) and turns:
        prior = last_asst or last_user
        pick = c.strip()
        text = (
            f'The user selected option "{pick}" from your previous choices.\n'
            + (f'Your previous message (with the options) was:\n"""{prior[:900]}"""\n' if prior else "")
            + "Map their pick onto the matching option (A/B/C, 1/2/3, first/second/third/last). "
            "Proceed with THAT choice only — do not re-list all options unless clarification is needed. "
            "Do not restart the conversation."
        )
        return text, "dialog", "option_pick"

    if profile == "dialog" or (is_short_reply(c) and turns):
        prior = last_asst or last_user
        text = (
            f'User follow-up: "{c}"\n'
            + (f"Recent assistant context:\n\"\"\"{prior[:700]}\"\"\"\n" if prior else "")
            + "Resolve any pronouns (it/that/this) against the conversation. "
            "Answer as a continuous chat — do not ignore prior turns."
        )
        return text, "dialog", "followup"

    return c, profile, None

def build_chat_messages(
    system: str,
    history: Optional[List[Dict[str, Any]]],
    user_text: str,
    *,
    max_turns: int = 12,
) -> List[Dict[str, str]]:
    """Proper multi-turn messages for Claude / OpenAI-style chat APIs."""
    msgs: List[Dict[str, str]] = [{"role": "system", "content": system}]
    for t in _clean_turns(history, limit=max_turns):
        # Skip if the last history user turn is identical to current (avoid dup)
        msgs.append({"role": t["role"], "content": t["content"]})
    # Ensure we end with the current user text
    if not msgs or msgs[-1].get("role") != "user" or msgs[-1].get("content") != user_text:
        # If history already ends with this exact user content, still append resolved text
        msgs.append({"role": "user", "content": user_text})
    # API requirement: first non-system should be user
    if len(msgs) >= 2 and msgs[1]["role"] != "user":
        msgs.insert(1, {"role": "user", "content": "(continuing conversation)"})
    return msgs


DIALOG_SYSTEM = (
    "You are LOLM, a capable continuous assistant in an ongoing conversation. "
    "Rules:\n"
    "1. Use prior turns. Resolve pronouns and short replies against context.\n"
    "2. If the user says idk / I don't know / dunno, they are declining knowledge — "
    "help them forward. Never define the slang.\n"
    "3. Be direct, specific, and useful. Prefer actions and options over lectures.\n"
    "4. Do not invent that you lack conversation history when history is present.\n"
    "5. Keep answers tight unless the user asked for depth.\n"
    "6. If you previously asked a question and they answered, advance the thread."
)
