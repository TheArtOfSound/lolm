"""Conversation intelligence — short replies must not become dictionary lookups."""
from local_ui.conversation import (
    classify_command, resolve_followup, should_skip_web_search, is_short_reply, build_chat_messages,
)

HIST = [
    {"role": "user", "content": "Fix conversation or coding first?"},
    {"role": "assistant", "content": "Conversation first. Want me to prioritize that?"},
]

def test_idk_is_dialog():
    assert is_short_reply("idk")
    assert classify_command("idk", HIST) == "dialog"
    assert should_skip_web_search("idk", HIST)

def test_idk_resolve_no_dictionary():
    cmd, prof, tag = resolve_followup("idk", HIST)
    assert prof == "dialog" and tag == "unknown"
    assert "NEVER" in cmd or "Do NOT define" in cmd or "do not define" in cmd.lower() or "Do NOT define" in cmd or "not asking what the slang" in cmd
    assert "dictionary" in cmd.lower() or "slang" in cmd.lower()

def test_yes_affirm():
    cmd, prof, tag = resolve_followup("yes", HIST)
    assert tag == "affirm"


def test_do_that_and_go_for_it_affirm():
    assert resolve_followup("do that", HIST)[2] == "affirm"
    assert resolve_followup("go for it", HIST)[2] == "affirm"

def test_greeting_social():
    assert classify_command("Hello!") == "social"
    assert should_skip_web_search("Hello!")

def test_research_still_searches():
    assert should_skip_web_search("Who is the CEO of OpenAI today?") is False

def test_multiturn_messages():
    msgs = build_chat_messages("sys", HIST, "idk")
    assert msgs[0]["role"] == "system"
    assert msgs[-1]["role"] == "user"


def test_option_pick_a_b_c():
    hist = [
        {"role": "user", "content": "What should we build?"},
        {"role": "assistant", "content": "Pick one: A) chat fix  B) coding loop  C) pricing"},
    ]
    cmd, prof, tag = resolve_followup("B", hist)
    assert prof == "dialog" and tag == "option_pick"
    assert "option" in cmd.lower() and "B" in cmd
    cmd2, _, tag2 = resolve_followup("the second one", hist)
    assert tag2 == "option_pick"
    assert "second" in cmd2.lower()

def test_short_option_is_short_reply():
    assert is_short_reply("A")
    assert is_short_reply("the first one")
