# Rasa-Dialogmanagement (Variante 2: Kontextuelle Gesprächsführung) – Design
Version: 0.4 (archiviert; Design implementiert, Pflege findet im Code statt; Änderungen bitte im Header hochzählen; Tracking via Git-Commits, optional `docs/CHANGELOG.md`)

## Kurzfassung
- Dialog-Flow über Rasa Core mit Slots, Forms und Custom Actions; RAG-Aufrufe nutzen Kontext aus Slots/History.
- Policies: Rule/Memoization für deterministische Pfade, TED (80–120 Epochen) für prädiktive Schritte, zweistufiges Fallback.
- Action-Server ruft RAG `/query` mit History/Slots auf, liefert Metriken (Prometheus) und Fallbacks bei Fehlern.
- Tests: NLU/Core/E2E + Action-Server-Unit-Tests mit RAG-Mocks; Risiken betreffen Session-Expiry, RAG-Timeouts, History-Größe.
- Status: Umsetzung liegt in `rasa/` (Config/Domain/Data/Actions); Unit-Tests für Actions vorhanden, NLU/Core/E2E-Tests stehen noch aus.

## Ziel & Scope
- **Ziel:** Rasa Core für mehrturnige, kontextuelle Gespräche nutzen. Der Bot behält Gesprächszustand, Slots und Verlauf, entscheidet per Policies, wann RAG aufgerufen oder eine Rückfrage gestellt wird.
- **Scope:** Stories/Rules, Slots, Policies, Forms/Slot-Filling, Custom Actions für RAG-Aufrufe. Transport primär `webhooks/rest/webhook`. Optionale Integration über den bestehenden Node-Bot als dünne Proxy-Schicht.
- **Nicht im Scope:** UI/Frontend, mehrsprachiges Modell, Voice, LangChain-ähnliche Planner, Agentic Tools über Rasa hinaus.
- **Terminologie:** Technische Begriffe wie `TEDPolicy` und `RulePolicy` bleiben auf Englisch, da sie Rasa-Bezeichner sind.

## Ausgangslage
- Aktuell Intent-only NLU (siehe `docs/archive/rasa-intent-only.md`, Historie in `docs/archive/rasa-intent-only.md`), Bot routet anhand des erkannten Intents und ruft RAG direkt.
- Kein Dialogzustand, kein Slot-Filling, keine Policies/Stories. Rasa Action-Server nicht aktiviert.

## Abhängigkeiten & Annahmen
- RAG-Service stellt `/query` mit Payload `{ question, roles?, topic?, doc_type?, history? }` bereit (aktuell in `docs/archive/rasa-intent-only.md` beschrieben); Schnittstelle gilt hier als fix.
- Node-Bot (falls genutzt) kann HTTP-Header für Rollen weiterreichen und 1:1 proxien; kein eigenes Intent-Routing mehr nötig.
- Trainings-/Testdaten für neue Intents (`affirm`, `deny`, `provide_*`) liegen vor oder werden im Rahmen dieses Designs erstellt.
- Cross-Links: Historie/Alt-Design siehe `docs/archive/rasa-intent-only.md`; Änderungen hier sollten dort vermerkte Annahmen ablösen.
- Daten-Plan für Trainingsdaten: siehe `docs/data-plan.md` (Quellen, Volumen, Abdeckung der neuen Intents/Entities).

## Zielverhalten (Happy Path)
1. Client spricht Rasa über `/webhooks/rest/webhook` an (oder Node-Bot proxied identisch).
2. NLU erkennt Intent + Entities, Policies wählen nächste Aktion.
3. Bei fachlichen Fragen (`ask_rag`) löst eine Custom Action den Aufruf des RAG-Service aus, nutzt Slots (z. B. `topic`, `doc_type`, `roles`, `history`) als Kontext/Filter.
4. Nach der Antwort können Folgefragen den bisherigen Kontext (Slots + letzter Antworttext) nutzen; kein erneutes Abfragen von Rollen nötig, falls bereits gesetzt.
5. Fallbacks (`nlu_fallback`, `out_of_scope`, niedrige Confidence) führen zu Klarstellungsfragen oder direktem RAG-Fallback (konfigurierbar).

