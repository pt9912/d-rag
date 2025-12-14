# Federated RAG Architektur mit LangChain 1.0 und MCP

> Hinweis: Für die **aktuelle Ist-Architektur** gibt es `docs/ARCHITECTURE.md`.
> Dieses Dokument beschreibt eine **mögliche Federated-RAG-Integration** als Zielbild: mehrere spezialisierte RAG-Module werden parallel betrieben und über MCP von einem Agenten geroutet/orchestriert.

## 1. Überblick
Diese Architektur ergänzt ein monolithisches RAG-Setup um **spezialisierte, isolierte RAG-Module** ("Microservices für Wissen"), die über das **Model Context Protocol (MCP)** orchestriert werden. Jedes Modul ist für eine Domäne (z. B. Java, Python, Tickets) optimiert und wird über einen MCP-Endpunkt als Tool-Provider bereitgestellt.

Bezug zum Repo:
- Dieses Repo bringt bereits ein **MCP-Gateway** mit (Tools `rag.query`, `rag.ingest`, `rag.update`, siehe `mcp/app/main.py`).
- Federated-RAG bedeutet hier: **mehrere Instanzen** (oder Varianten) dieses Moduls parallel betreiben (z. B. je Domäne eigene Datenbasis, Chunking, Embeddings, Reranker, Collection/Vectorstore) und im Agenten passend routen.
- Für Federated-Routing sollte die **MCP-Description/Instructions** pro Gateway **konfigurierbar** sein (z. B. via `MCP_INSTRUCTIONS`), damit ein Agent die Zuständigkeiten der Domänen sauber unterscheiden kann.
- Zusätzlich sollten **Chunking-Parameter/Strategie** und das **Indexing-Metadaten-Schema** konfigurierbar sein (idealerweise über Dokumenttypen wie Confluence/Jira), damit Retrieval (Filter, ACL/Rollen, Routing) zuverlässig funktioniert.

---

## 2. Architektur-Diagramm

