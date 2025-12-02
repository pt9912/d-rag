# Rasa-Dialogmanagement (Variante 2: Kontextuelle Gesprächsführung) – Design

## Ziel & Scope
- **Ziel:** Rasa Core für mehrturnige, kontextuelle Gespräche nutzen. Der Bot behält Gesprächszustand, Slots und Verlauf, entscheidet per Policies, wann RAG aufgerufen oder eine Rückfrage gestellt wird.
- **Scope:** Stories/Rules, Slots, Policies, Forms/Slot-Filling, Custom Actions für RAG-Aufrufe. Transport primär `webhooks/rest/webhook`. Optionale Integration über den bestehenden Node-Bot als dünne Proxy-Schicht.
- **Nicht im Scope:** UI/Frontend, mehrsprachiges Modell, Voice, LangChain-ähnliche Planner, Agentic Tools über Rasa hinaus.

## Ausgangslage
- Aktuell Intent-only NLU (siehe `docs/rasa-intent-only.md`), Bot routet anhand des erkannter Intents und ruft RAG direkt.
- Kein Dialogzustand, kein Slot-Filling, keine Policies/Stories. Rasa Action-Server nicht aktiviert.

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
  - `TEDPolicy` (80–120 Epochen) für prädiktive Dialogschritte.
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
  - `conversation_history`: Liste der letzten N QA-Paare (N=3–5) für RAG-Payload; bei Überschreitung wird FIFO getrimmt.  
  - `last_answer`: Für Nachfragen wie „Erzähl mehr dazu“.  
  - `pending_clarification`: Steuert, ob Klärungsfrage aktiv ist.  
  - `expected_slot`: Merkt, welches Feld als nächstes gefragt werden soll.
- **Slot-Persistenz:** Session-Config mit `session_expiration_time` (z. B. 60 min), `carry_over_slots_to_new_session: true`, außer `conversation_history` (kann bei Sessionwechsel geleert werden).

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
- **Logging/Metriken:** JSON-Logs pro Action; optional Prometheus-Counter für Action-Erfolge/Fehler.

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
- **NLU:** `rasa test nlu` auf neuen Intents.  
- **Core:** `rasa test core` mit Stories.  
- **E2E:** `curl /webhooks/rest/webhook` mit:  
  - Frage mit Entities → direkte RAG-Antwort.  
  - Frage ohne Entities → Form fragt nach Topic/DocType, dann RAG.  
  - Nachfrage („erzähl mehr“) → nutzt `conversation_history`.  
  - Fallback-Sätze → Klärungsfrage, ggf. RAG-Fallback.  
- **Action-Server:** Unit-Tests für Payload-Bau, History-Trimming, Fehlerfälle (Timeout, 5xx).

## Offene Punkte
- Mapping für History → RAG-Prompt festlegen (z. B. letzte 3 QA-Paare, Token-Budget berücksichtigen).
- Entscheidung Node-Bot: Proxy beibehalten oder direkt Rasa REST exponieren.
- Mehrsprachigkeit: zweites Modell/Service mit LID (Language Identification) + Routing.
- Prometheus/Tracing für Action-Server (z. B. `prom-client` oder OpenTelemetry Python SDK).