## Architektur & Komponenten
- **NLU-Pipeline:** Analog Intent-only (WhitespaceTokenizer, RegexFeaturizer, LexicalSyntactic, CountVectors word+char, DIET, EntitySynonymMapper, FallbackClassifier). Optional spätere Umstellung auf spaCy (`de_core_news_md`) für bessere Entitäten.
- **Policies:**  
  - `RulePolicy` für deterministische Pfade (Greet/Goodbye/Thank, Fallback-Antworten, Form-Activation).  
  - `MemoizationPolicy` für bekannte Stories.  
  - `TEDPolicy` (80–120 Epochen; Erfahrungswert für kleine deutsche Domänen, Spielraum für Fein-Tuning nach ersten Tests) für prädiktive Dialogschritte.
  - `FallbackClassifier` + Rule-basiertes Fallback (zweistufig: NLU-Fallback → Klärungsfrage, Core-Fallback → RAG).
- **Domain/Slots:**  
  - Intents: `ask_rag`, `greet`, `goodbye`, `help`, `thank`, `out_of_scope`, `affirm`, `deny`, `provide_topic`, `provide_doc_type`, `provide_role` (optional).  
  - Entities: `topic`, `doc_type`, `role`, `name` (optional für Personalisierung).  
  - Slots (type `text`/`list`): `topic`, `doc_type`, `roles`, `last_answer`, `conversation_history` (list of strings), `pending_clarification` (bool), `expected_slot` (text).  
  - Responses: statische Antworten für Small-Talk und Klärungsfragen.
- **Forms / Slot-Filling:**  
  - `rag_form` fordert fehlende Slots an (z. B. `topic`, `doc_type`, optional `roles`).  
  - Validierung im Action-Server (`validate_rag_form`) normalisiert Werte, mappt Synonyme.
- **Custom Actions (Action-Server):**  
  - `action_query_rag`: Baut Payload aus Slots (`question`, `topic`, `doc_type`, `roles`, `history`), ruft RAG `/query` auf, speichert Antwort in `last_answer`, hängt Query/Antwort an `conversation_history`.  
  - `action_reset_context`: Löscht Slots/History bei `goodbye` oder explizitem Reset.  
  - Optional: `action_acknowledge_clarification` für Flow nach Fallback-Fragen.
- **Transport:**  
  - Primär `POST /webhooks/rest/webhook` (standard Rasa REST), Client erhält Liste von Messages.  
  - Alternativ: Node-Bot proxied Requests 1:1 an Rasa REST (kein eigenes Routing mehr nötig).

## Datenmodell & Slot-Strategie
- **Slots:**  
  - `roles` (list): Aggregiert aus User-Eingaben oder Header-Forwarding des Proxys.  
  - `topic`/`doc_type`: Text-Slots, füllen sich aus Entitäten oder Form-Eingaben.  
  - `conversation_history`: Liste der letzten N QA-Paare (N=3–5; Balancing zwischen Token-Budget und Kontexttreue) für RAG-Payload; bei Überschreitung wird FIFO getrimmt.  
  - `last_answer`: Für Nachfragen wie „Erzähl mehr dazu“.  
  - `pending_clarification`: Steuert, ob Klärungsfrage aktiv ist.  
  - `expected_slot`: Merkt, welches Feld als nächstes gefragt werden soll.
- **Slot-Persistenz:** Session-Config mit `session_expiration_time` (z. B. 60 min, Anpassung an Session-Timeout des Clients) und `carry_over_slots_to_new_session: true`, außer `conversation_history` (kann bei Sessionwechsel geleert werden, um Token-Budget zu schützen).