```plaintext
┌──────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                            LangChain-Agent                                           │
│  ┌────────────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │                                                                                                │  │
│  │  ┌───────────────────────────┐   ┌───────────────────────────┐   ┌──────────────────────────┐  │  │
│  │  │ MCP-Gateway: Java         │   │ MCP-Gateway: Dokumente    │   │ MCP-Gateway: Tickets     │  │  │
│  │  │ Tools: rag.query/...      │   │ Tools: rag.query/...      │   │ Tools: rag.query/...     │  │  │
│  │  └───────────┬───────────────┘   └───────────┬───────────────┘   └───────────┬──────────────┘  │  │
│  │              │                               │                               │                 │  │
│  │  ┌───────────▼───────────────┐   ┌───────────▼───────────────┐   ┌───────────▼──────────────┐  │  │
│  │  │ RAG-Service: Java         │   │ RAG-Service: Dokumente    │   │ RAG-Service: Tickets     │  │  │
│  │  │ Chunking/Embeddings/etc.  │   │ Chunking/Embeddings/etc.  │   │ Chunking/Embeddings/etc. │  │  │
│  │  └───────────┬───────────────┘   └───────────┬───────────────┘   └───────────┬──────────────┘  │  │
│  │              │                               │                               │                 │  │
│  │  ┌───────────▼───────────────┐   ┌───────────▼───────────────┐   ┌───────────▼───────────────┐ │  │
│  │  │ Vectorstore (z. B. Qdrant)│   │ Vectorstore (z. B. Qdrant)│   │ Vectorstore (z. B. Qdrant)│ │  │
│  │  │ Collection/Namespace: java│   │ Collection/Namespace: docs│   │ Collection/NS:      ticket│ │  │
│  │  └───────────────────────────┘   └───────────────────────────┘   └───────────────────────────┘ │  │
│  │                                                                                                │  │
│  └───────────────────────────┬────────────────────────────────────────────────────────────────────┘  │
│                              │                                                                       │
│                       ┌──────▼───────────────────────────┐                                           │
│                       │ MCP Client / Tool-Adapter        │                                           │
│                       │ (Discovery + Parallel Calls)     │                                           │
│                       └──────────────────────────────────┘                                           │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Komponenten

### 3.1 RAG-Module (RAG-Service + MCP-Gateway)
- **Zweck**: Bereitstellung domänenspezifischer Wissensabfrage als MCP-Tools.
- **Technische Umsetzung**:
  - Pro Domäne existiert typischerweise:
    - ein **RAG-Service** (z. B. FastAPI) für `/query`, `/ingest`, `/update` (ähnlich `rag-service` in diesem Repo),
    - ein **MCP-Gateway** (z. B. FastMCP) das diese REST-Endpunkte als MCP-Tools exportiert (ähnlich `mcp` in diesem Repo).
  - **Wichtig für Federated-Betrieb**:
    - Die MCP-Server-Metadaten (insb. *Description/Instructions*) sollten pro Instanz konfigurierbar sein, z. B. per Env-Var `MCP_INSTRUCTIONS="Gateway für Java-Doku (nur Code- und API-Fragen)"`.
    - Chunking sollte konfigurierbar sein (mindestens Größe/Overlap/Tokenizer; je nach Typ auch eine abweichende Strategie wie Header-/AST-/Field-basiertes Chunking).
    - Indexing-Metadaten sollten konsistent und filterbar sein (z. B. `roles`, `source_kind`, `source_id`, `doc_type`, `domain`, `language`, `product`, `updated_at_ts`), damit:
      - der Agent zuverlässig routen kann,
      - Zugriffskontrolle (z. B. Rollen) durchgängig bleibt,
      - Updates/Löschungen eindeutig adressierbar sind.
    - In der Praxis ist es oft stabiler, **Chunking-Strategie und Metadaten-Policy über Dokumenttypen** festzulegen:
      - `source_kind` beschreibt die Quelle/Struktur (z. B. `confluence`, `jira`, `git`, `file`).
      - `doc_type` beschreibt die fachliche Kategorie (z. B. `runbook`, `adr`, `incident`, `howto`).
  - **MCP-Tool-Schema (Beispiel aus diesem Repo)**:
    - `rag.query`
    - `rag.ingest`
    - `rag.update`

- **Vorteile**:
  - Isolation: Änderungen an einem Modul beeinflussen andere nicht.
  - Optimierung: Chunking/Embeddings pro Domäne (z. B. hierarchisch für XML, zeitbasiert für Tickets).

#### 3.1.1 Dokumenttypen-Profile (Chunking + Metadaten)

Zielbild: Eine Ingest-Pipeline normalisiert Inhalte aus verschiedenen Quellen und wählt anhand von `source_kind`/`doc_type` ein Profil, das:
- eine Chunking-Strategie inkl. Parametern definiert,
- ein Metadaten-Minimalschema (Pflichtfelder) erzwingt,
- optionale Retrieval-Rescoring-Regeln (z. B. Recency-Boost) festlegt.

Beispiel-Mapping:

| `source_kind`  | Chunking-Strategie (Beispiel)          | Metadaten (Minimum)                                              | Besonderheiten |
| -------------- | -------------------------------------- | ---------------------------------------------------------------- | ------------- |
| `confluence`   | hierarchisch nach Überschriften        | `source_id`, `source_url`, `space_key`, `updated_at_ts`, `roles` | `section_path` für Struktur/Zitate |
| `jira`         | **pro Ticket ein Dokument**            | `source_id`, `source_url`, `project_key`, `issue_key`, `updated_at_ts`, `roles` | optional: zeitbasiertes Boosting |
| `aggregated-md`| projektweise, split pro Datei-Sektion  | `source_id`, `project_id`, `source_url?`, `doc_type`, `language`, `roles` | gut für Codebases (siehe `/extract/aggregated-md`) |
| `git`          | code-/datei-basiert (optional AST)     | `source_id`, `git_repo`, `git_path`, `git_commit`, `roles`       | Update/Delete über `git_*` |
| `file`         | token-basiert (Fallback)               | `source_id`, `source`, `updated_at_ts?`, `roles`                 | für Uploads/Extracts |

Skizze einer Konfiguration (z. B. als YAML/JSON), die pro `source_kind` Profile definiert:

```yaml
profiles:
  confluence:
    chunking:
      strategy: hierarchical_headers
      params: { chunk_size: 900, chunk_overlap: 150, tokenizer_encoding: cl100k_base }
    required_metadata: [source_kind, source_id, source_url, space_key, updated_at_ts, roles]

  jira:
    chunking:
      strategy: jira_issue_single_document
      params: { combine_fields: ["summary", "description", "comments"] }
    required_metadata: [source_kind, source_id, source_url, project_key, issue_key, updated_at_ts, roles]
    rescoring:
      recency_boost: { field: updated_at_ts, weight: 0.2, half_life_days: 30 }

  aggregated-md:
    chunking:
      strategy: aggregated_markdown_project_files
      params: { split_on: "## DATEI:", preserve_frontmatter: true }
    required_metadata: [source_kind, source_id, project_id, doc_type, language, roles]
