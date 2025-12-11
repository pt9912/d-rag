# Architektur des lokalen RAG-Stacks

Dieses Dokument beschreibt Aufbau, Komponenten und Datenflüsse des RAG-Demostacks unter `docker-compose.yml`. Ziel ist, schnell zu erkennen, welche Dienste beteiligt sind, wie sie interagieren und welche Erweiterungspunkte bzw. Betriebsaspekte zu beachten sind. Der Stack nutzt Rasa als dialogfähigen Orchestrator (Slots, Forms, Policies, Custom Actions) mit Action-Server; der Node-Bot kann als dünner Proxy weiterverwendet werden.

## 1. Überblick & Ziele

- **Use Case:** Lokale Referenzimplementierung für ein Retrieval-Augmented-Generation-System, das Markdown/PDF-Dokumente ingestiert, in Qdrant persistiert und Fragen über ein Ollama-Modell beantwortet.
- **Schnittstellen:** REST (FastAPI), Express Bot-Endpoint (`/ask`), MCP-Gateway (JSON-RPC), PDF-/ZIP-Uploadservice, direkte Qdrant/Ollama Endpoints per Compose-Netzwerk.
- **Beobachtbarkeit:** OpenTelemetry Collector nimmt OTLP-Events an, exportiert Traces als Logs und Metrics nach Prometheus; Grafana dient als Dashboard. RAG-/Bot-/Extractor-Services sind derzeit nicht mit OTEL-SDKs instrumentiert.
- **Deployment-Form:** Einzelnes Docker-Compose-File. Persistente Volumes für Qdrant (`qdrant_data`), Ollama-Modelle (`ollama_models`) und Reranker-Modelle (`reranker_models`). Quelle für Git-Inhalte ist eine lokale Bare-Repo-Mappe `docs.git`, Arbeitskopien landen in `git-workspace`.