## Stories & Rules (Beispiele)
- **Rules:**  
  - Greet → `utter_greet`.  
  - Goodbye → `utter_goodbye` + `action_reset_context`.  
  - Thank → `utter_thank`.  
  - Help → `utter_help`.  
  - NLU-Fallback → `utter_ask_rephrase` (erste Stufe), Core-Fallback → `action_query_rag` (zweite Stufe).  
  - Activate `rag_form` wenn `ask_rag` mit fehlenden Slots erkannt wird.
- **Stories:**  
  - Happy Path: `ask_rag` (mit Entities) → `action_query_rag` → `utter_answer_rag`.  
  - Slot-Filling: `ask_rag` (ohne Entities) → `rag_form` → `action_query_rag`.  
  - Nachfragen: `ask_rag` → `action_query_rag` → User stellt Nachfrage (`ask_rag`/`out_of_scope`/`affirm`) → `action_query_rag` mit `conversation_history`.  
  - Abbruch: User `deny` während Form → `utter_cancel` + `action_reset_context`.

## Action-Server Design
- **Tech:** `rasa/rasa-sdk:3.6` als separater Service (Compose) oder integrierter Container.  
- **Endpoints:** `endpoints.yml` zeigt auf `http://action-server:5055/webhook`.  
- **RAG-Aufruf:** HTTP-POST `RAG_ENDPOINT/query` mit Payload `{ question, roles?, topic?, doc_type?, history? }`. History als Array von {user, bot} Strings oder letztem Antworttext.  
- **Fehlerbehandlung:** Timeouts (3–5 s), Retries (1 kurzer Retry), Fallback-Response: `utter_rag_unavailable` + optionaler erneuter Versuch.  
- **Logging/Metriken:** JSON-Logs pro Action; optional Prometheus-Counter für Action-Erfolge/Fehler. Beispiel:

```python
from typing import Text

from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.types import DomainDict
from prometheus_client import Counter, start_http_server

rag_calls_total = Counter("rag_calls_total", "RAG-Aufrufe", ["status"])
start_http_server(8001)  # Scrape-Pfad /metrics

class ActionQueryRag(Action):
    def name(self) -> Text:
        return "action_query_rag"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: DomainDict,
    ):
        try:
            # ... Payload bauen, Request senden ...
            rag_calls_total.labels(status="ok").inc()
        except Exception:
            rag_calls_total.labels(status="error").inc()
            raise
```

- **Metrik-Auswertung/Alerts:** Beispiel-Alert in Prometheus: `sum(rate(rag_calls_total{status="error"}[5m])) / sum(rate(rag_calls_total[5m])) > 0.05` (Fehlerquote >5% über 5 Minuten). Grafana-Panels: Counter nach Status (Bar), Error-Rate (Single-Stat), und Latenz sobald ein Histogramm ergänzt wird.

## Config-Vorschlag (Auszug)
- `config.yml`:  
  - Pipeline wie Intent-only, Threshold FallbackClassifier 0.7.  
  - Policies: `RulePolicy`, `MemoizationPolicy`, `TEDPolicy` (epochs 80–120, max_history 5), `FallbackClassifier`.  
- `domain.yml`:  
  - Intents/Entities/Slots wie oben, Forms `rag_form`, Responses (Greet/Help/Goodbye/Thank, Ask Topic/DocType, Fallback, RAG unavailable).  
  - Actions: `action_query_rag`, `validate_rag_form`, `action_reset_context`, optional `action_acknowledge_clarification`.  
- `data/`:  
  - `nlu.yml` erweitert um Affirm/Deny/Provide-* Intents.  
  - `rules.yml` für deterministische Flows, `stories.yml` für Happy/Edge Paths.

