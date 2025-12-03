# Rasa-Integration (Variante 1: Intent-only) – Design

## Ziel & Scope
- **Ziel:** Rasa als reinen NLU-Dienst nutzen, um Nutzeranfragen zu klassifizieren und Entities zu extrahieren. Der Node-Bot entscheidet anhand des Intents, ob er den RAG-Service aufruft oder eine statische Antwort zurückgibt.
- **Nicht im Scope:** Dialog-Policies, Stories/Rules, Slot-Filling, Action-Server mit `rasa-sdk`, webhooks `/webhooks/rest/webhook`.

## Ausgangslage
- `rasa`-Container ist in `docker-compose.yml` vorhanden, aber ohne trainiertes Projekt und ohne Nutzung im Bot. Umstellung des Bots auf Rasa-Nutzung wird als Backlog-Issue nachverfolgt (siehe Offene Punkte).
- Bot (`bot/src/index.js`) ruft derzeit nur `/query` vom RAG-Service auf; `NLU_ENDPOINT` wird lediglich im Health-Check ausgegeben.

## Zielverhalten (Happy Path)
1. Bot erhält `question` (+ optional `roles`).
2. Bot ruft `POST {NLU_ENDPOINT}/model/parse` mit dem Text auf.
3. Bot liest den erkannten Intent (`intent.name`) und die Confidence (Default 0.7, per Env konfigurierbar; Logik: `confidence >= threshold` zählt als Treffer, außer Rasa liefert explizit `nlu_fallback`, dann immer Fallback).
4. Intent-Routing:
   - `ask_rag`: Bot ruft wie bisher den RAG-Service `/query` mit `question` (+ `roles`) auf und gibt Antwort/Contexts zurück.
   - Statische Intents (z. B. `greet`, `help`, `goodbye`, `thank`): Bot antwortet direkt mit vordefinierter Message.
   - Fallback (`nlu_fallback` oder Confidence < Threshold): Bot ruft RAG.

## Änderungen am Rasa-Projekt
- **Dateien/Struktur**
  - `rasa/config.yml`: NLU-Pipeline ohne Policies (REST-Parsing benötigt keine Stories), `language: de`.
    - Pipeline (Intent-only):
      - `WhitespaceTokenizer` (keine Zusatz-Downloads, schnell)
      - `RegexFeaturizer`
      - `LexicalSyntacticFeaturizer`
      - `CountVectorsFeaturizer` (words)
      - `CountVectorsFeaturizer` (char n-grams)
      - `DIETClassifier`
      - `EntitySynonymMapper`
      - `FallbackClassifier` (für `nlu_fallback` bei niedriger Confidence)
      - Optional: `ResponseSelector` (initial weggelassen, da Antworten im Bot liegen).
    - Hinweis: Upgrade-Pfad auf `SpacyTokenizer`/`SpacyFeaturizer` mit `de_core_news_md` für bessere Entity-Qualität möglich.
  - `rasa/domain.yml`: Intents und Responses für statische Intents (z. B. `greet`, `help`, `goodbye`, `thank`), damit ResponseSelector trainieren kann (falls genutzt).
  - `rasa/data/nlu.yml`: Beispielsätze für Intents: `ask_rag` (Fragen), `greet`, `goodbye`, `help`, `thank`, `out_of_scope`/`fallback`; optional Entities (z. B. `topic`, `doc_type`) mit annotierten Beispielen.
  - Keine `stories.yml`/`rules.yml` erforderlich.
  - Sprache: Deutsch-only initial; English kann als separates Modell folgen.
  - Intents (festgelegt): `ask_rag`, `greet`, `goodbye`, `help`, `thank`, `out_of_scope`.
  - Optionale Entities: `topic` (Themenbereich), `doc_type` (z. B. Anleitung, FAQ).
  - Versionierung: Rasa 3.6.21 (Compose setzt `rasa/rasa:3.6.21-full` ein, damit alle Dependencies inkl. spaCy verfügbar sind), passend zu `DIETClassifier`/`FallbackClassifier` Verhalten in 3.x.
- **Training**
  - Lokal: `cd rasa && rasa train`.
  - Docker: `docker compose run --rm rasa train --domain domain.yml --data data/ --out models` (nutzt Volume `./rasa:/app`; Entrypoint ist bereits `rasa`, Volume-Mount in Compose vorhanden; `--config config.yml` nur setzen, falls abweichend; Modelle liegen in `rasa/models`, das Volume sichert Persistenz). Hinweis: Schreibrechte im Volume prüfen (UID/GID), falls auf Host restriktiv.
- **Betrieb**
  - Compose-Service `rasa` bleibt, API offen auf Port 5005 mit `--enable-api --cors "*"`; keine Änderung nötig.

