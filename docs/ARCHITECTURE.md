# Architektur des lokalen RAG-Stacks

Dieses Dokument beschreibt Aufbau, Komponenten und Datenflüsse des RAG-Demostacks unter `docker-compose.yml`. Ziel ist, schnell zu erkennen, welche Dienste beteiligt sind, wie sie interagieren und welche Erweiterungspunkte bzw. Betriebsaspekte zu beachten sind.

## 1. Überblick & Ziele

- **Use Case:** Lokale Referenzimplementierung für ein Retrieval-Augmented-Generation-System, das Markdown/PDF-Dokumente ingestiert, in Qdrant persistiert und Fragen über ein Ollama-Modell beantwortet.
- **Schnittstellen:** REST (FastAPI), Express Bot-Endpoint (`/ask`), MCP-Gateway (JSON-RPC), PDF-/ZIP-Uploadservice, direkte Qdrant/Ollama Endpoints per Compose-Netzwerk.
- **Beobachtbarkeit:** OpenTelemetry Collector nimmt OTLP-Events an, exportiert Traces als Logs und Metrics nach Prometheus; Grafana dient als Dashboard. RAG-/Bot-/Extractor-Services sind derzeit nicht mit OTEL-SDKs instrumentiert.
- **Deployment-Form:** Einzelnes Docker-Compose-File. Persistente Volumes für Qdrant (`qdrant_data`), Ollama-Modelle (`ollama_models`) und Reranker-Modelle (`reranker_models`). Quelle für Git-Inhalte ist eine lokale Bare-Repo-Mappe `docs.git`, Arbeitskopien landen in `git-workspace`.

```
┌─────────┐      ┌────────────────┐      ┌─────────────────────────┐
│ Client  │<---->│ Bot / MCP /    │<---->│ RAG-Service             │
│ (REST)  │      │ Direct REST    │      │                         │
└─────────┘      └────────────────┘      ├──────────┬──────────────┤
                                         │Ollama    │ Qdrant        │
                                         │Embedding │ (Vectorstore) │
                                         └─────┬────┴──────┬────────┘
                                               │           │
                                 ┌─────────────▼───────────▼────────┐
                                 │ Reranker (TEI Cross-Encoder)     │
                                 └─────────────┬────────────────────┘
                                               │
                                     ┌─────────▼────────┐
                                     │ Ollama LLM        │
                                     └───────────────────┘
                 ┌────────────────────┐
                 │ Doc Extractor      │
                 └─────────┬──────────┘
                           │
                  ┌────────▼──────┐
                  │ rag/data/*    │
                  │ (Markdown)    │
                  └───────────────┘
```

## 2. Komponenten & Verantwortlichkeiten

| Komponente                                | Technology                      | Aufgabe                                                                                                                                                                                                                                             |
| ----------------------------------------- | ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `rag-service`                             | FastAPI, Python 3.11            | Kernpipeline für Ingest, Update und Query (`rag/app/main.py`). Verwaltet Chunking, Einbettung via Ollama (`ollama_client.py`), Re-Ranking (`reranker_client.py`), Persistenz in Qdrant (`vectorstore.py`) und Git-basierte Quellen (`git_sync.py`). |
| `qdrant`                                  | Qdrant 1.7                      | Vektor-Datenbank. Wird bei Bedarf vom RAG-Service initialisiert (`VectorStore.ensure_collection`). Legt Daten in Volume `qdrant_data` ab.                                                                                                           |
| `ollama`                                  | Ollama Daemon                   | Stellt Embedding- (`nomic-embed-text`) und LLM-Modell (`llama3`) bereit. Läuft im selben Compose-Netz, sodass der RAG-Service HTTP-Requests senden kann.                                                                                            |
| `reranker`                                | TEI (Text Embeddings Inference) | Re-Ranking-Service mit BGE-Modell (`BAAI/bge-reranker-large`). Bewertet Kandidaten aus der Vektorsuche nach semantischer Relevanz zur Query und sortiert sie neu. Modell wird in Volume `reranker_models` gecacht.                                  |
| `extractor`                               | FastAPI                         | Endpunkte `/extract/pdf` und `/extract/zip` (`extractor/app/main.py`). Extrahiert Text mit `pypdf`, schreibt Markdown nach `rag/data/*.md` und ruft optional `/update` auf dem RAG-Service.                                                         |
| `bot`                                     | Express (Node 20)               | Minimaler API-Stub (`bot/src/index.js`). Route `/ask` proxied Anfragen an `rag-service` und dient als Beispielintegration für Conversational Agents.                                                                                                |
| `rasa`                                    | Rasa 3.6.21                     | NLU-Container, vorbereitet um Intents zu erkennen. Im aktuellen Stand wird er noch nicht aktiv vom Bot genutzt, kann aber zur Intent-bestimmten RAG-Abfrage erweitert werden.                                                                       |
| `mcp`                                     | FastMCP                         | JSON-RPC-Gateway (Model Context Protocol). Exportiert Tools `rag.query`, `rag.ingest`, `rag.update`, die intern die REST-Endpunkte ansprechen (`mcp/app/main.py`).                                                                                  |
| `otel-collector`, `prometheus`, `grafana` | Observability-Stack             | Collector nimmt OTLP-Traces/Metrics entgegen (siehe `otel-collector-config.yaml`), exponiert Metriken an Prometheus (`prometheus.yml`). Grafana visualisiert.                                                                                       |

