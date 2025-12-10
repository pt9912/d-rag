# Sprint-Task: Generator-Tool `projekt_aggregator.py`

## Ziel

Ein standalone Python-Skript bereitstellen, das Projektstruktur, Dokumentation und Source-Code in eine einzige Markdown-Datei aggregiert. Das Format ist optimiert für den Import in das RAG-System als Projekt-Wissensarchiv.

## User Story

> Als Entwickler möchte ich ein abgeschlossenes Projekt (Lastenheft, Pflichtenheft, Architektur, Code) in eine einzelne Datei exportieren, damit es im RAG-System durchsuchbar wird und bei ähnlichen Anforderungen als Referenz dient.

## Anforderungen

### Funktional

| ID | Anforderung | Priorität |
|----|-------------|-----------|
| F1 | Rekursives Durchlaufen eines Projektverzeichnisses | Must |
| F2 | Generierung eines ASCII-Verzeichnisbaums | Must |
| F3 | Einbettung einer konfigurierbaren Projektbeschreibung | Must |
| F4 | Extraktion aller Dateiinhalte mit Code-Fences | Must |
| F5 | Filterung nach Dateiendungen (whitelist) | Must |
| F6 | Ausschluss von Verzeichnissen (blacklist) | Must |
| F7 | Selbst-Überspringung (Skript + Output) | Must |
| F8 | CLI-Argumente für Konfiguration | Should |
| F9 | Fortschrittsanzeige bei großen Projekten | Could |

### Nicht-funktional

| ID | Anforderung |
|----|-------------|
| NF1 | Keine externen Dependencies (nur Python stdlib) |
| NF2 | Python 3.9+ Kompatibilität |
| NF3 | UTF-8 Encoding für alle Dateien |
| NF4 | Fehlertoleranz bei nicht-lesbaren Dateien (skip + log) |

## Technisches Design

### Ausgabe-Format

```markdown
# VERZEICHNISSTRUKTUR
```text
.
├── docs/
│   ├── lastenheft.md
│   └── architektur.md
├── src/
│   └── main.py
└── README.md
```

---
# PROJEKTBESCHREIBUNG
Projektname: <name>
Ziel: <beschreibung>

Domäne: <fachgebiet>
Technologie-Stack: <sprachen, frameworks, datenbanken>
Architektur-Pattern: <z.B. Clean Architecture, Microservices, MVC>

Problemstellung:
<Was war die Ausgangssituation? Welches Problem wurde gelöst?>

Wichtige Entscheidungen:
- <Architekturentscheidung 1>
- <Architekturentscheidung 2>

Schlüsselkomponenten:
- <komponente>: <kurze beschreibung>

---
# DATEIINHALTE

---
## DATEI: ./docs/lastenheft.md
```markdown
<inhalt>
```

---
## DATEI: ./src/main.py
```python
<inhalt>
```
```

### Konfiguration

```python
@dataclass
class AggregatorConfig:
    output_filename: str = "projekt_komplett.md"
    projekt_beschreibung: str = ""
    extensions: list[str] = field(default_factory=lambda: [
        '.md', '.py', '.js', '.ts', '.html', '.css',
        '.java', '.cpp', '.h', '.json', '.yaml', '.yml',
        '.sql', '.txt', '.sh', '.dockerfile'
    ])
    ignore_folders: list[str] = field(default_factory=lambda: [
        '.git', '__pycache__', 'node_modules', 'venv', '.venv',
        '.idea', '.vscode', 'build', 'dist', 'bin', 'obj',
        '.pytest_cache', '.mypy_cache', 'coverage', '.tox'
    ])
    ignore_files: list[str] = field(default_factory=lambda: [
        '.DS_Store', 'Thumbs.db', '*.pyc', '*.pyo'
    ])
```

### CLI-Interface (optional, Phase 2)

```bash
# Basis-Verwendung
python projekt_aggregator.py

# Mit Optionen
python projekt_aggregator.py \
  --output projektarchiv.md \
  --description "Projektname: MeinProjekt\nZiel: ..." \
  --extensions .py,.md,.yaml \
  --ignore node_modules,dist
```

### Modul-Struktur

```
tools/
└── projekt_aggregator.py
    ├── AggregatorConfig (dataclass)
    ├── generate_tree(startpath, config) -> str
    ├── get_language(extension) -> str
    ├── collect_files(startpath, config) -> list[Path]
    ├── merge_files(config) -> None
    └── main() -> None
```

### Extension-zu-Sprache Mapping

```python
LANGUAGE_MAP = {
    '.py': 'python',
    '.js': 'javascript',
    '.ts': 'typescript',
    '.java': 'java',
    '.cpp': 'cpp',
    '.c': 'c',
    '.h': 'c',
    '.json': 'json',
    '.yaml': 'yaml',
    '.yml': 'yaml',
    '.sql': 'sql',
    '.md': 'markdown',
    '.html': 'html',
    '.css': 'css',
    '.sh': 'bash',
    '.dockerfile': 'dockerfile',
    '.xml': 'xml',
    '.toml': 'toml',
}
```

### KI-Prompt für Projektbeschreibung

Der folgende Prompt hilft Benutzern, eine optimale Projektbeschreibung für das RAG-System zu erstellen:

