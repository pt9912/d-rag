# Sprint-Task: Extractor-Endpoint für Aggregiertes Markdown

## Ziel

Einen neuen Endpoint `/extract/aggregated-md` im Extractor-Service implementieren, der das aggregierte Markdown-Format parst, Metadaten extrahiert und die Chunks mit erweiterten Metadaten im RAG-System speichert.

## User Story

> Als Anwender möchte ich eine aggregierte Projekt-Markdown-Datei hochladen, damit alle enthaltenen Dokumente und Code-Dateien automatisch mit korrekten Metadaten (Projekt, Dokument-Typ, Sprache) im RAG-System indexiert werden.

## Anforderungen

### Funktional

| ID | Anforderung | Priorität |
|----|-------------|-----------|
| F1 | Endpoint `/extract/aggregated-md` akzeptiert Markdown-Upload | Must |
| F2 | Parsen der `# PROJEKTBESCHREIBUNG` Sektion | Must |
| F3 | Extraktion von `project_name` aus Projektbeschreibung | Must |
| F4 | Parsen aller `## DATEI:` Sektionen | Must |
| F5 | Erkennung des `doc_type` aus Dateipfad/Inhalt | Must |
| F6 | Extraktion der Code-Fence-Sprache als `language` | Must |
| F7 | Ableitung von `directory` und `extension` aus Pfad | Must |
| F8 | Speicherung jeder Datei als separater Chunk mit Metadaten | Must |
| F9 | Speicherung von Projektbeschreibung als Meta-Chunk | Should |
| F10 | Speicherung von Verzeichnisstruktur als Meta-Chunk | Could |
| F11 | Auto-Update im RAG-Service triggern | Should |

### Nicht-funktional

| ID | Anforderung |
|----|-------------|
| NF1 | Verarbeitung von Dateien bis 50MB |
| NF2 | Fehlertoleranz bei malformed Markdown (partial success) |
| NF3 | Logging aller extrahierten Dateien |
| NF4 | Rückgabe detaillierter Statistiken |

## Technisches Design

### API-Spezifikation

**Endpoint:** `POST /extract/aggregated-md`

**Request:**
```
Content-Type: multipart/form-data

file: <aggregated-markdown-file>
auto_update: bool (default: false)
roles: string (comma-separated, optional)
project_name_override: string (optional, überschreibt extrahierten Namen)
```

**Response (200 OK):**
```json
{
  "project_name": "Kundenportal-v2",
  "project_id": "kundenportal-v2",
  "files_extracted": 42,
  "chunks": [
    {
      "source": "./docs/lastenheft.md",
      "doc_type": "lastenheft",
      "language": "markdown",
      "chars": 4523
    },
    {
      "source": "./src/main.py",
      "doc_type": "source_code",
      "language": "python",
      "chars": 1892
    }
  ],
  "meta_chunks": [
    {"type": "projektbeschreibung", "chars": 512},
    {"type": "verzeichnisstruktur", "chars": 1024}
  ],
  "rag_update": "ok"
}
```

**Response (422 Unprocessable Entity):**
```json
{
  "detail": "Keine DATEI-Sektionen gefunden"
}
```

### Parser-Architektur

```python
@dataclass
class ParsedFile:
    source: str           # ./src/main.py
    content: str          # Dateiinhalt
    language: str         # python
    doc_type: str         # source_code
    directory: str        # ./src
    extension: str        # .py

@dataclass
class ParsedProject:
    project_name: str
    project_id: str
    beschreibung: str
    verzeichnisstruktur: str
    files: list[ParsedFile]

class AggregatedMarkdownParser:
    def parse(self, content: str) -> ParsedProject
    def _extract_projektbeschreibung(self, content: str) -> tuple[str, str]
    def _extract_verzeichnisstruktur(self, content: str) -> str
    def _extract_files(self, content: str) -> list[ParsedFile]
    def _detect_doc_type(self, filepath: str, content: str) -> str
    def _extract_project_name(self, beschreibung: str) -> str
```

### Dokument-Typ-Erkennung

```python
DOC_TYPE_PATTERNS = {
    'lastenheft': [
        r'lastenheft', r'anforderung', r'requirements',
        r'stakeholder', r'rahmenbedingung'
    ],
    'pflichtenheft': [
        r'pflichtenheft', r'spec', r'specification',
        r'abnahmekriterien', r'technische.*spezifikation'
    ],
    'architektur': [
        r'architektur', r'architecture', r'ARCHITECTURE',
        r'system.*design', r'komponenten.*übersicht'
    ],
    'design': [
        r'design', r'entwurf', r'konzept', r'datenmodell',
        r'sequenz', r'klassendiagramm'
    ],
}

CODE_EXTENSIONS = {'.py', '.js', '.ts', '.java', '.cpp', '.c', '.h',
                   '.go', '.rs', '.rb', '.php', '.cs', '.swift', '.kt'}

def detect_doc_type(filepath: str, content: str) -> str:
    ext = Path(filepath).suffix.lower()
    if ext in CODE_EXTENSIONS:
        return 'source_code'

    filepath_lower = filepath.lower()
    content_lower = content[:500].lower()  # Nur Anfang prüfen

    for doc_type, patterns in DOC_TYPE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, filepath_lower) or re.search(pattern, content_lower):
                return doc_type

    return 'dokument'  # Fallback für .md ohne erkannten Typ
```