```
┌─────────┐       ┌──────────────────────┐      ┌─────────────────────────┐
│ Client  │<----->│ Bot / MCP / REST     │----->│ RAG-Service             │
│ (REST)  │       │ (Intent-Routing)     │      │                         │
└─────────┘       └─────────┬────────────┘      ├──────────┬──────────────┤
                            │                   │Ollama    │ Qdrant       │
                            │                   │Embedding │ (Vectorstore)│
                            │                   └─────┬────┴──────┬───────┘
                            │                         │           │
                            │          ┌──────────────▼───────────▼────────┐
                            └--------->│ Rasa Core + Action-Server         │
                                       └───────────────────────────────────┘
                                             │
                                             │ Custom Action: /query (RAG)
                                             │
                             ┌───────────────▼─────────────┐
                             │ RAG-Service (Retrieval +    │
                             │ Ollama/Reranker/Qdrant)     │
                             └───────────────┬─────────────┘
                                             │
                             ┌───────────────▼─────────────┐
                             │ Reranker (TEI Cross-Enc)    │
                             └───────────────┬─────────────┘
                                             │
                                   ┌─────────▼────────┐
                                   │ Ollama LLM       │
                                   └──────────────────┘
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

| Komponente                                | Technology                      | Aufgabe                                                                                                                                                                                                                                                    |
| ----------------------------------------- | ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `rag-service`                             | FastAPI, Python 3.11            | Kernpipeline für Ingest, Update und Query (`rag/app/main.py`). Verwaltet Chunking, Einbettung via Ollama (`ollama_client.py`), Re-Ranking (`reranker_client.py`), Persistenz in Qdrant (`vectorstore.py`) und Git-basierte Quellen (`git_sync.py`).        |
| `qdrant`                                  | Qdrant 1.7                      | Vektor-Datenbank. Wird bei Bedarf vom RAG-Service initialisiert (`VectorStore.ensure_collection`). Legt Daten in Volume `qdrant_data` ab.                                                                                                                  |
| `ollama`                                  | Ollama Daemon                   | Stellt Embedding- (`nomic-embed-text`) und LLM-Modell (`llama3`) bereit. Läuft im selben Compose-Netz, sodass der RAG-Service HTTP-Requests senden kann.                                                                                                   |
| `reranker`                                | TEI (Text Embeddings Inference) | Re-Ranking-Service mit BGE-Modell (`BAAI/bge-reranker-large`). Bewertet Kandidaten aus der Vektorsuche nach semantischer Relevanz zur Query und sortiert sie neu. Modell wird in Volume `reranker_models` gecacht.                                         |
| `extractor`                               | FastAPI                         | Endpunkte `/extract/pdf`, `/extract/zip` und `/extract/aggregated-md` (`extractor/app/main.py`). Extrahiert Text aus PDFs (`pypdf`), Markdown/Text-Dateien und aggregierten Projektdateien. Schreibt nach `rag/data/*.md` und ruft optional `/update` auf. |
| `bot`                                     | Express (Node 20)               | Optionaler Proxy zu Rasa `/webhooks/rest/webhook` und zum RAG-Service; kann statische Antworten liefern und Header (z. B. Rollen) weitergeben. Für Dialogmanagement übernimmt primär Rasa.                                                                 |
| `rasa`                                    | Rasa 3.6.21                     | Dialog-Engine (Deutsch) mit Slots, Forms, Policies (Rule/Memoization/TED) und FallbackClassifier. REST-Endpoint `/webhooks/rest/webhook`.                                                                                                                  |
| `action-server`                           | rasa-sdk 3.6                    | Custom Actions: `action_query_rag` ruft RAG `/query` mit Slots/History/Rollen, trimmt History; Form-Validierung; Kontext-Reset; Prometheus-Metriken `/metrics` (Port 8001).                                                                                |
| `mcp`                                     | FastMCP                         | JSON-RPC-Gateway (Model Context Protocol). Exportiert Tools `rag.query`, `rag.ingest`, `rag.update`, die intern die REST-Endpunkte ansprechen (`mcp/app/main.py`).                                                                                         |
| `otel-collector`, `prometheus`, `grafana` | Observability-Stack             | Collector nimmt OTLP-Traces/Metrics entgegen (siehe `otel-collector-config.yaml`), exponiert Metriken an Prometheus (`prometheus.yml`). Grafana visualisiert.                                                                                              |

### 2.1 Wichtige Endpunkte

| Service        | Endpoint                 | Methode     | Beschreibung                                     |
| -------------- | ------------------------ | ----------- | ------------------------------------------------ |
| rag-service    | `/query`                 | POST        | Haupt-RAG-Query                                  |
| rag-service    | `/ingest`                | POST        | Manuelles Ingest                                 |
| rag-service    | `/update`                | POST        | Re-Ingest/Delta-Update                           |
| rag-service    | `/git/webhook/{repo}`    | POST        | Git-Push-Webhook (optional signiert)             |
| extractor      | `/extract/pdf`           | POST        | PDF → Markdown                                   |
| extractor      | `/extract/zip`           | POST        | ZIP → mehrere Dateien (PDF, MD, TXT)             |
| extractor      | `/extract/aggregated-md` | POST        | Aggregiertes Projekt-Markdown → Chunks           |
| bot            | `/ask`                   | POST        | Intent-Routing + Proxy auf RAG                   |
| bot            | `/readyz`                | GET         | Readiness, prüft Rasa `/status`                  |
| bot            | `/metrics`               | GET         | Prometheus-Metriken (Intent/Fallback/Confidence) |
| reranker (TEI) | `/rerank`                | POST        | Cross-Encoder Re-Ranking                         |
| mcp            | JSON-RPC Tools           | POST/stream | `rag.query`, `rag.ingest`, `rag.update`          |

## 3. Datenflüsse

### 3.1 Query Flow
1. **Eingang:** Client (oder Bot als Proxy) ruft `POST /webhooks/rest/webhook` am Rasa-Service auf.
2. **NLU/Core:** Rasa erkennt Intent/Entities, füllt Slots/Forms (`rag_form` für `topic`/`doc_type`/`roles`) und wählt per Policies die Custom Action.
3. **Custom Action:** `action_query_rag` baut Payload `{question, topic?, doc_type?, roles?, history?}` und ruft `POST {RAG_ENDPOINT}/query` mit Timeout/Retry. History wird auf 3–5 QA-Paare getrimmt.
4. **RAG-Service:** `RAGPipeline.answer` erzeugt Embeddings, sucht in Qdrant, rerankt, generiert Antwort über Ollama.
5. **Antwort:** Rasa sendet Liste von Messages zurück (REST-Webchat-Format), die der Bot optional 1:1 weiterreicht. History/Slots werden im Tracker aktualisiert.

Latenz-Richtwerte (abhängig von Hardware/Modell):
- Rasa-NLU/Core: typ. <100 ms bei kleinen Modellen und kurzen Verläufen
- Embedding (Ollama): ca. 10–20 ms pro Chunk
- Qdrant-Suche: ca. 1–5 ms
- Reranker (Cross-Encoder): ca. 50–200 ms * K
- LLM-Antwort: ca. 100–1500 ms je nach Promptumfang

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
1. **Upload:** `/extract/pdf` akzeptiert `multipart/form-data`. ZIP-Endpoint (`/extract/zip`) extrahiert mehrere Dateien (PDF, MD, Markdown, TXT).
2. **Speicherung:** Datei wird in Markdown konvertiert, Name per `slugify`/`ensure_suffix` normalisiert und nach `rag/data/<name>.md` geschrieben.
3. **Automatisches Update:** Ist `auto_update=true` und `RAG_SERVICE_URL` gesetzt, ruft der Dienst `/update` auf (rollen können via `roles`-Formfeld übergeben werden).

### 3.5 Aggregiertes Markdown-Format

Der Stack unterstützt ein spezielles Markdown-Format, das ganze Codebasen in einer einzigen Datei aggregiert. Dieses Format wird durch das mitgelieferte Generator-Tool erstellt.

#### Generator-Tool: `projekt_aggregator.py`

Ein Python-Skript, das Projektstruktur, Dokumentation und Source-Code in eine einzige Markdown-Datei zusammenfasst.

**Verwendung:**

```bash
cd /pfad/zum/projekt
python projekt_aggregator.py
# Erzeugt: projekt_komplett.md

# Mit Beschreibung aus Datei
python projekt_aggregator.py --description @beschreibung.txt

# Ausgabe nach stdout
python projekt_aggregator.py --output -

# KI-Prompt generieren (sammelt README, docs/, Config-Dateien)
python projekt_aggregator.py --generate-prompt > prompt.txt
```

**Docker-Verwendung:**

```bash
docker build -t projekt-aggregator ./tools
docker run --rm -v $(pwd):/project projekt-aggregator --output mein_projekt.md

# Mit externer Beschreibungsdatei
docker run --rm -v $(pwd):/project -v ~/templates:/config projekt-aggregator --description @/config/beschreibung.txt

# KI-Prompt generieren
docker run --rm -v $(pwd):/project projekt-aggregator --generate-prompt
```

**Konfiguration** (im Skript anpassbar):

```python
# Ausgabedatei
output_filename = "projekt_komplett.md"

# Projektbeschreibung für KI-Kontext (siehe KI-Prompt unten)
PROJEKT_BESCHREIBUNG = """
# PROJEKTBESCHREIBUNG
Projektname: Kundenportal-v2
Ziel: Self-Service-Portal für Endkunden mit Vertragsverwaltung

Domäne: Versicherung, B2C-Portal
Technologie-Stack: Python 3.11, FastAPI, PostgreSQL, Vue.js 3
Architektur-Pattern: Clean Architecture, CQRS

Problemstellung:
Monolithisches Legacy-Portal mit hohem Support-Aufwand ersetzen.

Wichtige Entscheidungen:
- Clean Architecture für Testbarkeit
- CQRS für optimierte Lese-/Schreibpfade

Schlüsselkomponenten:
- api-gateway: Request-Routing, Auth
- contract-service: Vertragsverwaltung

Schlagworte: Self-Service, Kundenportal, Versicherung, FastAPI, Vue.js
"""

# Zu erfassende Dateitypen
extensions = ['.md', '.py', '.js', '.html', '.css', '.java',
              '.cpp', '.h', '.json', '.yaml', '.sql', '.txt']

# Ausgeschlossene Verzeichnisse
ignore_folders = ['.git', '__pycache__', 'node_modules', 'venv',
                  '.idea', '.vscode', 'build', 'dist', 'bin', 'obj']
```

**Ausgabe-Struktur:**

1. `# VERZEICHNISSTRUKTUR` – ASCII-Baum aller erfassten Dateien
2. `# PROJEKTBESCHREIBUNG` – Konfigurierter Kontext für die KI
3. `# DATEIINHALTE` – Jede Datei als `## DATEI: <pfad>` mit Code-Fence

**Hinweise:**
- Das Skript überspringt sich selbst und die Ausgabedatei
- Dateien werden UTF-8-kodiert gelesen
- Große Projekte erzeugen große Markdown-Dateien (ggf. selektiv Extensions wählen)
- Für KI-Prompts zur Erstellung von Projektbeschreibungen siehe `docs/archive/sprint-task-projekt-aggregator.md`

#### Format-Struktur

Das Format besteht aus drei Hauptsektionen:

1. **Verzeichnisstruktur** – ASCII-Baum des Projekts
2. **Projektbeschreibung** – Kontext und Hinweise für die Verarbeitung
3. **Dateiinhalte** – Jede Datei als eigene `## DATEI:`-Sektion mit Code-Fence

```markdown
# VERZEICHNISSTRUKTUR
​```text
.
├── src/
│   ├── main.py
│   └── utils.py
└── README.md
​```

---
# PROJEKTBESCHREIBUNG
[Beschreibung des Projekts und Hinweise für die Verarbeitung]

---
# DATEIINHALTE

---
## DATEI: ./src/main.py
​```python
<Dateiinhalt>
​```

---
## DATEI: ./src/utils.py
​```python
<Dateiinhalt>
​```
```

#### Verarbeitung mit MarkdownHeaderTextSplitter

Das Format ist so strukturiert, dass es mit LangChains `MarkdownHeaderTextSplitter` effizient in Chunks aufgeteilt werden kann:

```python
from langchain.text_splitter import MarkdownHeaderTextSplitter

headers_to_split_on = [
    ("#", "Header 1"),      # z.B. # DATEIINHALTE
    ("##", "Dateiname"),    # z.B. ## DATEI: ./ordner/main.py
]

markdown_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
docs = markdown_splitter.split_text(text)

# Ergebnis: Jede Datei wird ein eigener Chunk mit Metadaten
# docs[n].metadata = {'Dateiname': 'DATEI: ./src/main.py', ...}
```

#### Use-Case: Projekt-Wissensarchiv

Das Format eignet sich besonders für ein **Projekt-Wissensarchiv** – eine Sammlung abgeschlossener Projekte mit Dokumentation und Source-Code. Bei neuen Anforderungen können ähnliche Architekturen und Lösungen gefunden werden.

Typische Inhalte pro Projekt-Datei:
- **Lastenheft** – Anforderungen, Stakeholder, Rahmenbedingungen
- **Pflichtenheft** – Technische Spezifikation, Abnahmekriterien
- **Architektur-Dokumentation** – Systemübersicht, Komponenten, Schnittstellen
- **Design-Dokumente** – Detailentwürfe, Datenmodelle, Sequenzdiagramme
- **Source-Code** – Implementierung mit Kommentaren

#### Extrahierte Metadaten

Für jeden Chunk werden folgende Metadaten in Qdrant gespeichert:

| Metadatum      | Quelle                             | Beispiel                                                              |
| -------------- | ---------------------------------- | --------------------------------------------------------------------- |
| `project_name` | Aus `# PROJEKTBESCHREIBUNG` parsen | `Kundenportal-v2`                                                     |
| `project_id`   | Slug aus project_name              | `kundenportal-v2`                                                     |
| `doc_type`     | Aus Dateipfad/Header erkennen      | `lastenheft`, `pflichtenheft`, `architektur`, `design`, `source_code` |
| `source`       | Dateipfad aus `## DATEI:`          | `./src/main.py`                                                       |
| `language`     | Code-Fence-Sprache                 | `python`                                                              |
| `directory`    | Abgeleitet aus Pfad                | `./src`                                                               |
| `extension`    | Abgeleitet aus Pfad                | `.py`                                                                 |

**Dokument-Typ-Erkennung** (`doc_type`):

| Erkennungsmuster                                             | doc_type        |
| ------------------------------------------------------------ | --------------- |
| `lastenheft`, `anforderung`, `requirements` im Pfad/Header   | `lastenheft`    |
| `pflichtenheft`, `spec`, `specification` im Pfad/Header      | `pflichtenheft` |
| `architektur`, `architecture`, `ARCHITECTURE` im Pfad/Header | `architektur`   |
| `design`, `entwurf`, `konzept` im Pfad/Header                | `design`        |
| Code-Dateien (`.py`, `.js`, `.java`, etc.)                   | `source_code`   |

Die Projektbeschreibung und Verzeichnisstruktur werden als eigene Chunks mit `doc_type: meta` gespeichert.

#### Vorteile

- **Ähnlichkeitssuche:** „Zeige mir Projekte mit REST-API und PostgreSQL" findet passende Architekturen
- **Dokument-Typ-Filter:** Suche nur in Lastenheften, nur in Source-Code, oder übergreifend
- **Projekt-übergreifend:** Ein Query durchsucht alle archivierten Projekte gleichzeitig
- **Kontexterhaltung:** Jeder Chunk behält Projekt-Zugehörigkeit und Dateipfad
- **Batch-Import:** Ganze Projekte können mit einem Upload ingestiert werden

#### Unterstützte Dateitypen

| Extension | Sprache für Code-Fence |
| --------- | ---------------------- |
| `.py`     | `python`               |
| `.js`     | `js`                   |
| `.ts`     | `typescript`           |
| `.java`   | `java`                 |
| `.cpp`    | `cpp`                  |
| `.h`      | `c`                    |
| `.json`   | `json`                 |
| `.yaml`   | `yaml`                 |
| `.sql`    | `sql`                  |
| `.md`     | `markdown`             |
| `.html`   | `html`                 |
| `.css`    | `css`                  |

### 3.6 Observability
1. Collector akzeptiert OTLP (`otel-collector:4317/4318`). RAG-/Extractor sind derzeit nicht mit OTEL-SDKs instrumentiert; Bot exportiert eigene Prometheus-Metriken (`/metrics`).
2. Collector exportiert Traces als Logs und Metrics an einen eingebetteten Prometheus-Endpoint (`:9464`); keine Logs nach Prometheus.
3. Prometheus scraped den Collector und den Bot alle 15s (`prometheus.yml`), stellt Daten Grafana zur Verfügung.

## 4. Deployment & Infrastruktur

- **Netz:** Compose erstellt Default-Netzwerk, so dass Services via DNS (`rag-service`, `qdrant`, `ollama`, …) erreichbar sind.
- **Persistenz:** Textdaten liegen im Workspace (`rag/data`). Qdrant-, Ollama- und Reranker-Volumes sichern Vektoren/Modelle zwischen Container-Neustarts.
- **Build-/Startbefehle:** Python-Services installieren Abhängigkeiten bei jedem Start (`pip install .`). Bot installiert npm-Dependencies on-the-fly (Trade-off zwischen Einfachheit und Startzeit).
- **Ports:** Standard-Ports werden extern gemappt (8000 FastAPI, 8082 Reranker, 8100 Extractor, 8800 MCP, 3978 Bot, 5005 Rasa, 5055 Action-Server, 8001 Metrics Action-Server, 11434 Ollama, 6333 Qdrant, 9090 Prometheus, 3000 Grafana).
- **Qdrant-Parameter:** Collection wird beim ersten Ingest mit `vector_size=768` (Default `nomic-embed-text`) und Distanz `cosine` angelegt; Einbettungsmodell und Collection müssen zusammenpassen.
- **Access Control:** RAG-Endpunkte sind nicht geschützt; nur Git-Webhook erwartet Signatur (`Settings.webhook_secret`). Rasa/Action-Server liefern keine Auth; Rollen-basierte Filter sind ausschließlich logischer Natur (Trennung durch Metadaten).

## 5. Konfiguration & Secrets

- `.env` im `rag/`-Verzeichnis konfiguriert Settings. Wichtige Parameter: Ollama/Qdrant/Reranker URLs, `default_dataset_path`, `git_repos`, `default_roles`, `webhook_secret`.
- Tokenizer: `tokenizer_encoding` (tiktoken-Encoding, Standard `cl100k_base`, `None` schaltet auf Whitespace-Splitting zurück).
- Reranker-Konfiguration: `RERANKER_URL` (URL des TEI-Service), `RERANKER_TOP_K` (Ergebnisse nach Re-Ranking), `RERANKER_INITIAL_K` (Kandidaten für Re-Ranking). Um Re-Ranking zu deaktivieren, `RERANKER_URL` leer lassen.
- Git-Repos können denselben Arbeitsbereich teilen, Pfade werden automatisch erstellt (`git_workspace_root`).
- Extractor benötigt `EXTRACT_OUTPUT_DIR` (Default `/data` -> gemountet auf `rag/data`) und optional `RAG_SERVICE_URL`.
- MCP-Gateway erwartet `RAG_SERVICE_URL` und optional `MCP_TRANSPORT` (Std. `streamable-http`).
- Bot-Env: `NLU_ENDPOINT`, `RAG_ENDPOINT`, `PORT`, `NLU_CONFIDENCE_THRESHOLD` (Default 0.7), `NLU_TIMEOUT_MS`, `NLU_STATUS_TIMEOUT_MS`, `NLU_CACHE_SIZE` (Default 500), `NLU_CACHE_TTL_MS` (Default 300000), `METRICS_PORT` (Default 9100), `METRICS_PATH` (Default `/metrics`).

## 6. Sicherheit & Compliance

- **Netzwerkgrenzen:** Alle Dienste laufen lokal; sobald Ports veröffentlicht werden, ist Authentifizierung notwendig (derzeit nicht implementiert).
- **Webhook-Absicherung:** Nur `/git/webhook/{repo}` prüft Signatur (HMAC-SHA256). Secret wird über `WEBHOOK_SECRET` gesetzt.
- **Rollenkonzept:** Rollen sind Metadaten pro Chunk; Matching erfolgt über `MatchAny`. Enforcement gilt nur bei Retrieval, nicht beim Speichern/Abrufen der Rohdateien im Dateisystem.
- **Dateizugriff:** Extractor schreibt direkt ins Workspace-Volume. Host sollte Dateisystemberechtigungen prüfen, da jeder Benutzer Markdown-Dateien lesen könnte.

## 7. Betrieb & Erweiterbarkeit

- **Monitoring:** `docker compose logs <service>` für Troubleshooting; Qdrant-Dashboard unter `localhost:6333/dashboard`. Prometheus scrapt Bot (`/metrics`) und Action-Server (`:8001/metrics`), RAG selbst liefert keine Prometheus-Metriken.
- **Training/Tests:** Rasa train/test per `docker compose run --rm rasa train` und `rasa test nlu/core`; Actions per `pytest` in `rasa/actions/tests`. E2E-REST-Sequenzen gegen `/webhooks/rest/webhook` ergänzen.
- **Betrieb Rasa:** Rasa benötigt laufenden Action-Server (`5055`) für Custom Actions. Default-Tracker ist In-Memory; für skalierte Setups Redis o. ä. als Tracker-Store konfigurieren. `endpoints.yml` zeigt auf `http://action-server:5055/webhook`.
- **Skalierung:** Compose-Setup ist für Ein-Knoten-Entwicklung gedacht. RAG-Service und Action-Server sind stateless und horizontal skalierbar; Qdrant ist clusterfähig; TEI-Reranker replizierbar, aber CPU-intensiv; Rasa skaliert nur mit gemeinsamem Tracker-Store. Ollama skaliert nicht horizontal (Single-Process); für mehr Durchsatz externes LLM/Embeddings nutzen. In Produktion AuthN/AuthZ und Secret-Handling ergänzen.
- **Erweiterungen:** 
  - Weitere Dokumentquellen über zusätzliche Endpunkte/Loader (z. B. S3) anbinden.
  - Rasa: neue Intents/Slots/Stories per `domain.yml`/`data/*.yml` und Actions ergänzen.
  - MCP-Gateway um neue Tools erweitern (z. B. `rag.delete`) durch zusätzliche `@server.tool`-Funktionen.

## 8. Bekannte Einschränkungen

- Ingest-Zeit steigt linear mit Dokumentgröße; es gibt keine Hintergrund-Jobs oder Warteschlangen – alle Operationen laufen synchron innerhalb der HTTP-Requests.
- Keine dedizierte Authentifizierung oder Rate-Limits an den REST-Endpunkten (Rasa/Action-Server/RAG). Rollen wirken nur als Metadaten-Filter in Qdrant.
- Observability: RAG-/Extractor-Services haben keine OTLP-Instrumentierung und keine Prometheus-Metriken; Action-Server liefert nur Counters, keine Latenzen. End-to-End-Tracing fehlt.
- Bot/Rasa sind Referenzimplementierungen; Tracker-Store ist In-Memory, daher kein Shared-State bei Skalierung und kein Persistenz-Backup. Multi-Role-Handling erfolgt nur über Slots/Metadaten.
- Reranker läuft als Cross-Encoder im CPU-Image, skaliert linear mit K, kein Batch über Paare; großes Modell (≈2,2 GB) verursacht längeren Cold-Start, `max_batch_requests` wird vom Dienst automatisch reduziert und GPU-Deployments bringen deutliche Vorteile.

Dieses Dokument soll als Einstieg dienen. Für detaillierte Implementierungsdetails siehe die jeweils referenzierten Dateien (`rag/app/*.py`, `extractor/app/main.py`, `mcp/app/main.py`, `bot/src/index.js`, Compose-File).
