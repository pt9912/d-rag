#!/usr/bin/env python3
"""
Projekt-Aggregator: Fasst Projektstruktur, Dokumentation und Source-Code
in eine einzige Markdown-Datei zusammen.

Verwendung:
    cd /pfad/zum/projekt
    python projekt_aggregator.py

Oder mit Optionen:
    python projekt_aggregator.py --output mein_projekt.md --description "Projektname: ..."

Das generierte Format ist optimiert für den Import in RAG-Systeme als Projekt-Wissensarchiv.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


# --- KONFIGURATION ---

LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "jsx",
    ".tsx": "tsx",
    ".java": "java",
    ".cpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".sql": "sql",
    ".md": "markdown",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".sass": "sass",
    ".less": "less",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "zsh",
    ".fish": "fish",
    ".ps1": "powershell",
    ".bat": "batch",
    ".cmd": "batch",
    ".dockerfile": "dockerfile",
    ".tf": "hcl",
    ".hcl": "hcl",
    ".vue": "vue",
    ".svelte": "svelte",
    ".graphql": "graphql",
    ".gql": "graphql",
    ".proto": "protobuf",
    ".txt": "text",
    ".csv": "csv",
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "ini",
    ".env": "dotenv",
    ".gitignore": "gitignore",
    ".dockerignore": "dockerignore",
}

DEFAULT_EXTENSIONS: list[str] = [
    ".md", ".py", ".js", ".ts", ".jsx", ".tsx",
    ".html", ".css", ".scss",
    ".java", ".cpp", ".c", ".h", ".cs", ".go", ".rs",
    ".json", ".yaml", ".yml", ".toml", ".xml",
    ".sql", ".sh", ".dockerfile",
    ".txt", ".env", ".gitignore",
]

DEFAULT_IGNORE_FOLDERS: list[str] = [
    ".git", "__pycache__", "node_modules", "venv", ".venv",
    ".idea", ".vscode", "build", "dist", "bin", "obj",
    ".pytest_cache", ".mypy_cache", "coverage", ".tox",
    ".eggs", ".cache", ".gradle", ".rasa", ".keras",
    ".config", ".grok", ".claude", "*.egg-info", "tmp*",
    "target", "out", ".next", ".nuxt",
]

DEFAULT_IGNORE_FILES: list[str] = [
    ".DS_Store", "Thumbs.db", "*.pyc", "*.pyo", "*.pyd",
    "*.so", "*.dll", "*.dylib", "*.class", "*.o", "*.a",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "poetry.lock", "Pipfile.lock", "composer.lock",
]

BEISPIEL_BESCHREIBUNG: str = """# PROJEKTBESCHREIBUNG
Projektname: [Projektname hier eintragen]
Ziel: [1-2 Sätze zum Hauptziel]

Domäne: [Fachgebiet, z.B. E-Commerce, Fintech, Healthcare]
Technologie-Stack: [Sprachen, Frameworks, Datenbanken]
Architektur-Pattern: [z.B. Clean Architecture, Microservices, MVC]

Problemstellung:
[2-3 Sätze: Was war die Ausgangssituation? Welches Problem wurde gelöst?]

Wichtige Entscheidungen:
- [Architekturentscheidung 1 mit Begründung]
- [Architekturentscheidung 2 mit Begründung]

Schlüsselkomponenten:
- [Komponente 1]: [Was sie tut]
- [Komponente 2]: [Was sie tut]

