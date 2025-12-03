import os
from typing import Any, Dict, List, Optional, Text

import httpx
from rasa_sdk import Action, FormValidationAction, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import EventType, SlotSet
from rasa_sdk.types import DomainDict

RAG_ENDPOINT = os.getenv("RAG_ENDPOINT", "http://rag-service:8000")
RAG_TIMEOUT_SECONDS = float(os.getenv("RAG_TIMEOUT_SECONDS", "5.0"))
RAG_RETRIES = int(os.getenv("RAG_RETRIES", "1"))
HISTORY_LIMIT = int(os.getenv("RAG_HISTORY_LIMIT", "5"))
METRICS_PORT = int(os.getenv("METRICS_PORT", "8001"))

try:  # optional Prometheus metrics
    from prometheus_client import Counter, start_http_server

    rag_calls_total = Counter("rag_calls_total", "RAG calls by status", ["status"])
    start_http_server(METRICS_PORT)
except Exception:
    rag_calls_total = None


def _inc_metric(status: str) -> None:
    if rag_calls_total:
        rag_calls_total.labels(status=status).inc()


def _trim_history(history: Optional[List[Dict[str, str]]]) -> List[Dict[str, str]]:
    if not history:
        return []
    return history[-HISTORY_LIMIT:]


def _append_history(
    history: Optional[List[Dict[str, str]]], question: str, answer: str
) -> List[Dict[str, str]]:
    current = history[:] if history else []
    current.append({"user": question, "bot": answer})
    return _trim_history(current)


def _normalize_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_roles(value: Any) -> Optional[List[str]]:
    if value is None:
        return None
    if isinstance(value, list):
        roles = [str(item).strip() for item in value if str(item).strip()]
    else:
        roles = [part.strip() for part in str(value).replace(";", ",").split(",") if part.strip()]
    return roles or None


class ActionQueryRag(Action):
    def name(self) -> Text:
        return "action_query_rag"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: DomainDict,
    ) -> List[EventType]:
        question = _normalize_text(tracker.latest_message.get("text"))
        history = tracker.get_slot("conversation_history") or []
        topic = tracker.get_slot("topic")
        doc_type = tracker.get_slot("doc_type")
        roles = tracker.get_slot("roles")

        if not question:
            dispatcher.utter_message(text="Ich habe keine Frage erkannt.")
            return []

        payload: Dict[str, Any] = {"question": question}
        if topic:
            payload["topic"] = topic
        if doc_type:
            payload["doc_type"] = doc_type
        if roles:
            payload["roles"] = roles
        trimmed_history = _trim_history(history)
        if trimmed_history:
            payload["history"] = trimmed_history

        answer: Optional[str] = None
        error: Optional[str] = None

        for attempt in range(RAG_RETRIES + 1):
            try:
                response = httpx.post(
                    f"{RAG_ENDPOINT}/query",
                    json=payload,
                    timeout=RAG_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                data = response.json()
                answer = _normalize_text(data.get("answer"))
                _inc_metric("ok")
                break
            except Exception as exc:  # pragma: no cover - runtime path
                error = str(exc)
                if attempt == RAG_RETRIES:
                    _inc_metric("error")

        events: List[EventType] = []

        if answer:
            dispatcher.utter_message(text=answer)
            events.extend(
                [
                    SlotSet("last_answer", answer),
                    SlotSet("conversation_history", _append_history(history, question, answer)),
                    SlotSet("pending_clarification", False),
                    SlotSet("expected_slot", None),
                ]
            )
            return events

        dispatcher.utter_message(response="utter_rag_unavailable")
        events.extend(
            [
                SlotSet("pending_clarification", True),
                SlotSet("expected_slot", None),
            ]
        )
        if error:
            print(f"[action_query_rag] RAG-Call failed: {error}")
        return events


class ValidateRagForm(FormValidationAction):
    def name(self) -> Text:
        return "validate_rag_form"

    def validate_topic(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: DomainDict,
    ) -> Dict[Text, Any]:
        topic = _normalize_text(slot_value)
        if topic:
            return {"topic": topic}
        dispatcher.utter_message(response="utter_ask_topic")
        return {"topic": None}

    def validate_doc_type(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: DomainDict,
    ) -> Dict[Text, Any]:
        doc_type = _normalize_text(slot_value)
        if doc_type:
            return {"doc_type": doc_type}
        dispatcher.utter_message(response="utter_ask_doc_type")
        return {"doc_type": None}

    def validate_roles(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: DomainDict,
    ) -> Dict[Text, Any]:
        roles = _normalize_roles(slot_value)
        if roles:
            return {"roles": roles}
        dispatcher.utter_message(response="utter_ask_roles")
        return {"roles": None}


class ActionResetContext(Action):
    def name(self) -> Text:
        return "action_reset_context"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: DomainDict,
    ) -> List[EventType]:
        return [
            SlotSet("topic", None),
            SlotSet("doc_type", None),
            SlotSet("roles", None),
            SlotSet("conversation_history", []),
            SlotSet("last_answer", None),
            SlotSet("pending_clarification", False),
            SlotSet("expected_slot", None),
        ]


class ActionAcknowledgeClarification(Action):
    def name(self) -> Text:
        return "action_acknowledge_clarification"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: DomainDict,
    ) -> List[EventType]:
        dispatcher.utter_message(text="Danke, ich passe die Suche entsprechend an.")
        return [SlotSet("pending_clarification", False)]