### 2.1 Wichtige Endpunkte

| Service        | Endpoint              | Methode     | Beschreibung                            |
| -------------- | --------------------- | ----------- | --------------------------------------- |
| rag-service    | `/query`              | POST        | Haupt-RAG-Query                         |
| rag-service    | `/ingest`             | POST        | Manuelles Ingest                        |
| rag-service    | `/update`             | POST        | Re-Ingest/Delta-Update                  |
| rag-service    | `/git/webhook/{repo}` | POST        | Git-Push-Webhook (optional signiert)    |
| extractor      | `/extract/pdf`        | POST        | PDF → Markdown                          |
| extractor      | `/extract/zip`        | POST        | ZIP → mehrere Markdown-Dateien          |
| bot            | `/ask`                | POST        | Proxy auf RAG                           |
| reranker (TEI) | `/rerank`             | POST        | Cross-Encoder Re-Ranking                |
| mcp            | JSON-RPC Tools        | POST/stream | `rag.query`, `rag.ingest`, `rag.update` |

## 3. Datenflüsse

### 3.1 Query Flow
1. **Eingang:** Bot, MCP oder direkter REST-Client ruft `POST /query` am RAG-Service auf. Rollen (`roles`) begrenzen sichtbare Dokumente.
2. **Embedding:** `RAGPipeline.answer` erzeugt Embeddings über `OllamaClient.embed`.
3. **Retrieval:** `VectorStore.search` ruft Qdrant mit optionalem Rollen-Filter (`MatchAny`) auf und gibt Top-N Kandidaten zurück (`Settings.reranker_initial_k`, default 20).
4. **Re-Ranking:** `RerankerClient.rerank` sendet Query und Kandidaten an den TEI-Service (Cross-Encoder, kein Bi-Encoder). Pro Kandidat läuft ein vollständiger Forward-Pass über Query+Dokument, es entsteht ein unnormalisierter Similarity-Score; Sortierung erfolgt absteigend. Kosten wachsen linear mit K, daher `reranker_initial_k` klein halten und `max_context_chunks` hart begrenzen.
5. **Generierung:** Prompt wird mit den re-gerankten Kontexten angereichert und per `OllamaClient.generate` beantwortet.
6. **Antwort:** JSON: `{ answer, contexts }`. Kontexte enthalten optional `rerank_score`. Bot reicht es ungefiltert weiter, MCP stellt Antwort + Kontextliste als `TextContent` bereit.

Latenz-Richtwerte (abhängig von Hardware/Modell):
- Embedding (Ollama): ca. 10–20 ms pro Chunk
- Qdrant-Suche: ca. 1–5 ms
- Reranker (Cross-Encoder): ca. 50–200 ms * K
- LLM-Antwort: ca. 100–1500 ms je nach Promptumfang