Schlagworte: [kommaseparierte Liste für Ähnlichkeitssuche]
"""

# Dateien, die für die Projektbeschreibung relevant sind (Priorität)
CONTEXT_FILES: list[str] = [
    "README.md", "README", "readme.md",
    "ARCHITECTURE.md", "architecture.md",
    "DESIGN.md", "design.md",
    "PROJECT.md", "project.md",
    "OVERVIEW.md", "overview.md",
    "pyproject.toml", "package.json", "Cargo.toml", "pom.xml", "build.gradle",
    "requirements.txt", "setup.py", "setup.cfg",
    "docker-compose.yml", "docker-compose.yaml", "Dockerfile",
    ".env.example", "config.yaml", "config.json",
]

# Ordner, die für Dokumentation durchsucht werden
DOCS_FOLDERS: list[str] = [
    "docs", "doc", "documentation",
    "design", "architecture",
    "spec", "specs", "specification",
]

KI_PROMPT_TEMPLATE: str = '''Du bist ein Software-Architekt, der Projektdokumentationen für ein Wissensarchiv aufbereitet.

Analysiere die folgenden Projektinformationen und erstelle eine strukturierte Projektbeschreibung.

## Gesammelte Projektinformationen

{context}

## Aufgabe

Erstelle aus den obigen Informationen eine prägnante Projektbeschreibung im folgenden Format:

```
# PROJEKTBESCHREIBUNG
Projektname: [Name des Projekts]
Ziel: [1-2 Sätze zum Hauptziel]

Domäne: [Fachgebiet, z.B. E-Commerce, Fintech, Healthcare, DevOps]
Technologie-Stack: [Sprachen, Frameworks, Datenbanken - aus den Dateien erkannt]
Architektur-Pattern: [z.B. Clean Architecture, Microservices, MVC, Monolith]

Problemstellung:
[2-3 Sätze zur Ausgangssituation und dem gelösten Problem]

Wichtige Entscheidungen:
- [Architekturentscheidung 1 mit Begründung]
- [Architekturentscheidung 2 mit Begründung]

Schlüsselkomponenten:
- [Komponente 1]: [Was sie tut]
- [Komponente 2]: [Was sie tut]

Schlagworte: [kommaseparierte Liste für Ähnlichkeitssuche]
```

Wichtig:
- Extrahiere konkrete Technologien aus den Konfigurationsdateien (package.json, pyproject.toml, etc.)
- Erkenne Architektur-Patterns aus der Verzeichnisstruktur und Dokumentation
- Verwende präzise, suchbare Begriffe
- Halte die Beschreibung kompakt aber informativ
'''


@dataclass
class AggregatorConfig:
    """Konfiguration für den Projekt-Aggregator."""

    output_filename: str = "projekt_komplett.md"
    projekt_beschreibung: str = BEISPIEL_BESCHREIBUNG
    extensions: list[str] = field(default_factory=lambda: DEFAULT_EXTENSIONS.copy())
    ignore_folders: list[str] = field(default_factory=lambda: DEFAULT_IGNORE_FOLDERS.copy())
    ignore_files: list[str] = field(default_factory=lambda: DEFAULT_IGNORE_FILES.copy())
    root_path: str = "."
    max_file_size_kb: int = 1024  # 1MB default


def get_language(extension: str) -> str:
    """Ermittelt die Sprache für Code-Fences basierend auf der Dateiendung."""
    return LANGUAGE_MAP.get(extension.lower(), "text")


def should_ignore(name: str, ignore_patterns: list[str]) -> bool:
    """Prüft, ob eine Datei oder ein Ordner ignoriert werden soll."""
    for pattern in ignore_patterns:
        if pattern.startswith("*"):
            if name.endswith(pattern[1:]):
                return True
        elif pattern.endswith("*"):
            if name.startswith(pattern[:-1]):
                return True
        elif name == pattern:
            return True
    return False


def generate_tree(startpath: str, config: AggregatorConfig) -> str:
    """Generiert einen ASCII-Verzeichnisbaum."""
    tree_lines: list[str] = ["# VERZEICHNISSTRUKTUR", "```text", "."]

    startpath = os.path.abspath(startpath)

    for root, dirs, files in os.walk(startpath):
        # Filter ignorierte Ordner
        dirs[:] = [d for d in sorted(dirs)
                   if d not in config.ignore_folders
                   and not should_ignore(d, config.ignore_folders)]

        level = root.replace(startpath, "").count(os.sep)
        indent = "│   " * level

        # Ordnernamen anzeigen (nicht für Root)
        if root != startpath:
            dirname = os.path.basename(root)
            tree_lines.append(f"{indent[:-4]}├── {dirname}/")

        # Dateien filtern und anzeigen
        visible_files = []
        for f in sorted(files):
            if f == config.output_filename:
                continue
            if f == os.path.basename(__file__):
                continue
            if should_ignore(f, config.ignore_files):
                continue
            ext = os.path.splitext(f)[1].lower()
            if ext in config.extensions or f in config.extensions:
                visible_files.append(f)

        for f in visible_files:
            if root == startpath:
                tree_lines.append(f"├── {f}")
            else:
                tree_lines.append(f"{indent}├── {f}")

    tree_lines.append("```")
    tree_lines.append("")
    return "\n".join(tree_lines)


def collect_files(startpath: str, config: AggregatorConfig) -> list[Path]:
    """Sammelt alle zu verarbeitenden Dateien."""
    startpath = os.path.abspath(startpath)
    collected: list[Path] = []

    for root, dirs, files in os.walk(startpath):
        # Filter ignorierte Ordner
        dirs[:] = [d for d in dirs
                   if d not in config.ignore_folders
                   and not should_ignore(d, config.ignore_folders)]

        for filename in files:
            # Selbst und Output überspringen
            if filename == config.output_filename:
                continue
            if filename == os.path.basename(__file__):
                continue
            if should_ignore(filename, config.ignore_files):
                continue

            ext = os.path.splitext(filename)[1].lower()
            if ext in config.extensions or filename in config.extensions:
                collected.append(Path(root) / filename)

    return sorted(collected)


def read_file_safely(filepath: Path, max_size_kb: int) -> tuple[str | None, str | None]:
    """
    Liest eine Datei sicher ein.
    Gibt (content, error) zurück.
    """
    try:
        size_kb = filepath.stat().st_size / 1024
        if size_kb > max_size_kb:
            return None, f"Datei zu groß ({size_kb:.1f} KB > {max_size_kb} KB)"

        # Versuche UTF-8
        try:
            content = filepath.read_text(encoding="utf-8")
            return content, None
        except UnicodeDecodeError:
            # Fallback auf latin-1
            try:
                content = filepath.read_text(encoding="latin-1")
                return content, None
            except Exception as e:
                return None, f"Encoding-Fehler: {e}"

    except PermissionError:
        return None, "Keine Leseberechtigung"
    except Exception as e:
        return None, str(e)


def merge_files(config: AggregatorConfig, quiet: bool = False) -> dict[str, int]:
    """
    Führt alle Dateien zusammen und schreibt die Ausgabedatei.
    Gibt Statistiken zurück.

    Args:
        config: Aggregator-Konfiguration
        quiet: Keine Fortschrittsausgabe (automatisch bei stdout)
    """
    stats = {"files_processed": 0, "files_skipped": 0, "total_chars": 0}

    startpath = os.path.abspath(config.root_path)
    use_stdout = config.output_filename == "-"

    # Verzeichnisbaum generieren
    tree_content = generate_tree(startpath, config)

    # Dateien sammeln
    files = collect_files(startpath, config)

    # Log-Funktion (nur wenn nicht stdout und nicht quiet)
    def log(msg: str) -> None:
        if not use_stdout and not quiet:
            print(msg, file=sys.stderr)

    # Output-Stream bestimmen
    if use_stdout:
        outfile = sys.stdout
        _close_file = False
    else:
        output_path = Path(startpath) / config.output_filename
        outfile = open(output_path, "w", encoding="utf-8")
        _close_file = True

    try:
        # 1. Verzeichnisstruktur
        outfile.write(tree_content)

        # 2. Projektbeschreibung
        outfile.write("---\n")
        outfile.write(config.projekt_beschreibung.strip())
        outfile.write("\n\n---\n")

        # 3. Dateiinhalte
        outfile.write("# DATEIINHALTE\n")

        for filepath in files:
            relative_path = filepath.relative_to(startpath)
            content, error = read_file_safely(filepath, config.max_file_size_kb)

            if error:
                log(f"  Übersprungen: {relative_path} ({error})")
                stats["files_skipped"] += 1
                continue

            ext = filepath.suffix.lower()
            lang = get_language(ext)

            outfile.write(f"\n---\n")
            outfile.write(f"## DATEI: ./{relative_path}\n")
            outfile.write(f"```{lang}\n")
            outfile.write(content)
            if content and not content.endswith("\n"):
                outfile.write("\n")
            outfile.write("```\n")

            stats["files_processed"] += 1
            stats["total_chars"] += len(content) if content else 0
            log(f"  Hinzugefügt: ./{relative_path}")

    finally:
        if _close_file:
            outfile.close()

    return stats


def parse_args() -> argparse.Namespace:
    """Parst Kommandozeilenargumente."""
    parser = argparse.ArgumentParser(
        description="Aggregiert Projektdateien in eine einzelne Markdown-Datei.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  python projekt_aggregator.py
  python projekt_aggregator.py --output mein_projekt.md
  python projekt_aggregator.py --extensions .py,.md,.yaml
  python projekt_aggregator.py --ignore node_modules,dist,.cache
        """,
    )

    parser.add_argument(
        "-o", "--output",
        default="projekt_komplett.md",
        help="Name der Ausgabedatei (default: projekt_komplett.md). Verwende '-' für stdout.",
    )

    parser.add_argument(
        "-d", "--description",
        help="Projektbeschreibung (oder @datei.txt zum Einlesen)",
    )

    parser.add_argument(
        "-e", "--extensions",
        help="Kommaseparierte Liste der Dateiendungen (z.B. .py,.md,.yaml)",
    )

    parser.add_argument(
        "-i", "--ignore",
        help="Zusätzliche zu ignorierende Ordner (kommasepariert)",
    )

    parser.add_argument(
        "-p", "--path",
        default=".",
        help="Wurzelverzeichnis des Projekts (default: aktuelles Verzeichnis)",
    )

    parser.add_argument(
        "--max-size",
        type=int,
        default=1024,
        help="Maximale Dateigröße in KB (default: 1024)",
    )

    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Keine Fortschrittsausgabe",
    )

    parser.add_argument(
        "--generate-prompt",
        action="store_true",
        help="Generiert einen KI-Prompt mit Projektkontext für die Projektbeschreibung (gibt nur den Prompt aus, keine Aggregation)",
    )

    parser.add_argument(
        "--prompt-max-chars",
        type=int,
        default=50000,
        help="Maximale Zeichenzahl für den generierten Prompt (default: 50000)",
    )

    return parser.parse_args()