```

### 3.2 MCP Client / Tool-Adapter (LangChain)
- **Zweck**: Verbindung zu allen MCP-Gateways, Laden der Tools (Discovery) und Ausführung (Call), optional in LangChain-Tools integriert.
- **Funktionen**:
  - Tool-Discovery via JSON-RPC `tools/list` und Tool-Calls via `tools/call`.
  - Parallele Tool-Ausführung (z. B. `asyncio`).
  - Fehlerbehandlung (Timeouts/Retry/Backoff).
  - Namens-/Routing-Logik (welcher Gateway für welche Frage?).

### 3.3 LangChain-Agent
- **Zweck**: Orchestrierung der Tools basierend auf Nutzeranfragen.
- **Technische Umsetzung**:
  - Tools werden dynamisch je nach Anfrage kombiniert.
  - Routing kann heuristisch (Keywords/Rules), per Klassifikator, oder per LLM-gestütztem Router erfolgen.

---

## 4. Workflow

1. **Nutzeranfrage**:
   ```plaintext
   "Wie implementiere ich ein Singleton in Go und dokumentiere es im Ticket-System?"
   ```
2. **Agent-Routing**:
   - Der Agent erkennt die Domänen `Go` und `Tickets`.
   - Parallelaufruf der passenden MCP-Tools (z. B. je Domäne `rag.query` auf dem jeweiligen Gateway).
3. **Tool-Ausführung**:
   - Go-Modul: Liefert Code-Beispiele.
   - Ticket-Modul: Liefert relevante Ticket-Vorlagen.
4. **Antwortsynthese**:
   - Der Agent kombiniert die Ergebnisse zu einer kohärenten Antwort.

---

## 5. Vorteile

| Aspekt              | Federated RAG                         | Monolithisches RAG                  |
| ------------------- | ------------------------------------- | ----------------------------------- |
| **Erweiterbarkeit** | Neue RAGs per Config hinzufügbar.     | Index muss neu aufgebaut werden.    |
| **Isolation**       | Module unabhängig deploy-/skalierbar. | Änderungen riskieren Seiteneffekte. |
| **Optimierung**     | Chunking/Embeddings pro Domäne.       | Kompromisse für alle Daten.         |
| **Wartung**         | Einfaches Update einzelner Module.    | Komplexe Migrationen.               |

---

## 6. Beispiel-Code

### 6.1 MCP-Gateway (ein RAG-Modul exportiert Tools)

In diesem Repo entspricht das in etwa `mcp/app/main.py` (FastMCP), das REST-Endpunkte des RAG-Services als MCP-Tools bereitstellt.

```python
import os
from mcp.server.fastmcp import FastMCP