## Betrieb & Migration
- **Option A (reiner Rasa-Endpoint):** Clients sprechen direkt `/webhooks/rest/webhook` an; Node-Bot wird obsolet oder dient nur als Reverse Proxy/Guard.  
- **Option B (Bot als Proxy):** Bot leitet `/ask` an Rasa REST durch, ergänzt Header-Rollen, konvertiert Rasa-Responses in das bestehende `{answer, contexts}`-Schema.  
- **Training:** `docker compose run --rm --user 1000:1000 rasa train` (inkl. Stories/Rules). Action-Server muss bereitstehen, wenn `rasa test` oder Bot-Proxy läuft.  
- **Deployment:** Zusätzlicher Service `action-server` in `docker-compose.yml`. Prometheus-Scrape für Bot bleibt; Rasa selbst liefert keine Prometheus-Metriken out-of-the-box.

## Fallback-Strategie
- Stufe 1: NLU-Fallback → `utter_ask_rephrase`.  
- Stufe 2: Core-Fallback oder wiederholter NLU-Fallback → `action_query_rag` als Best-Effort.  
- Stufe 3: RAG-Fehler → `utter_rag_unavailable`.  
- Konfigurierbare Confidence-Thresholds per Env (`NLU_CONFIDENCE_THRESHOLD`), maximale Anzahl Klärungsversuche (z. B. 2) bevor RAG-Fallback.

## Security & Governance
- CORS: Rasa `--cors` auf bekannte Origins beschränken.  
- Rate-Limits für `/model/parse` und `/webhooks/rest/webhook` via Upstream-Proxy.  
- Input-Validierung im Action-Server (Whitelist/Max-Längen für Slots/History).  
- Logging: Keine sensiblen Inhalte persistieren, History begrenzen.

## Test-Plan (High-Level)
- Aktueller Stand: Action-Server-Unit-Tests liegen unter `rasa/actions/tests/test_actions.py`; NLU/Core/E2E-Tests sind noch zu ergänzen.
- **Kurzfassung:** NLU/Core-Tests ausführen, E2E-REST-Flows für Happy/Slot-Filling/Fallback abdecken, Action-Server mit RAG-Mocks auf Payload/History/Retry/Metriken testen.
- **NLU:** `rasa test nlu` auf neuen Intents.  
- **Core:** `rasa test core` mit Stories.  
- **E2E:** `curl /webhooks/rest/webhook` mit Beispielen (Payload immer `{ "sender": "test", "message": "<Text>" }`):  
  - Frage mit Entities → direkte RAG-Antwort. Beispiel: `{"message": "Welche Policies nutzt ihr für Rasa?"}`.  
  - Frage ohne Entities → Form fragt nach Topic/DocType, dann RAG. Beispiel-Sequence:  
    1. `{"message": "Erzähl mir was zu RAG"}` → Bot fragt nach `topic`.  
    2. `{"message": "Architektur"}` → Bot fragt nach `doc_type`.  
    3. `{"message": "ADR"}` → Bot ruft RAG auf.  
  - Nachfrage nutzt History: `{"message": "Erzähl mehr dazu"}` direkt nach einer RAG-Antwort → `conversation_history` enthält letzte QA.  
  - Fallback-Sätze: `{"message": "asdasd"}` → `utter_ask_rephrase`; wiederholt → `action_query_rag`.  
- **Action-Server:** Unit-Tests mit Mocks für den RAG-Endpoint: Payload-Bau (inkl. Slot-Normalisierung), History-Trimming auf N Einträge, Fehlerfälle (Timeout 3–5 s, 5xx), Retry-Logik, Logging/Metrik-Inkremente, Validierung von Slot-Werten und Graceful Fallback-Antworten.
- **User-Storys / Akzeptanz:**  
  - Als User möchte ich, dass Nachfragen den Kontext nutzen, damit ich nicht alles wiederholen muss (akzeptiert, wenn `conversation_history` in Payload landet und Antwort Bezug nimmt).  
  - Als Admin möchte ich RAG-Ausfälle erkennen, damit ich reagieren kann (akzeptiert, wenn Alert >5% Fehlerquote feuert und Bot fallbacked).  
  - Als User möchte ich, dass fehlende Infos nachgefragt werden, damit Antworten präzise sind (akzeptiert, wenn `rag_form` fehlende Slots abfragt).

