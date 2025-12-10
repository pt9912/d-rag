"""Tests für den Aggregated Markdown Parser und Endpoint."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# Patch OUTPUT_DIR vor dem Import
with patch.dict("os.environ", {"EXTRACT_OUTPUT_DIR": tempfile.mkdtemp()}):
    from extractor.app.main import (
        AggregatedMarkdownParser,
        ParsedFile,
        ParsedProject,
        app,
        detect_doc_type,
        extract_project_name,
        slugify_project,
    )

client = TestClient(app)


# --- Test Data ---

SAMPLE_AGGREGATED_MD = """# VERZEICHNISSTRUKTUR
```text
.
├── docs/
│   └── lastenheft.md
├── src/
│   └── main.py
└── README.md
```

---
# PROJEKTBESCHREIBUNG
Projektname: Test-Projekt
Ziel: Ein Beispielprojekt für Tests

Domäne: Testing
Technologie-Stack: Python, FastAPI
Architektur-Pattern: Clean Architecture

Schlagworte: test, beispiel, demo

---
# DATEIINHALTE

---
## DATEI: ./docs/lastenheft.md
```markdown
# Lastenheft

## Anforderungen
- Anforderung 1
- Anforderung 2
```

---
## DATEI: ./src/main.py
```python
def main():
    print("Hello World")

if __name__ == "__main__":
    main()
```

---
## DATEI: ./README.md
```markdown
# README

Dies ist ein Test-Projekt.
```
"""

MINIMAL_AGGREGATED_MD = """# DATEIINHALTE