def load_description(desc_arg: str | None) -> str:
    """Lädt die Projektbeschreibung aus Argument oder Datei."""
    if not desc_arg:
        return BEISPIEL_BESCHREIBUNG

    if desc_arg.startswith("@"):
        filepath = desc_arg[1:]
        try:
            return Path(filepath).read_text(encoding="utf-8")
        except Exception as e:
            print(f"Warnung: Konnte {filepath} nicht lesen: {e}")
            return BEISPIEL_BESCHREIBUNG

    return desc_arg


def collect_context_files(root_path: str, max_file_size_kb: int = 100) -> list[tuple[str, str]]:
    """
    Sammelt relevante Dateien für die Projektbeschreibung.
    Gibt Liste von (relativer_pfad, inhalt) zurück.
    """
    root = Path(root_path).resolve()
    collected: list[tuple[str, str]] = []
    max_bytes = max_file_size_kb * 1024

    # 1. Kontext-Dateien im Root-Verzeichnis
    for filename in CONTEXT_FILES:
        filepath = root / filename
        if filepath.exists() and filepath.is_file():
            try:
                if filepath.stat().st_size <= max_bytes:
                    content = filepath.read_text(encoding="utf-8", errors="replace")
                    collected.append((filename, content))
            except Exception:
                pass

    # 2. Dokumentations-Ordner durchsuchen
    for docs_folder in DOCS_FOLDERS:
        docs_path = root / docs_folder
        if docs_path.exists() and docs_path.is_dir():
            # Markdown-Dateien im docs-Ordner sammeln
            for md_file in sorted(docs_path.rglob("*.md")):
                if md_file.is_file():
                    try:
                        if md_file.stat().st_size <= max_bytes:
                            content = md_file.read_text(encoding="utf-8", errors="replace")
                            rel_path = md_file.relative_to(root)
                            collected.append((str(rel_path), content))
                    except Exception:
                        pass

    return collected