server = FastMCP(
    name="rag-mcp-gateway-java",
    instructions=os.getenv("MCP_INSTRUCTIONS", "Gateway für Java-RAG."),
)

@server.tool(name="rag.query", description="Stellt eine Frage an den Java-RAG-Dienst.")
async def rag_query(question: str, roles: list[str] | None = None) -> str:
    # Implementierung: per HTTP an den passenden RAG-Service weiterleiten
    ...
```

### 6.2 MCP-Client (JSON-RPC Call; als LangChain-Tool wrappbar)

Minimal-Variante: Ein Adapter ruft MCP per JSON-RPC auf (`tools/list`, `tools/call`) und übersetzt die Antwort in ein Tool-Ergebnis.

```python
import httpx

async def mcp_tools_call(mcp_url: str, tool_name: str, arguments: dict) -> dict:
    payload = {
        "jsonrpc": "2.0",
        "id": "call-1",
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(mcp_url, json=payload)
        resp.raise_for_status()
        return resp.json()
```

In einer LangChain-Integration würde man daraus z. B. mehrere Tools bauen (je Gateway/Tool) und sie dem Agenten zur Verfügung stellen.

---

## 7. Deployment

- **Containerisierung**: Jedes RAG-Modul als Docker-Container (z. B. mit `docker-compose`).
- **Skalierung**: Horizontale Skalierung pro MCP-Server bei hoher Last.
- **Service-Discovery**: Optional mit Kubernetes/Consul für dynamische Registrierung.

### 7.1 docker-compose Skizze: Multi-Gateway (pro Domäne eigener MCP-Gateway)

```yaml
services:
  qdrant:
    image: qdrant/qdrant:latest
    ports: ["6333:6333"]

  rag-java:
    image: python:3.11-slim
    working_dir: /app
    command: ["bash", "-lc", "pip install --no-cache-dir . && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
    volumes: ["./rag:/app", "./git-workspace:/repos"]
    environment:
      QDRANT_URL: http://qdrant:6333
      COLLECTION_NAME: rag_java
      CHUNKING_PROFILE: aggregated-md
    depends_on: [qdrant]

  rag-docs:
    image: python:3.11-slim
    working_dir: /app
    command: ["bash", "-lc", "pip install --no-cache-dir . && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
    volumes: ["./rag:/app", "./git-workspace:/repos"]
    environment:
      QDRANT_URL: http://qdrant:6333
      COLLECTION_NAME: rag_docs
      CHUNKING_PROFILE: confluence
    depends_on: [qdrant]

  rag-tickets:
    image: python:3.11-slim
    working_dir: /app
    command: ["bash", "-lc", "pip install --no-cache-dir . && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
    volumes: ["./rag:/app", "./git-workspace:/repos"]
    environment:
      QDRANT_URL: http://qdrant:6333
      COLLECTION_NAME: rag_tickets
      CHUNKING_PROFILE: jira
    depends_on: [qdrant]

  mcp-java:
    image: python:3.11-slim
    working_dir: /app
    command: ["bash", "-lc", "pip install --no-cache-dir . && uvicorn app.main:app --host 0.0.0.0 --port 8800"]
    volumes: ["./mcp:/app"]
    ports: ["8801:8800"]
    environment:
      RAG_SERVICE_URL: http://rag-java:8000
      MCP_INSTRUCTIONS: Gateway für Java-RAG (Code, APIs, Libraries).
    depends_on: [rag-java]

  mcp-docs:
    image: python:3.11-slim
    working_dir: /app
    command: ["bash", "-lc", "pip install --no-cache-dir . && uvicorn app.main:app --host 0.0.0.0 --port 8800"]
    volumes: ["./mcp:/app"]
    ports: ["8802:8800"]
    environment:
      RAG_SERVICE_URL: http://rag-docs:8000
      MCP_INSTRUCTIONS: Gateway für Domänen-Dokumente (Guides, ADRs, Architektur).
    depends_on: [rag-docs]

  mcp-tickets:
    image: python:3.11-slim
    working_dir: /app
    command: ["bash", "-lc", "pip install --no-cache-dir . && uvicorn app.main:app --host 0.0.0.0 --port 8800"]
    volumes: ["./mcp:/app"]
    ports: ["8803:8800"]
    environment:
      RAG_SERVICE_URL: http://rag-tickets:8000
      MCP_INSTRUCTIONS: Gateway für Tickets (Incidents, Worklogs, Verlauf).
    depends_on: [rag-tickets]
```

Hinweis: `CHUNK_SIZE`, `CHUNK_OVERLAP`, `TOKENIZER_ENCODING` bleiben als sinnvolle **Defaults** für token-basiertes Chunking erhalten, aber im Federated-Zielbild werden sie typischerweise **aus dem Profil** (z. B. `confluence`/`jira`) abgeleitet bzw. überschrieben.

### 7.2 docker-compose Skizze: Single-Gateway-Router (ein MCP, mehrere Backends)

Diese Variante setzt einen zusätzlichen Service (z. B. `mcp-router`) voraus, der Tool-Calls entgegennimmt und anhand eines Routing-Signals (z. B. `domain`-Argument oder Tool-Namenspräfix) an die passenden RAG-Services weiterleitet.

```yaml
services:
  qdrant:
    image: qdrant/qdrant:latest
    ports: ["6333:6333"]

  rag-java:
    image: python:3.11-slim
    working_dir: /app
    command: ["bash", "-lc", "pip install --no-cache-dir . && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
    volumes: ["./rag:/app", "./git-workspace:/repos"]
    environment:
      QDRANT_URL: http://qdrant:6333
      COLLECTION_NAME: rag_java
      CHUNKING_PROFILE: aggregated-md
    depends_on: [qdrant]

  rag-docs:
    image: python:3.11-slim
    working_dir: /app
    command: ["bash", "-lc", "pip install --no-cache-dir . && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
    volumes: ["./rag:/app", "./git-workspace:/repos"]
    environment:
      QDRANT_URL: http://qdrant:6333
      COLLECTION_NAME: rag_docs
      CHUNKING_PROFILE: confluence
    depends_on: [qdrant]

  rag-tickets:
    image: python:3.11-slim
    working_dir: /app
    command: ["bash", "-lc", "pip install --no-cache-dir . && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
    volumes: ["./rag:/app", "./git-workspace:/repos"]
    environment:
      QDRANT_URL: http://qdrant:6333
      COLLECTION_NAME: rag_tickets
      CHUNKING_PROFILE: jira
    depends_on: [qdrant]

  mcp-router:
    image: python:3.11-slim
    working_dir: /app
    command: ["bash", "-lc", "pip install --no-cache-dir . && uvicorn app.main:app --host 0.0.0.0 --port 8800"]
    volumes: ["./mcp-router:/app"]
    ports: ["8800:8800"]
    environment:
      RAG_JAVA_URL: http://rag-java:8000
      RAG_DOCS_URL: http://rag-docs:8000
      RAG_TICKETS_URL: http://rag-tickets:8000
      MCP_INSTRUCTIONS: Federated MCP Router (Java/Dokumente/Tickets).
    depends_on: [rag-java, rag-docs, rag-tickets]
```

---

## 8. Offene Punkte & Erweiterungen
- **Topologie-Entscheidung**:
  - *Multi-Gateway*: pro Domäne eigenes MCP-Gateway + eigener RAG-Service (einfach zu isolieren, gut skalierbar).
  - *Single-Gateway-Router*: ein MCP-Gateway exportiert mehrere Tools und routet intern auf mehrere Backends (einfacher Client, aber Gateway wird kritischer Pfad).
- **Cross-Domain-Fragen**: Agent-Logik für kombinierte Anfragen optimieren.
- **Monitoring**: Metriken pro RAG (z. B. Antwortqualität mit RAGAS).
- **Sicherheit**: API-Keys und Rate-Limiting für MCP-Server.

---