```
Du bist ein Software-Architekt, der Projektdokumentationen für ein Wissensarchiv aufbereitet.

Ich gebe dir Informationen zu einem abgeschlossenen Software-Projekt. Erstelle daraus eine strukturierte Projektbeschreibung im folgenden Format:

# PROJEKTBESCHREIBUNG
Projektname: [Name des Projekts]
Ziel: [1-2 Sätze zum Hauptziel]

Domäne: [Fachgebiet, z.B. E-Commerce, Fintech, Healthcare, IoT]
Technologie-Stack: [Programmiersprachen, Frameworks, Datenbanken]
Architektur-Pattern: [z.B. Clean Architecture, Microservices, MVC, Event-Driven]

Problemstellung:
[2-3 Sätze: Was war die Ausgangssituation? Welches Problem wurde gelöst?]

Wichtige Entscheidungen:
- [Architekturentscheidung 1 mit kurzer Begründung]
- [Architekturentscheidung 2 mit kurzer Begründung]
- [...]

Schlüsselkomponenten:
- [Komponente 1]: [Was sie tut]
- [Komponente 2]: [Was sie tut]
- [...]

Schlagworte: [kommaseparierte Liste für Ähnlichkeitssuche]

---

Achte auf:
1. Präzise, suchbare Begriffe (keine vagen Formulierungen)
2. Technische Tiefe für Entwickler
3. Domänen-Kontext für fachliche Ähnlichkeitssuche
4. Architektur-Pattern explizit benennen
5. Schlagworte, die bei ähnlichen Projekten auch vorkommen würden

Hier sind die Projektinformationen:
[HIER PROJEKTINFOS EINFÜGEN]
```

**Beispiel-Ausgabe:**

```markdown
# PROJEKTBESCHREIBUNG
Projektname: Kundenportal-v2
Ziel: Self-Service-Portal für Endkunden mit Vertragsverwaltung und Rechnungseinsicht

Domäne: Versicherung, B2C-Portal
Technologie-Stack: Python 3.11, FastAPI, PostgreSQL, Redis, Vue.js 3, Docker
Architektur-Pattern: Clean Architecture, CQRS, Event-Driven

Problemstellung:
Das bestehende Portal war monolithisch und schwer wartbar. Kunden konnten keine
Verträge selbst verwalten, was zu hohem Support-Aufwand führte. Ziel war eine
moderne, skalierbare Lösung mit Self-Service-Funktionen.

Wichtige Entscheidungen:
- Clean Architecture für Testbarkeit und Austauschbarkeit der Infrastruktur
- CQRS für optimierte Lese-/Schreibpfade bei hoher Last
- Event-Sourcing für Audit-Trail und Compliance-Anforderungen
- Redis für Session-Management und Caching

Schlüsselkomponenten:
- api-gateway: Request-Routing, Auth, Rate-Limiting
- contract-service: Vertragsverwaltung, CRUD-Operationen
- billing-service: Rechnungen, Zahlungsstatus
- notification-service: E-Mail/Push via Event-Consumer
- frontend-spa: Vue.js SPA mit Composition API

Schlagworte: Self-Service, Kundenportal, Versicherung, Clean Architecture,
CQRS, Event-Sourcing, FastAPI, Vue.js, Vertragsverwaltung, B2C
```

## Abnahmekriterien

- [ ] Skript läuft ohne externe Dependencies
- [ ] Generierte Datei folgt dem dokumentierten Format
- [ ] Verzeichnisbaum ist korrekt formatiert (Unicode Box-Drawing)
- [ ] Code-Fences haben korrekte Sprach-Tags
- [ ] Nicht-lesbare Dateien werden übersprungen mit Warnung
- [ ] Skript überspringt sich selbst und die Ausgabedatei
- [ ] Ausgabe ist valides Markdown

## Testfälle

| ID | Testfall | Erwartetes Ergebnis |
|----|----------|---------------------|
| T1 | Leeres Verzeichnis | Nur Struktur + Beschreibung, keine Dateiinhalte |
| T2 | Verschachtelte Ordner | Korrekter Baum mit Einrückung |
| T3 | Binärdatei im Projekt | Wird übersprungen, Warnung ausgegeben |
| T4 | Datei mit UTF-8 Sonderzeichen | Korrekt eingebettet |
| T5 | Sehr große Datei (>1MB) | Wird verarbeitet (ggf. mit Warnung) |
| T6 | Symlinks | Werden nicht verfolgt (Endlosschleifen vermeiden) |

## Aufwand

| Komponente | Aufwand |
|------------|---------|
| Basis-Implementierung | S |
| CLI-Interface | S |
| Tests | S |
| Dokumentation | XS |
| **Gesamt** | **M** |

## Abhängigkeiten

- Keine externen Abhängigkeiten
- Ausgabedatei wird vom Extractor-Service verarbeitet (siehe Sprint-Task 2)

## Offene Fragen

1. Soll eine maximale Dateigröße konfigurierbar sein?
2. Sollen Binary-Dateien (Images) als Platzhalter `[Binary: image.png, 45KB]` aufgelistet werden?
3. Soll das Skript auch als Package installierbar sein (`pip install`)?