---
## DATEI: ./test.py
```python
x = 1
```
"""


# --- Unit Tests für Helper-Funktionen ---

class TestDetectDocType:
    """Tests für die Dokument-Typ-Erkennung."""

    def test_python_file_is_source_code(self):
        assert detect_doc_type("./src/main.py", "print('hello')") == "source_code"

    def test_javascript_file_is_source_code(self):
        assert detect_doc_type("./app.js", "const x = 1;") == "source_code"

    def test_lastenheft_by_filename(self):
        assert detect_doc_type("./docs/lastenheft.md", "# Inhalt") == "lastenheft"

    def test_lastenheft_by_content(self):
        assert detect_doc_type("./docs/spec.md", "# Anforderungen\nStakeholder") == "lastenheft"

    def test_pflichtenheft_by_filename(self):
        assert detect_doc_type("./pflichtenheft.md", "# Inhalt") == "pflichtenheft"

    def test_architektur_by_filename(self):
        assert detect_doc_type("./ARCHITECTURE.md", "# System") == "architektur"

    def test_design_by_filename(self):
        assert detect_doc_type("./design/konzept.md", "# Konzept") == "design"

    def test_generic_markdown_is_dokument(self):
        assert detect_doc_type("./notes.md", "Einige Notizen") == "dokument"

    def test_unknown_extension(self):
        assert detect_doc_type("./data.xyz", "binary stuff") == "sonstiges"


class TestExtractProjectName:
    """Tests für die Projektnamen-Extraktion."""

    def test_extracts_projektname(self):
        desc = "Projektname: Mein-Projekt\nZiel: Testen"
        assert extract_project_name(desc) == "Mein-Projekt"

    def test_extracts_projekt(self):
        desc = "Projekt: Anderes Projekt\nBeschreibung: ..."
        assert extract_project_name(desc) == "Anderes Projekt"

    def test_extracts_name(self):
        desc = "Name: Einfacher Name\n"
        assert extract_project_name(desc) == "Einfacher Name"

    def test_case_insensitive(self):
        desc = "PROJEKTNAME: GROSSBUCHSTABEN\n"
        assert extract_project_name(desc) == "GROSSBUCHSTABEN"

    def test_returns_unbekannt_if_not_found(self):
        desc = "Keine Projekt-Info hier"
        assert extract_project_name(desc) == "unbekannt"

    def test_strips_markdown_formatting(self):
        desc = "Projektname: **Bold** _Italic_\n"
        assert extract_project_name(desc) == "Bold Italic"


class TestSlugifyProject:
    """Tests für die Projekt-ID-Generierung."""

    def test_lowercase(self):
        assert slugify_project("MeinProjekt") == "meinprojekt"

    def test_replaces_spaces(self):
        assert slugify_project("Mein Projekt") == "mein-projekt"

    def test_replaces_special_chars(self):
        assert slugify_project("Projekt (v2.0)") == "projekt-v2-0"

    def test_removes_multiple_dashes(self):
        assert slugify_project("Test---Projekt") == "test-projekt"

    def test_empty_string(self):
        assert slugify_project("") == "projekt"

    def test_only_special_chars(self):
        assert slugify_project("@#$%") == "projekt"


# --- Tests für den Parser ---

class TestAggregatedMarkdownParser:
    """Tests für den Markdown-Parser."""

    def test_parses_full_document(self):
        parser = AggregatedMarkdownParser()
        project = parser.parse(SAMPLE_AGGREGATED_MD)

        assert project.project_name == "Test-Projekt"
        assert project.project_id == "test-projekt"
        assert len(project.files) == 3

    def test_extracts_verzeichnisstruktur(self):
        parser = AggregatedMarkdownParser()
        project = parser.parse(SAMPLE_AGGREGATED_MD)

        assert "docs/" in project.verzeichnisstruktur
        assert "src/" in project.verzeichnisstruktur
        assert "main.py" in project.verzeichnisstruktur

    def test_extracts_projektbeschreibung(self):
        parser = AggregatedMarkdownParser()
        project = parser.parse(SAMPLE_AGGREGATED_MD)

        assert "Test-Projekt" in project.beschreibung
        assert "Clean Architecture" in project.beschreibung

    def test_extracts_files_with_metadata(self):
        parser = AggregatedMarkdownParser()
        project = parser.parse(SAMPLE_AGGREGATED_MD)

        # Finde die Python-Datei
        py_file = next(f for f in project.files if f.source == "./src/main.py")
        assert py_file.language == "python"
        assert py_file.doc_type == "source_code"
        assert py_file.directory == "src"
        assert py_file.extension == ".py"
        assert "print" in py_file.content

    def test_extracts_lastenheft_doc_type(self):
        parser = AggregatedMarkdownParser()
        project = parser.parse(SAMPLE_AGGREGATED_MD)

        lastenheft = next(f for f in project.files if "lastenheft" in f.source)
        assert lastenheft.doc_type == "lastenheft"

    def test_minimal_document(self):
        parser = AggregatedMarkdownParser()
        project = parser.parse(MINIMAL_AGGREGATED_MD)

        assert project.project_name == "unbekannt"
        assert len(project.files) == 1
        assert project.files[0].source == "./test.py"

    def test_empty_beschreibung_handled(self):
        md = """# DATEIINHALTE
---
## DATEI: ./a.py
```python
pass
```
"""
        parser = AggregatedMarkdownParser()
        project = parser.parse(md)

        assert project.beschreibung == ""
        assert len(project.files) == 1


# --- Integration Tests für den Endpoint ---

class TestExtractAggregatedMdEndpoint:
    """Tests für den /extract/aggregated-md Endpoint."""

    def test_successful_extraction(self):
        response = client.post(
            "/extract/aggregated-md",
            files={"file": ("test.md", SAMPLE_AGGREGATED_MD, "text/markdown")},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["project_name"] == "Test-Projekt"
        assert data["project_id"] == "test-projekt"
        assert data["files_extracted"] == 3
        assert len(data["chunks"]) == 3
        assert len(data["meta_chunks"]) == 2

    def test_returns_chunk_details(self):
        response = client.post(
            "/extract/aggregated-md",
            files={"file": ("test.md", SAMPLE_AGGREGATED_MD, "text/markdown")},
        )

        data = response.json()
        chunks = data["chunks"]

        # Finde Python-Chunk
        py_chunk = next(c for c in chunks if c["source"] == "./src/main.py")
        assert py_chunk["doc_type"] == "source_code"
        assert py_chunk["language"] == "python"
        assert py_chunk["extension"] == ".py"
        assert py_chunk["chars"] > 0

    def test_project_name_override(self):
        response = client.post(
            "/extract/aggregated-md",
            files={"file": ("test.md", SAMPLE_AGGREGATED_MD, "text/markdown")},
            data={"project_name_override": "Custom Project Name"},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["project_name"] == "Custom Project Name"
        assert data["project_id"] == "custom-project-name"

    def test_roles_are_returned(self):
        response = client.post(
            "/extract/aggregated-md",
            files={"file": ("test.md", SAMPLE_AGGREGATED_MD, "text/markdown")},
            data={"roles": "dev, admin"},
        )

        data = response.json()
        assert data["roles"] == ["dev", "admin"]

    def test_empty_file_returns_400(self):
        response = client.post(
            "/extract/aggregated-md",
            files={"file": ("empty.md", "", "text/markdown")},
        )

        assert response.status_code == 400
        assert "leer" in response.json()["detail"]

    def test_no_files_returns_422(self):
        md_without_files = """# PROJEKTBESCHREIBUNG