def generate_context_prompt(root_path: str, max_file_size_kb: int = 100, max_total_chars: int = 50000) -> str:
    """
    Generiert einen KI-Prompt mit gesammeltem Projektkontext.
    """
    root = Path(root_path).resolve()
    project_name = root.name

    # Verzeichnisstruktur generieren (für Kontext)
    config = AggregatorConfig(root_path=root_path)
    tree = generate_tree(str(root), config)

    # Kontext-Dateien sammeln
    context_files = collect_context_files(root_path, max_file_size_kb)

    # Kontext zusammenbauen
    context_parts: list[str] = []

    # Projektname aus Verzeichnis
    context_parts.append(f"### Projektverzeichnis: {project_name}\n")

    # Verzeichnisstruktur (gekürzt)
    tree_lines = tree.split("\n")
    if len(tree_lines) > 50:
        tree_preview = "\n".join(tree_lines[:50]) + "\n... (gekürzt)"
    else:
        tree_preview = tree
    context_parts.append(f"### Verzeichnisstruktur\n{tree_preview}\n")

    # Gesammelte Dateien
    total_chars = sum(len(p) for p in context_parts)
    for rel_path, content in context_files:
        file_section = f"### Datei: {rel_path}\n```\n{content}\n```\n"

        # Prüfen ob noch Platz ist
        if total_chars + len(file_section) > max_total_chars:
            # Datei kürzen
            remaining = max_total_chars - total_chars - 200
            if remaining > 500:
                truncated = content[:remaining] + "\n... (gekürzt)"
                file_section = f"### Datei: {rel_path}\n```\n{truncated}\n```\n"
                context_parts.append(file_section)
            break
        else:
            context_parts.append(file_section)
            total_chars += len(file_section)

    context = "\n".join(context_parts)
    return KI_PROMPT_TEMPLATE.format(context=context)