### 3.2 Datei-Ingest (Manuell / Default-Dataset)
1. **Trigger:** Startup-Hook lädt `rag/data/demo.md` (konfigurierbar via `Settings.default_dataset_path`). Alternativ Aufruf von `/ingest` oder `/update` mit `path`.
2. **Chunking:** `chunk_text` splittet Markdown Token-basiert via `tiktoken` (Default-Encoding `cl100k_base`, 600 Tokens, 120 Overlap). Wenn kein Tokenizer verfügbar ist, wird auf whitespace-basierte Splits zurückgefallen.
3. **Persistenz:** Jeder Chunk wird eingebettet, Collection wird falls nötig erzeugt und via `VectorStore.upsert` gespeichert.
4. **Update:** `/update` löscht zuvor gespeicherte Chunks eines Pfads (`VectorStore.delete_by_metadata(source=...)`) oder – bei Git – selektiv anhand `git_repo`/`git_path`.

### 3.3 Git-basierter Ingest
1. **Konfiguration:** `.env` bzw. `Settings.git_repos` definieren `url`, `branch`, optional `default_glob` (siehe `GitRepoConfig`).
2. **Sync:** `git_sync.sync_repo` klont/aktualisiert Repo nach `git_workspace_root` (`/repos`) und checkt Branch oder Commit aus.
3. **Auswahl:** Patterns aus Request oder Repo-Default bestimmen, welche Dateien ingestiert werden (`_collect_git_files`). Ordner/Glob-Kombinationen möglich.
4. **Update über Webhook:** `/git/webhook/{repo}` validiert HMAC-Signaturen (`verify_signature`), ermittelt geänderte Dateien via `diff_changed_files` und aktualisiert nur betroffene Chunks. Deletions/Umbenennungen werden durch gezieltes Löschen behandelt.

### 3.4 PDF-/ZIP-Verarbeitung
1. **Upload:** `/extract/pdf` akzeptiert `multipart/form-data`. ZIP-Endpoint extrahiert mehrere PDFs.
2. **Speicherung:** Datei wird in Markdown konvertiert, Name per `slugify`/`ensure_suffix` normalisiert und nach `rag/data/<name>.md` geschrieben.
3. **Automatisches Update:** Ist `auto_update=true` und `RAG_SERVICE_URL` gesetzt, ruft der Dienst `/update` auf (rollen können via `roles`-Formfeld übergeben werden).

### 3.5 Observability
1. Collector akzeptiert OTLP (`otel-collector:4317/4318`). RAG-/Bot-/Extractor sind derzeit nicht mit OTEL-SDKs instrumentiert, d. h. es werden ohne Anpassung keine Spans/Metrics gesendet.
2. Collector exportiert Traces als Logs und Metrics an einen eingebetteten Prometheus-Endpoint (`:9464`); keine Logs nach Prometheus.
3. Prometheus scraped den Collector alle 15s und stellt Daten Grafana zur Verfügung.

## 4. Deployment & Infrastruktur

- **Netz:** Compose erstellt Default-Netzwerk, so dass Services via DNS (`rag-service`, `qdrant`, `ollama`, …) erreichbar sind.
- **Persistenz:** Textdaten liegen im Workspace (`rag/data`). Qdrant-, Ollama- und Reranker-Volumes sichern Vektoren/Modelle zwischen Container-Neustarts.
- **Build-/Startbefehle:** Python-Services installieren Abhängigkeiten bei jedem Start (`pip install .`). Bot installiert npm-Dependencies on-the-fly (Trade-off zwischen Einfachheit und Startzeit).
- **Ports:** Standard-Ports werden extern gemappt (8000 FastAPI, 8082 Reranker, 8100 Extractor, 8800 MCP, 3978 Bot, 5005 Rasa, 11434 Ollama, 6333 Qdrant, 9090 Prometheus, 3000 Grafana).
- **Qdrant-Parameter:** Collection wird beim ersten Ingest mit `vector_size=768` (Default `nomic-embed-text`) und Distanz `cosine` angelegt; Einbettungsmodell und Collection müssen zusammenpassen.
- **Access Control:** RAG-Endpunkte sind nicht geschützt; nur Git-Webhook erwartet Signatur (`Settings.webhook_secret`). Rollen-basierte Filter sind ausschließlich logischer Natur (Trennung durch Metadaten).

## 5. Konfiguration & Secrets