Projektname: Leer
"""
        response = client.post(
            "/extract/aggregated-md",
            files={"file": ("nofiles.md", md_without_files, "text/markdown")},
        )

        assert response.status_code == 422
        assert "DATEI-Sektionen" in response.json()["detail"]

    def test_minimal_document_works(self):
        response = client.post(
            "/extract/aggregated-md",
            files={"file": ("minimal.md", MINIMAL_AGGREGATED_MD, "text/markdown")},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["project_name"] == "unbekannt"
        assert data["files_extracted"] == 1


class TestHealthEndpoint:
    """Tests für den Health-Endpoint."""

    def test_health_returns_ok(self):
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestExtractZipEndpoint:
    """Tests für den ZIP-Endpoint mit Markdown-Unterstützung."""

    def test_zip_with_markdown_files(self):
        """Test dass ZIP mit Markdown-Dateien verarbeitet wird."""
        import zipfile
        from io import BytesIO

        # ZIP mit Markdown erstellen
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("docs/readme.md", "# Test README\n\nThis is a test.")
            zf.writestr("docs/architecture.md", "# Architecture\n\nSystem design.")
        zip_buffer.seek(0)

        response = client.post(
            "/extract/zip",
            files={"file": ("test.zip", zip_buffer, "application/zip")},
            data={"auto_update": "false"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "files" in data
        assert len(data["files"]) == 2

    def test_zip_with_mixed_files(self):
        """Test dass ZIP mit gemischten Dateitypen (MD + TXT) verarbeitet wird."""
        import zipfile
        from io import BytesIO

        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("readme.md", "# Markdown file")
            zf.writestr("notes.txt", "Plain text notes")
        zip_buffer.seek(0)

        response = client.post(
            "/extract/zip",
            files={"file": ("mixed.zip", zip_buffer, "application/zip")},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["files"]) == 2

    def test_zip_rejects_unsupported_files_only(self):
        """Test dass ZIP ohne unterstützte Dateien abgelehnt wird."""
        import zipfile
        from io import BytesIO

        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("image.png", b"\x89PNG\r\n\x1a\n")  # PNG header
            zf.writestr("data.json", '{"key": "value"}')  # JSON nicht unterstützt
        zip_buffer.seek(0)

        response = client.post(
            "/extract/zip",
            files={"file": ("unsupported.zip", zip_buffer, "application/zip")},
        )

        assert response.status_code == 422
        assert "unterstützten Dateien" in response.json()["detail"]

    def test_zip_handles_utf8_content(self):
        """Test dass UTF-8 Inhalt korrekt verarbeitet wird."""
        import zipfile
        from io import BytesIO

        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("german.md", "# Übersicht\n\nÄnderungen und Ergänzungen.")
        zip_buffer.seek(0)

        response = client.post(
            "/extract/zip",
            files={"file": ("utf8.zip", zip_buffer, "application/zip")},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["files"]) == 1
        assert int(data["files"][0]["chars"]) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