## Risiken & Alternativen
- Session-Expiry: Wenn Client-Session < Rasa-Session, Slots könnten verloren gehen → Session-Zeiten angleichen oder Slots im Proxy mitschicken (Impact: geschätzt +10–20% Klarstellungsdialoge bei Sessions >60 min).
- RAG-Fehler/Timeout: Fallback-Antwort + optionaler Retry; alternativ Zwischencache für häufige Fragen (Impact: bei 3–5 s Timeout könnten 5–10% der Queries in Stosszeiten fallbacken).
- Node-Bot-Entscheidung: Proxy beibehalten für Auth/Rate-Limit/Tracing, oder direkten Rasa-Endpoint exponieren (einfacher Betrieb). Entscheidung abhängig von benötigten Guards (Impact: hoch, beeinflusst Deployment-Topologie und Zuständigkeiten).
- History-Größe: 3–5 QA-Paare als Startwert; wenn Antworten häufig zu lang sind, Anzahl reduzieren und stärker auf `last_answer` setzen (Impact: zu große History erhöht Token-Kosten, zu kleine mindert Kontexttreue; beides wirkt auf Antwortqualität).

## Entscheidungsvorschläge
- History-Format für RAG-Payload: Empfehlung JSON-Paare `[{user: "...", bot: "..."}]`, FIFO auf 3–5 QA-Paare, klare Rollentrennung und einfaches Trimming; Alternative Inline-Text (`User: ...\nBot: ...`) nur falls Serialisierung minimal gehalten werden muss.
- Node-Bot-Rolle: Empfehlung Proxy beibehalten (Auth/Rate-Limit/Tracing bleiben erhalten, 1:1 Forwarding zu `/webhooks/rest/webhook`), kein Intent-Routing mehr; Alternative Direktzugriff auf Rasa nur mit vorgelagertem Gateway, das die genannten Guards übernimmt.

## Offene Punkte (mit Priorität)
- Mapping für History → RAG-Prompt finalisieren (Hoch): Format {user, bot} vs. Inline-Text klären, Token-Budget messen; nächster Schritt: zwei Varianten in kleiner Test-Suite gegentesten.
- Entscheidung Node-Bot (Hoch): Proxy beibehalten oder direkt Rasa REST exponieren; falls Proxy, Schnittstelle für Slot-Forwarding festlegen; nächster Schritt: Betriebs-Anforderungen zu Auth/Rate-Limit/Tracing sammeln.
- Mehrsprachigkeit (Mittel): zweites Modell/Service mit LID (Language Identification) + Routing; nächster Schritt: Aufwandsschätzung und Anteil non-DE-Traffic klären.
- Prometheus/Tracing (Mittel): für Action-Server produktiv einbauen inkl. Dashboard; nächster Schritt: Metrics-Port/Paths finalisieren und Grafana-Panel/Alert importieren.

## Go-Live-Kriterien (für Version 1.0)
- NLU/Core: `rasa test nlu/core` ohne kritische Fehler; Intent/Entity F1 >= definiertem Zielwert.
- E2E: Happy-/Slot-Filling-/Fallback-Flows per REST manuell und automatisiert grün; History-Mapping-Variante entschieden.
- Action-Server: RAG-Mock-Tests grün (Payload, History-Trimming, Retry, Fallback), Prometheus-/Alert-Setup aktiv.
- Betrieb: Node-Bot-Entscheidung getroffen (Proxy vs. Direkt), Session-Timeouts abgestimmt, Deployment (Compose/K8s) dokumentiert.
- Doku: `docs/CHANGELOG.md` aktualisiert, Feedback aus Pilot-Tests eingearbeitet.

## Feedback-Schleife
- Nach ersten Läufen von `rasa test nlu/core` und einem kleinen manuellen E2E-Set das Dokument mit Messwerten (Fehlerquoten, Latenzen, History-Größe) und Lessons Learned aktualisieren.
