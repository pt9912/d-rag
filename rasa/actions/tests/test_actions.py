import types

import pytest
from rasa_sdk.events import SlotSet

from actions import actions as act


class DummyDispatcher:
    def __init__(self) -> None:
        self.messages = []

    def utter_message(self, text=None, response=None):
        self.messages.append({"text": text, "response": response})


class DummyTracker:
    def __init__(self, text: str, slots=None) -> None:
        self.latest_message = {"text": text}
        self._slots = slots or {}

    def get_slot(self, key):
        return self._slots.get(key)


def test_action_query_rag_builds_payload_and_updates_slots(monkeypatch):
    dispatcher = DummyDispatcher()
    tracker = DummyTracker(
        "Wie deploye ich das?",
        {
            "topic": "deployment",
            "doc_type": "adr",
            "roles": ["dev"],
            "conversation_history": [
                {"user": "u0", "bot": "b0"},
                {"user": "u1", "bot": "b1"},
                {"user": "u2", "bot": "b2"},
            ],
        },
    )

    captured = {}

    class DummyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"answer": "Antwort"}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return DummyResponse()

    monkeypatch.setattr(act, "httpx", types.SimpleNamespace(post=fake_post))
    monkeypatch.setattr(act, "HISTORY_LIMIT", 2)

    events = act.ActionQueryRag().run(dispatcher, tracker, {})

    assert captured["url"].endswith("/query")
    assert captured["json"]["topic"] == "deployment"
    assert captured["json"]["doc_type"] == "adr"
    assert captured["json"]["roles"] == ["dev"]
    assert len(captured["json"]["history"]) == 2  # trimmed to limit
    assert dispatcher.messages[0]["text"] == "Antwort"

    history_event = next(
        evt
        for evt in events
        if isinstance(evt, SlotSet) and evt.key == "conversation_history"
    )
    assert len(history_event.value) == 2
    assert history_event.value[-1]["user"] == "Wie deploye ich das?"


def test_action_query_rag_handles_failure_sets_pending(monkeypatch):
    dispatcher = DummyDispatcher()
    tracker = DummyTracker("?", {"conversation_history": []})

    def fake_post(url, json, timeout):
        raise Exception("boom")

    monkeypatch.setattr(act, "httpx", types.SimpleNamespace(post=fake_post))
    monkeypatch.setattr(act, "RAG_RETRIES", 0)

    events = act.ActionQueryRag().run(dispatcher, tracker, {})

    pending = next(
        evt for evt in events if isinstance(evt, SlotSet) and evt.key == "pending_clarification"
    )
    assert pending.value is True
    assert dispatcher.messages[0]["response"] == "utter_rag_unavailable"


def test_validate_rag_form_normalizes_and_prompts(monkeypatch):
    dispatcher = DummyDispatcher()
    tracker = DummyTracker("", {})
    domain = {}
    form = act.ValidateRagForm()

    assert form.validate_topic("  deployment  ", dispatcher, tracker, domain) == {"topic": "deployment"}
    assert form.validate_doc_type("  ", dispatcher, tracker, domain) == {"doc_type": None}
    assert dispatcher.messages[-1]["response"] == "utter_ask_doc_type"

    assert form.validate_roles("dev, admin;ops", dispatcher, tracker, domain) == {
        "roles": ["dev", "admin", "ops"]
    }