- `.env` im `rag/`-Verzeichnis konfiguriert Settings. Wichtige Parameter: Ollama/Qdrant/Reranker URLs, `default_dataset_path`, `git_repos`, `default_roles`, `webhook_secret`.
- Tokenizer: `tokenizer_encoding` (tiktoken-Encoding, Standard `cl100k_base`, `None` schaltet auf Whitespace-Splitting zurück).
- Reranker-Konfiguration: `RERANKER_URL` (URL des TEI-Service), `RERANKER_TOP_K` (Ergebnisse nach Re-Ranking), `RERANKER_INITIAL_K` (Kandidaten für Re-Ranking). Um Re-Ranking zu deaktivieren, `RERANKER_URL` leer lassen.
- Git-Repos können denselben Arbeitsbereich teilen, Pfade werden automatisch erstellt (`git_workspace_root`).
- Extractor benötigt `EXTRACT_OUTPUT_DIR` (Default `/data` -> gemountet auf `rag/data`) und optional `RAG_SERVICE_URL`.
- MCP-Gateway erwartet `RAG_SERVICE_URL` und optional `MCP_TRANSPORT` (Std. `streamable-http`).
- Bot-Env: `NLU_ENDPOINT`, `RAG_ENDPOINT`, `PORT`.

## 6. Sicherheit & Compliance

- **Netzwerkgrenzen:** Alle Dienste laufen lokal; sobald Ports veröffentlicht werden, ist Authentifizierung notwendig (derzeit nicht implementiert).
- **Webhook-Absicherung:** Nur `/git/webhook/{repo}` prüft Signatur (HMAC-SHA256). Secret wird über `WEBHOOK_SECRET` gesetzt.
- **Rollenkonzept:** Rollen sind Metadaten pro Chunk; Matching erfolgt über `MatchAny`. Enforcement gilt nur bei Retrieval, nicht beim Speichern/Abrufen der Rohdateien im Dateisystem.
- **Dateizugriff:** Extractor schreibt direkt ins Workspace-Volume. Host sollte Dateisystemberechtigungen prüfen, da jeder Benutzer Markdown-Dateien lesen könnte.

## 7. Betrieb & Erweiterbarkeit

- **Monitoring:** Prüfe `docker compose logs <service>` für Troubleshooting. Qdrant-Dashboard unter `localhost:6333/dashboard`.
- **Skalierung:** Compose-Setup ist für Ein-Knoten-Entwicklung gedacht. RAG-Service ist stateless und kann horizontal skaliert werden; Qdrant ist clusterfähig, TEI-Reranker lässt sich replizieren, bleibt aber CPU-intensiv. Ollama skaliert nicht horizontal (Single-Process), bräuchte externes LLM/Embeddings für mehr Durchsatz. Für Produktion müssten Qdrant/Ollama extern betrieben, Secrets sicher verwaltet und AuthN/AuthZ ergänzt werden.
- **RAG-Erweiterungen:** 
  - Weitere Dokumentquellen können über zusätzliche Endpunkte oder Tools angebunden werden (z. B. S3-Loader).
  - Chunking-/Embedding-Strategien lassen sich zentral im `RAGPipeline` bzw. `Settings` anpassen.
  - Bot kann Rasa-Intents auswerten und kontextuell entscheiden, ob/wie RAG angefragt wird.
  - MCP-Gateway lässt sich durch neue Tools erweitern (z. B. `rag.delete`), indem weitere `@server.tool`-Funktionen ergänzt werden.

## 8. Bekannte Einschränkungen

- Ingest-Zeit steigt linear mit Dokumentgröße; es gibt keine Hintergrund-Jobs oder Warteschlangen – alle Operationen laufen synchron innerhalb der HTTP-Requests.
- Keine dedizierte Authentifizierung oder Rate-Limits an den REST-Endpunkten.
- Observability ist rudimentär (Logging-Exporter), da RAG-/Extractor-Services keine OTLP-Instrumentierung enthalten.
- Bot und Rasa dienen als Referenz; Produktionsfeatures wie Konversationserhalt oder Multi-Role-Handling fehlen bewusst.
- Reranker läuft als Cross-Encoder im CPU-Image, skaliert linear mit K, kein Batch über Paare; großes Modell (≈2,2 GB) verursacht längeren Cold-Start, `max_batch_requests` wird vom Dienst automatisch reduziert und GPU-Deployments bringen deutliche Vorteile.

Dieses Dokument soll als Einstieg dienen. Für detaillierte Implementierungsdetails siehe die jeweils referenzierten Dateien (`rag/app/*.py`, `extractor/app/main.py`, `mcp/app/main.py`, `bot/src/index.js`, Compose-File).