def main() -> None:
    """Hauptfunktion."""
    args = parse_args()

    # Modus: Prompt generieren
    if args.generate_prompt:
        prompt = generate_context_prompt(
            root_path=args.path,
            max_file_size_kb=100,  # Kleinere Dateien für Kontext
            max_total_chars=args.prompt_max_chars,
        )
        print(prompt)
        return

    # Konfiguration erstellen
    config = AggregatorConfig(
        output_filename=args.output,
        projekt_beschreibung=load_description(args.description),
        root_path=args.path,
        max_file_size_kb=args.max_size,
    )

    # Extensions überschreiben falls angegeben
    if args.extensions:
        exts = [e.strip() if e.strip().startswith(".") else f".{e.strip()}"
                for e in args.extensions.split(",")]
        config.extensions = exts

    # Zusätzliche Ignore-Ordner
    if args.ignore:
        config.ignore_folders.extend([f.strip() for f in args.ignore.split(",")])

    # Bei stdout automatisch quiet
    use_stdout = config.output_filename == "-"
    is_quiet = args.quiet or use_stdout

    # Ausführen
    if not is_quiet:
        print(f"Projekt-Aggregator", file=sys.stderr)
        print(f"==================", file=sys.stderr)
        print(f"Verzeichnis: {os.path.abspath(config.root_path)}", file=sys.stderr)
        print(f"Ausgabe:     {config.output_filename}", file=sys.stderr)
        print(f"Extensions:  {', '.join(config.extensions[:10])}{'...' if len(config.extensions) > 10 else ''}", file=sys.stderr)
        print(file=sys.stderr)
        print("Verarbeite Dateien...", file=sys.stderr)

    stats = merge_files(config, quiet=is_quiet)

    if not is_quiet:
        print(file=sys.stderr)
        print(f"Fertig!", file=sys.stderr)
        print(f"  Dateien verarbeitet: {stats['files_processed']}", file=sys.stderr)
        print(f"  Dateien übersprungen: {stats['files_skipped']}", file=sys.stderr)
        print(f"  Gesamtzeichen: {stats['total_chars']:,}", file=sys.stderr)
        print(f"  Ausgabe: {config.output_filename}", file=sys.stderr)


if __name__ == "__main__":
    main()
