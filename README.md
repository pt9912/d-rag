# Lokales RAG-Setup

Dieses Verzeichnis enthält einen Docker-Compose-Stack, der einen einfachen Bot (Express), Rasa NLU, Observability-Komponenten (OTel Collector, Prometheus, Grafana) sowie einen lokalen RAG-Service mit Qdrant und Ollama startet. Hinweis: Die Applikationen senden ohne zusätzliche Instrumentierung keine OTEL-Traces/Metriken; Grafana/Prometheus bleiben daher leer, bis SDKs eingebaut werden.
(MAF: https://github.com/microsoft/Agent-Framework-Samples/tree/main/06.RAGs)

## Aufbau

- `docker-compose.yml`: startet alle Services inkl. Bot, Rasa, Qdrant, Ollama, Reranker und dem FastAPI-RAG-Service.
- `rag/`: FastAPI-App, die Dokumente in Qdrant ingestiert (Chunking + Embeddings per Ollama), per BGE-Reranker re-rankt und Anfragen beantwortet.
- `extractor/`: FastAPI-Dienst zur PDF-Extraktion und optionalem Triggern des RAG-Updates.
- `mcp/`: JSON-RPC-Gateway (Model Context Protocol) für Tools wie `rag.query`, `rag.ingest`, `rag.update`.
- `bot/`: Express-Stub, der Fragen an den RAG-Service weiterleitet (`POST /ask`).
- `rasa/`, `otel-collector-config.yaml`, `prometheus.yml`: Minimal-Configs für NLU bzw. Observability.

## Nutzung

1. **Modelle laden** (nur einmal nötig; Ollama muss laufen):
   ```bash
   docker compose up -d ollama  # falls der Stack noch nicht läuft
   docker compose exec ollama ollama pull nomic-embed-text
   docker compose exec ollama ollama pull llama3
   ```
   Der Reranker (`BAAI/bge-reranker-large`) wird beim ersten Start automatisch heruntergeladen.

2. **Stack starten**:
   ```bash
   docker compose up -d
   ```
   Der RAG-Service ingestiert beim Start automatisch `rag/data/demo.md`.

3. **Bot-Route testen**:
   - Die Route `POST /ask` spricht intern `http://rag-service:8000/query` an.
   - Sobald die Ports nach außen erreichbar sind:
     ```bash
     curl -X POST localhost:3978/ask \
          -H "Content-Type: application/json" \
          -d '{"question":"What is GraphRAG?","roles":["public"]}' | jq
     ```
     Rollen können alternativ auch per Header übergeben werden: `-H "X-Roles: public,internal"`.

4. **Eigene Dokumente & Updates**:
   - Dateien nach `rag/data/` legen (oder einen anderen Pfad wählen) und per
     ```bash
     curl -X POST localhost:8000/ingest \
          -H "Content-Type: application/json" \
          -d '{"path": "data/demo.md", "roles": ["public", "internal"]}' | jq
     ```
     ingestieren.
   - Für ein Update ohne Neustart denselben Pfad an `/update` senden:
     ```bash
     curl -X POST localhost:8000/update \
          -H "Content-Type: application/json" \
          -d '{"path": "data/demo.md", "roles": ["public", "internal"]}' | jq
     ```
     Dadurch werden alte Chunks gelöscht und sofort neu geschrieben.
   - Alternativ den RAG-Service neu starten (`docker compose restart rag-service`), damit automatisch `default_dataset_path` neu ingestiert wird.
   - In `rag/app/config.py` kannst du den Default-Pfad (`default_dataset_path`) dauerhaft ändern.
   - Ordnerstrukturen sind erlaubt (z. B. `data/legal/vertrag.md`); der Ingest akzeptiert jeden existierenden Pfad.
   - Rollen werden beim Query berücksichtigt:
     ```bash
     curl -X POST localhost:8000/query \
          -H "Content-Type: application/json" \
          -d '{"question":"What is GraphRAG?","roles":["public"]}' | jq
     ```
     Nur Dokumente, deren Rollenliste sich mit der Anfrage überschneidet, werden als Kontext genutzt.

5. **PDFs extrahieren**:
   - Der neue Dienst läuft auf Port 8100.
   - Beispiel-Upload mit automatischem RAG-Update:
     ```bash
     curl -X POST http://localhost:8100/extract/pdf \
          -F "file=@/pfad/zur/datei.pdf" \
          -F "target_name=graph-faq" \
          -F "roles=public,internal" \
          -F "auto_update=true" | jq
     ```
     Das extrahierte Markdown landet in `rag/data/graph-faq.md` und `/update` wird im Erfolgsfall automatisch aufgerufen. Ohne `auto_update=true` kannst du den Pfad anschließend manuell ingestieren.
   - ZIP-Support (`/extract/zip`): mehrere PDFs gebündelt hochladen.
     ```bash
     curl -X POST http://localhost:8100/extract/zip \
          -F "file=@/pfad/zu/dokumente.zip" \
          -F "roles=public" \
          -F "auto_update=true" | jq
     ```
     Jede PDF im Archiv wird extrahiert und – falls aktiviert – direkt aktualisiert.

6. **Alte Daten entfernen**:
   - Ganze Collection löschen und frisch befüllen:
     ```bash
     curl -X DELETE http://localhost:6333/collections/demo_documents
     docker compose restart rag-service  # erstellt die Collection neu
     ```
   - Selektives Löschen (alle Chunks einer Datei):
     ```bash
     curl -X POST http://localhost:6333/collections/demo_documents/points/delete \
          -H "Content-Type: application/json" \
          -d '{"filter":{"must":[{"key":"source","match":{"value":"data/obsolete.md"}}]}}'
     ```
     Anschließend die aktualisierte Datei erneut ingestieren.

7. **MCP-Gateway (JSON-RPC) nutzen**:
   - Der Dienst läuft auf Port 8800 und akzeptiert JSON-RPC-Anfragen auf `/mcp`.
   - Tools auflisten:
     ```bash
     curl -X POST http://localhost:8800/mcp \
          -H "Content-Type: application/json" \
          -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq
     ```
   - Tool-Aufruf (Query):
     ```bash
     curl -X POST http://localhost:8800/mcp \
          -H "Content-Type: application/json" \
          -d '{"jsonrpc":"2.0","id":"call-1","method":"tools/call","params":{"name":"rag.query","arguments":{"question":"What is GraphRAG?","roles":["public"]}}}' | jq
     ```
   - Unterstützte Tools: `rag.query`, `rag.ingest`, `rag.update`. Die Argumente entsprechen den jeweiligen REST-Endpunkten.

## Tipps

- `rag-service`-Logs kontrollierst du mit `docker compose logs rag-service`.
- Extraktor-Logs: `docker compose logs extractor`.
- MCP-Gateway: `docker compose logs mcp`.
- Reranker-Logs: `docker compose logs reranker`.
- Der Qdrant-Dashboard ist über `http://localhost:6333/dashboard` erreichbar.
- Zum Stoppen einfach `docker compose down`. Volumes (`qdrant_data`, `ollama_models`, `reranker_models`) behalten Vectorstore, Modelle und Reranker.

## Reranker-Konfiguration

Der RAG-Service nutzt einen BGE-Reranker (TEI) zur Verbesserung der Suchergebnisse. Die Vektorsuche liefert zunächst mehr Kandidaten (`reranker_initial_k`, default 20), die dann nach semantischer Relevanz re-rankt werden. Nur die Top-Ergebnisse (`max_context_chunks`, default 4) werden dem LLM übergeben.

Konfiguration über Umgebungsvariablen:
- `RERANKER_URL`: URL des Reranker-Service (default: `http://reranker:80`)
- `RERANKER_TOP_K`: Anzahl Ergebnisse nach Re-Ranking (default: 4)
- `RERANKER_INITIAL_K`: Anzahl Kandidaten für Re-Ranking (default: 20)

Um den Reranker zu deaktivieren, setze `RERANKER_URL` auf einen leeren String.