### Projekt-Name-Extraktion

```python
def extract_project_name(beschreibung: str) -> str:
    """Extrahiert Projektnamen aus Projektbeschreibung."""
    patterns = [
        r'Projektname:\s*(.+?)(?:\n|$)',
        r'Projekt:\s*(.+?)(?:\n|$)',
        r'Name:\s*(.+?)(?:\n|$)',
        r'^#\s*(.+?)(?:\n|$)',  # Erster Header
    ]
    for pattern in patterns:
        match = re.search(pattern, beschreibung, re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1).strip()
    return "unbekannt"
```

### Metadaten-Schema für Qdrant

```python
chunk_metadata = {
    # Projekt-Ebene
    "project_name": "Kundenportal-v2",
    "project_id": "kundenportal-v2",

    # Datei-Ebene
    "source": "./src/api/handlers.py",
    "doc_type": "source_code",  # lastenheft|pflichtenheft|architektur|design|source_code|meta
    "language": "python",
    "directory": "./src/api",
    "extension": ".py",

    # Standard-Felder
    "roles": ["dev", "architect"],  # Optional, vom Upload
}
```

### Integration mit RAG-Service

```python
async def trigger_rag_update(
    files: list[ParsedFile],
    project_id: str,
    roles: list[str] | None
) -> str:
    """Sendet extrahierte Chunks an RAG-Service."""
    if not RAG_SERVICE_URL:
        return "skipped"

    try:
        for file in files:
            # Chunk mit Metadaten senden
            payload = {
                "content": file.content,
                "metadata": {
                    "project_id": project_id,
                    "project_name": file.project_name,
                    "source": file.source,
                    "doc_type": file.doc_type,
                    "language": file.language,
                    "directory": file.directory,
                    "extension": file.extension,
                    "roles": roles,
                }
            }
            resp = await httpx.post(
                f"{RAG_SERVICE_URL}/ingest",
                json=payload,
                timeout=30
            )
            resp.raise_for_status()
        return "ok"
    except Exception as e:
        return f"failed: {e}"
```

## Abnahmekriterien

- [ ] Endpoint akzeptiert aggregierte Markdown-Dateien
- [ ] Projektname wird korrekt aus Beschreibung extrahiert
- [ ] Alle `## DATEI:` Sektionen werden geparst
- [ ] `doc_type` wird korrekt erkannt (lastenheft, pflichtenheft, architektur, design, source_code)
- [ ] Metadaten werden korrekt an RAG-Service übergeben
- [ ] Response enthält detaillierte Statistiken
- [ ] Fehlerhafte Sektionen werden übersprungen (partial success)

## Testfälle

| ID | Testfall | Erwartetes Ergebnis |
|----|----------|---------------------|
| T1 | Valide aggregierte MD-Datei | 200 OK, alle Dateien extrahiert |
| T2 | Fehlende PROJEKTBESCHREIBUNG | 200 OK, project_name = "unbekannt" |
| T3 | Keine DATEI-Sektionen | 422 Error |
| T4 | Gemischte Dokument-Typen | Korrekte doc_type Erkennung |
| T5 | Große Datei (>10MB) | Erfolgreiche Verarbeitung |
| T6 | Malformed Code-Fence | Datei wird übersprungen, Rest verarbeitet |
| T7 | Deutsche + englische Patterns | Beide werden erkannt |

## Änderungen am RAG-Service

Der RAG-Service benötigt eine Erweiterung des `/ingest` Endpoints:

```python
# Neues Request-Schema
class IngestRequestV2(BaseModel):
    content: str
    metadata: dict[str, Any]  # Erweiterte Metadaten

# Bestehender Endpoint erweitern oder neuen hinzufügen
@app.post("/ingest/chunk")
async def ingest_chunk(request: IngestRequestV2):
    # Chunk mit Metadaten speichern
    pass
```

## Aufwand

| Komponente | Aufwand |
|------------|---------|
| Parser-Implementierung | M |
| Endpoint-Integration | S |
| Doc-Type-Erkennung | S |
| RAG-Service Erweiterung | M |
| Tests | M |
| Dokumentation | S |
| **Gesamt** | **L** |

## Abhängigkeiten

- Sprint-Task 1 (Generator-Tool) für Testdaten
- RAG-Service Erweiterung für erweiterte Metadaten

## Offene Fragen

1. Soll der Parser auch verschachtelte Code-Fences unterstützen (Markdown in Markdown)?
2. Wie sollen sehr große Dateien (>100KB pro Datei) behandelt werden – zusätzliches Chunking?
3. Soll es einen Batch-Upload für mehrere Projekte geben (`/extract/aggregated-md/batch`)?
4. Sollen bestehende Projekt-Chunks beim Re-Upload gelöscht werden (Upsert-Verhalten)?
