#!/bin/bash
#
# Test-Skript für Aggregiertes Markdown Import & Query
#
# Voraussetzung: docker compose -f docker-compose.test.yml up -d
#
# Verwendung:
#   ./tools/test_aggregated_import.sh
#   ./tools/test_aggregated_import.sh --generate  # Generiert zuerst Test-Projekt
#

set -e

# Farben für Output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

EXTRACTOR_URL="${EXTRACTOR_URL:-http://localhost:8100}"
RAG_URL="${RAG_URL:-http://localhost:8000}"
TEST_PROJECT_FILE="test_projekt_komplett.md"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Aggregiertes Markdown Import Test${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Funktion: Warte auf Service
wait_for_service() {
    local url=$1
    local name=$2
    local max_attempts=30
    local attempt=1

    echo -e "${YELLOW}Warte auf $name...${NC}"
    while [ $attempt -le $max_attempts ]; do
        if curl -s -f "$url" > /dev/null 2>&1; then
            echo -e "${GREEN}✓ $name ist bereit${NC}"
            return 0
        fi
        echo "  Versuch $attempt/$max_attempts..."
        sleep 2
        attempt=$((attempt + 1))
    done
    echo -e "${RED}✗ $name nicht erreichbar nach $max_attempts Versuchen${NC}"
    exit 1
}

# Funktion: Generiere Test-Projekt
generate_test_project() {
    echo -e "${YELLOW}Generiere Test-Projekt...${NC}"

    cat > "$TEST_PROJECT_FILE" << 'ENDOFFILE'
# VERZEICHNISSTRUKTUR
```text
.
├── docs/
│   ├── lastenheft.md
│   └── architektur.md
├── src/
│   ├── main.py
│   └── utils.py
└── README.md
```

---
# PROJEKTBESCHREIBUNG
Projektname: Demo-API-Service
Ziel: REST-API für Benutzerverwaltung mit CRUD-Operationen

Domäne: Backend-Service, API
Technologie-Stack: Python 3.11, FastAPI, SQLAlchemy, PostgreSQL
Architektur-Pattern: Clean Architecture, Repository Pattern

Problemstellung:
Legacy-System hatte keine standardisierte API. Ziel war eine moderne,
dokumentierte REST-API mit OpenAPI-Spezifikation.

Wichtige Entscheidungen:
- FastAPI für automatische OpenAPI-Dokumentation
- Repository Pattern für Datenbankabstraktion
- Pydantic für Validierung

Schlüsselkomponenten:
- api/routes: REST-Endpoints
- domain/models: Business-Entitäten
- infrastructure/repositories: Datenbankzugriff

Schlagworte: REST-API, FastAPI, CRUD, Benutzerverwaltung, Clean Architecture

---
# DATEIINHALTE

---
## DATEI: ./docs/lastenheft.md
```markdown
# Lastenheft: Demo-API-Service

## 1. Stakeholder
- Entwicklerteam
- Frontend-Applikation

## 2. Anforderungen

### 2.1 Funktionale Anforderungen
- **LF-001**: Benutzer anlegen (Name, Email, Rolle)
- **LF-002**: Benutzer abrufen (einzeln und Liste)
- **LF-003**: Benutzer aktualisieren
- **LF-004**: Benutzer löschen

### 2.2 Nicht-funktionale Anforderungen
- **NF-001**: Antwortzeit < 200ms für 95% der Requests
- **NF-002**: OpenAPI 3.0 Dokumentation
- **NF-003**: JSON als Austauschformat
```

---
## DATEI: ./docs/architektur.md
```markdown
# Architektur: Demo-API-Service

## Übersicht

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Client    │────▶│  FastAPI    │────▶│  PostgreSQL │
└─────────────┘     └─────────────┘     └─────────────┘
```

## Schichten

1. **API-Schicht** (`api/routes.py`)
   - REST-Endpoints
   - Request/Response Validierung

2. **Domain-Schicht** (`domain/models.py`)
   - Business-Entitäten
   - Validierungsregeln

3. **Infrastruktur-Schicht** (`infrastructure/`)
   - Repository-Implementierungen
   - Datenbankzugriff

## Entscheidungen

- **FastAPI** statt Flask: Bessere Performance, native async-Unterstützung
- **SQLAlchemy 2.0**: Moderner ORM mit Type-Hints
- **Pydantic**: Automatische Validierung und Serialisierung
```

---
## DATEI: ./src/main.py
```python
"""Demo-API-Service Hauptmodul."""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr
from typing import Optional
from uuid import UUID, uuid4

app = FastAPI(
    title="Demo-API-Service",
    description="REST-API für Benutzerverwaltung",
    version="1.0.0",
)

# In-Memory Storage (Demo)
users_db: dict[UUID, "User"] = {}


class UserCreate(BaseModel):
    """Schema für Benutzer-Erstellung."""
    name: str
    email: EmailStr
    role: str = "user"


class User(BaseModel):
    """Schema für Benutzer."""
    id: UUID
    name: str
    email: EmailStr
    role: str


@app.post("/users", response_model=User)
async def create_user(user_data: UserCreate) -> User:
    """Erstellt einen neuen Benutzer."""
    user = User(id=uuid4(), **user_data.model_dump())
    users_db[user.id] = user
    return user


@app.get("/users", response_model=list[User])
async def list_users() -> list[User]:
    """Listet alle Benutzer auf."""
    return list(users_db.values())


@app.get("/users/{user_id}", response_model=User)
async def get_user(user_id: UUID) -> User:
    """Ruft einen Benutzer ab."""
    if user_id not in users_db:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
    return users_db[user_id]


@app.delete("/users/{user_id}")
async def delete_user(user_id: UUID) -> dict:
    """Löscht einen Benutzer."""
    if user_id not in users_db:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
    del users_db[user_id]
    return {"status": "deleted"}
```

---
## DATEI: ./src/utils.py
```python
"""Hilfsfunktionen für Demo-API-Service."""

import re
from typing import Optional


def validate_email(email: str) -> bool:
    """Validiert eine E-Mail-Adresse."""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def slugify(text: str) -> str:
    """Konvertiert Text in URL-sicheren Slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text


def truncate(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """Kürzt Text auf maximale Länge."""
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix
```

---
## DATEI: ./README.md
```markdown
# Demo-API-Service

REST-API für Benutzerverwaltung mit FastAPI.

## Installation

```bash
pip install -r requirements.txt
```

## Starten

```bash
uvicorn src.main:app --reload
```

## API-Dokumentation

Nach dem Start verfügbar unter:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
```
ENDOFFILE

    echo -e "${GREEN}✓ Test-Projekt generiert: $TEST_PROJECT_FILE${NC}"
}

# Prüfe ob --generate Flag gesetzt
if [ "$1" == "--generate" ]; then
    generate_test_project
fi

# Prüfe ob Test-Datei existiert
if [ ! -f "$TEST_PROJECT_FILE" ]; then
    echo -e "${YELLOW}Test-Datei nicht gefunden. Generiere...${NC}"
    generate_test_project
fi

# Warte auf Services
echo ""
wait_for_service "$EXTRACTOR_URL/healthz" "Extractor"
wait_for_service "$RAG_URL/healthz" "RAG-Service"

# Test 1: Import
echo ""
echo -e "${BLUE}--- Test 1: Import aggregiertes Markdown ---${NC}"
echo "Datei: $TEST_PROJECT_FILE"

IMPORT_RESPONSE=$(curl -s -X POST "$EXTRACTOR_URL/extract/aggregated-md" \
    -F "file=@$TEST_PROJECT_FILE" \
    -F "auto_update=true" \
    -F "roles=dev,architect")

echo "Response:"
echo "$IMPORT_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$IMPORT_RESPONSE"

# Prüfe Erfolg
if echo "$IMPORT_RESPONSE" | grep -q '"project_name"'; then
    echo -e "${GREEN}✓ Import erfolgreich${NC}"
    PROJECT_NAME=$(echo "$IMPORT_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['project_name'])" 2>/dev/null || echo "unknown")
    FILES_COUNT=$(echo "$IMPORT_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['files_extracted'])" 2>/dev/null || echo "0")
    echo "  Projekt: $PROJECT_NAME"
    echo "  Dateien: $FILES_COUNT"
else
    echo -e "${RED}✗ Import fehlgeschlagen${NC}"
    exit 1
fi

# Warte kurz für Indexierung
echo ""
echo -e "${YELLOW}Warte 5 Sekunden für Indexierung...${NC}"
sleep 5

# Test 2: Query - Architektur
echo ""
echo -e "${BLUE}--- Test 2: Query - Architektur ---${NC}"
echo "Frage: Welches Architektur-Pattern wird verwendet?"

QUERY_RESPONSE=$(curl -s -X POST "$RAG_URL/query" \
    -H "Content-Type: application/json" \
    -d '{"question": "Welches Architektur-Pattern wird im Demo-API-Service verwendet?"}')

echo "Response:"
echo "$QUERY_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$QUERY_RESPONSE"

if echo "$QUERY_RESPONSE" | grep -qi "clean\|repository\|pattern\|architektur"; then
    echo -e "${GREEN}✓ Query erfolgreich - Architektur-Pattern gefunden${NC}"
else
    echo -e "${YELLOW}⚠ Query Response enthält möglicherweise nicht die erwarteten Begriffe${NC}"
fi

# Test 3: Query - Code
echo ""
echo -e "${BLUE}--- Test 3: Query - Code ---${NC}"
echo "Frage: Wie wird ein Benutzer erstellt?"

QUERY_RESPONSE=$(curl -s -X POST "$RAG_URL/query" \
    -H "Content-Type: application/json" \
    -d '{"question": "Wie wird ein neuer Benutzer im Demo-API-Service erstellt? Zeige den Code."}')

echo "Response:"
echo "$QUERY_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$QUERY_RESPONSE"

if echo "$QUERY_RESPONSE" | grep -qi "create_user\|post\|user"; then
    echo -e "${GREEN}✓ Query erfolgreich - Code-Referenz gefunden${NC}"
else
    echo -e "${YELLOW}⚠ Query Response enthält möglicherweise nicht die erwarteten Begriffe${NC}"
fi

# Test 4: Query - Lastenheft
echo ""
echo -e "${BLUE}--- Test 4: Query - Lastenheft ---${NC}"
echo "Frage: Was sind die funktionalen Anforderungen?"

QUERY_RESPONSE=$(curl -s -X POST "$RAG_URL/query" \
    -H "Content-Type: application/json" \
    -d '{"question": "Was sind die funktionalen Anforderungen im Lastenheft?"}')

echo "Response:"
echo "$QUERY_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$QUERY_RESPONSE"

if echo "$QUERY_RESPONSE" | grep -qi "LF-\|anforderung\|benutzer"; then
    echo -e "${GREEN}✓ Query erfolgreich - Anforderungen gefunden${NC}"
else
    echo -e "${YELLOW}⚠ Query Response enthält möglicherweise nicht die erwarteten Begriffe${NC}"
fi

# Zusammenfassung
echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Test abgeschlossen${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "Services:"
echo "  - Extractor: $EXTRACTOR_URL"
echo "  - RAG:       $RAG_URL"
echo "  - Qdrant:    http://localhost:6333/dashboard"
echo ""
echo "Aufräumen:"
echo "  docker compose -f docker-compose.test.yml down -v"
echo "  rm $TEST_PROJECT_FILE"