## Änderungen am Bot (`bot/src/index.js`)
- **NLU-Aufruf:** Vor dem RAG-Call `POST {NLU_ENDPOINT}/model/parse` mit `{ text: question }` (HTTP-Client: `node-fetch` aus dem Bot).
- **Intent-Auswertung:** Nutze `intent.name` + `intent.confidence`.
  - Threshold 0.7 (Default im Code) konfigurierbar per Env `NLU_CONFIDENCE_THRESHOLD`; Wert orientiert sich am Rasa-Default für `FallbackClassifier` und ersten manuellen Tests, sollte nach den ersten Runs per Metriken verifiziert werden.
  - `nlu_fallback` vom `FallbackClassifier` kann mit hoher Confidence (bis 1.0) zurückkommen; immer per Intent-Name behandeln, nicht nur per Threshold.
  - Optional: Map Entities (`topic`, `doc_type`, später evtl. `roles`) und reiche sie an den RAG-Service weiter (z. B. als Filter oder Kontext im Payload).
  - Payload-Beispiel für `/query`: `{"question": "...", "roles": ["dev"], "topic": "deployment", "doc_type": "Anleitung"}`. Hinweis: Weitergabe an RAG optional; Verarbeitung (Filter/Prompt) muss im RAG-Service implementiert werden, falls gewünscht (separates Ticket "Entity forwarding to RAG" – siehe Offene Punkte/Tracking).
- **Routing-Logik (Mapping)**
  - `ask_rag` → RAG `/query` mit gleicher Payload wie bisher.
  - `greet`, `help` → statische Antworten, z. B. aus kleinem Dictionary im Bot.
  - `goodbye`, `thank` → statische Antworten.
  - `out_of_scope` oder unter Threshold → immer RAG (Fallback-Verhalten).
  - Kurz-Flow:  
    | Intent/Confidence                      | Aktion           |  
    |----------------------------------------|------------------|  
    | `intent.name === 'nlu_fallback'`       | RAG              |  
    | `confidence >= threshold`              | Intent-Mapping   |  
    | `confidence < threshold`               | RAG              |
- **Statische Antworten:** Kleines Mapping in `bot/src/index.js` oder ausgelagert nach `bot/src/responses.js`; Antwort-Format analog zu RAG (`{ answer: string, contexts: [] }`) für API-Konsistenz. Beispiel `responses.js` (ESM):  
  ```js
  export const responses = {
    greet: { answer: 'Hallo! Wie kann ich helfen?', contexts: [] },
    help: { answer: 'Ich beantworte Fragen zu deinem Projekt per RAG.', contexts: [] },
    goodbye: { answer: 'Bis bald!', contexts: [] },
    thank: { answer: 'Gerne.', contexts: [] }
  };
  ```  
  Import im Bot: `import { responses } from './responses.js';`
  ResponseSelector wird initial nicht genutzt; kann später aktiviert werden, wenn Antworten in Rasa liegen sollen.
- **Fehlerbehandlung:** Wenn Rasa nicht erreichbar oder 4xx/5xx, Bot fällt auf RAG zurück (best-effort).
- **Logging:** Intent-Name + Confidence in `morgan`-Log (oder `console.log`); für Prod optional strukturiert (JSON) + Metriken (Prometheus-Counter `nlu_intent_total`, `nlu_fallback_total`, Histogram `nlu_confidence`).
- **Caching (optional):** LRU-Cache im Bot für `model/parse`-Ergebnisse pro `question` (Cache-Key normalisiert: trim, Mehrfach-Whitespace zu einem Space; initial bewusst case-sensitiv, um potenzielle Case-Signale nicht zu verlieren). Risiko: Cache-Misses durch unterschiedliche Groß-/Kleinschreibung; A/B-Test mit Lowercasing-Variante und Loggen von Hit/Miss-Quote einplanen. Beispiel: Größe 500, TTL 5 Minuten. Cache sollte beim Deployment/Model-Retrain geleert werden.
- **Security/Prod-Hinweise:** `--cors` in Prod auf Bot-Origins whitelisten (z. B. `--cors "http://bot:3978,http://localhost:3978"`). Rate-Limit für `/model/parse` via Reverse-Proxy (z. B. nginx: `limit_req_zone $binary_remote_addr zone=nlu:10m rate=10r/s;` und `limit_req zone=nlu burst=20 nodelay;`).
- **Startup/Health:** Erstes Laden des Modells dauert; Health-Check via `GET /status` am Rasa-Container dokumentieren.
- **Observability:** JSON-Logs für Intent/Confidence; Prometheus-Endpoint im Bot (separater Port, Default 9100 statt 9092, um Kafka-Kollisionen zu vermeiden; per Env überschreibbar) mit Counters `nlu_intent_total{intent}`, `nlu_fallback_total` und Histogram `nlu_confidence`. Prometheus-Scrape-Config: `job_name: bot`, `targets: ['bot:9100']`, `scrape_interval: 15s`.
- **Alerting:** Prometheus-Rule-Beispiele: (a) Fallback-Rate > 50 % über 5 Minuten (`sum(rate(nlu_fallback_total[5m])) / sum(rate(nlu_intent_total[5m])) > 0.5`), (b) fehlendes Modell/Health-Check schlägt fehl; Alarme an Slack/PagerDuty routen.
- **Readiness im Bot:** Optionales Startup-Check gegen `GET /status` von Rasa (mit Retry/Backoff), bevor Requests geproxt werden; fallback weiterhin aktiv, wenn Rasa nicht bereit.
- **Timeout/Retry:** NLU-Request mit Timeout (z. B. 3–5 s); bei Timeout/503 optional ein kurzer Retry oder direkt Fallback auf RAG.

## Modellversionierung & Deployment
- **Artifact-Namen & Hash:** Modelle liegen als `rasa/models/<timestamp>-<hash>.tar.gz`; Compose nutzt `rasa/rasa:3.6.21-full`. Erwarteten Hash/Dateinamen als Env (`NLU_MODEL_HASH` oder `NLU_MODEL_NAME`) in den Bot geben und im Bot-Health-Check gegen `GET /status` (`model_file`, `model_id`) spiegeln.
- **Kompatibilität Bot ↔ Modell:** Bot-Health-Check kann `expected_model` aus Env vs. `loaded_model` aus Rasa loggen und bei Drift warnen. Persistente Modelle (Volume) verhindern unbeabsichtigtes Downgrade; Deploy-Pipeline sollte nur Versionen promoten, die Bot und Rasa gemeinsam getestet haben.
- **Rollback:** Letzte N Modelle behalten (z. B. `models/previous/`); aktives Modell via Symlink `models/active.tar.gz` oder Env `RASA_MODEL` setzen. Rollback = Symlink/Env auf vorheriges Modell zeigen und Bot env `NLU_MODEL_*` anpassen, dann Rasa neu laden (`rasa run --model models/active.tar.gz`).
- **Mehrsprachigkeit (optional):** Aktuell Deutsch-only. Für English: zweites Rasa-Modell/Service (`rasa-en`) mit `language: en` betreiben; Bot nutzt Language-Detection (z. B. fastText/langdetect) zur Auswahl des Endpoints (`NLU_ENDPOINT_EN` vs. `NLU_ENDPOINT`). Unklare Sprache → Default Deutsch/RAG-Fallback; Entities/Intents separat trainieren.

## Test-Plan
- **NLU lokal:** `docker compose run --rm rasa train --domain domain.yml --data data/ --out models && docker compose up -d rasa`; dann `curl -X POST http://localhost:5005/model/parse -H "Content-Type: application/json" -d '{"text":"Wie setze ich RAG auf?"}'`.
- **Bot-Flow:** `docker compose up bot rasa rag-service` und `curl -X POST http://localhost:3978/ask -H "Content-Type: application/json" -d '{"question":"Wie deploye ich das?", "roles":["dev"]}'` → prüfen, ob Bot Intent loggt und RAG antwortet.
- **Fallback:** Anfrage mit Off-Topic-Text stellen, Expectation: Fallback → RAG.
- **Fehlerfälle:** Rasa nicht erreichbar (Bot fällt auf RAG zurück); Confidence exakt bei 0.7 (Grenzfall prüfen); leere/ungültige Eingaben (400 vom Bot).
- **Reproduzierbarkeit:** Geplante Makefile-Targets oder Skripte (`make train-nlu`, `make test-nlu`, `make test-bot`) kapseln die obigen Kommandos für CI/Entwicklung.

## Offene Punkte
- Issue: Bot aktiv auf Rasa-Nutzung umstellen (derzeit noch reiner RAG-Bot) – Backlog/Repo-Issue anlegen und Referenz hier ergänzen.
- Ticket: Entity-Weitergabe an RAG (Phase 2) – Issue anlegen und verlinken; umfasst Anpassungen an RAG-Service für Entity-Filter/Prompt.
- Alerting-Regeln in `prometheus.yml` ergänzen (Fallback-Rate, fehlendes Modell), inkl. Routing zu Alarm-Channel.
- Mehrsprachigkeit: Sprache erkennen und English-Modell anbinden; Entscheidung/Implementierung separat tracken.
- Makefile/Script-Targets für Trainings- und Test-Commands hinzufügen, damit die Test-Plan-Schritte wiederholbar sind.
