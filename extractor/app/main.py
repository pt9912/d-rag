from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, Optional, Sequence
from zipfile import BadZipFile, ZipFile

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from langchain_text_splitters import MarkdownHeaderTextSplitter
from pypdf import PdfReader

OUTPUT_DIR = Path(os.getenv("EXTRACT_OUTPUT_DIR", "/data"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

RAG_SERVICE_URL = os.getenv("RAG_SERVICE_URL")

app = FastAPI(title="Document Extractor", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def slugify(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip().lower())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned or "document"


def ensure_suffix(filename: str) -> str:
    path = Path(filename)
    return f"{path.stem}.md"


@app.get("/healthz")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/extract/pdf")
async def extract_pdf(
    file: UploadFile = File(...),
    target_name: Optional[str] = Form(None),
    auto_update: bool = Form(False),
    roles: Optional[str] = Form(None),
) -> dict[str, str]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Dateiname fehlt.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Datei ist leer.")

    name_source = target_name or file.filename
    return process_pdf_bytes(content, name_source, auto_update, parse_roles(roles))


SUPPORTED_ZIP_EXTENSIONS = {".pdf", ".md", ".markdown", ".txt"}


@app.post("/extract/zip")
async def extract_zip(
    file: UploadFile = File(...),
    auto_update: bool = Form(False),
    roles: Optional[str] = Form(None),
) -> dict[str, Sequence[dict[str, str]]]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Dateiname fehlt.")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="ZIP-Datei ist leer.")

    try:
        with ZipFile(BytesIO(data)) as archive:
            # Unterstützte Dateitypen finden
            members = [
                item for item in archive.namelist()
                if any(item.lower().endswith(ext) for ext in SUPPORTED_ZIP_EXTENSIONS)
            ]
            if not members:
                raise HTTPException(
                    status_code=422,
                    detail=f"ZIP enthält keine unterstützten Dateien ({', '.join(SUPPORTED_ZIP_EXTENSIONS)})."
                )

            results = []
            parsed_roles = parse_roles(roles)
            for member in members:
                file_bytes = archive.read(member)
                if not file_bytes:
                    continue

                member_lower = member.lower()
                if member_lower.endswith(".pdf"):
                    results.append(process_pdf_bytes(file_bytes, member, auto_update, parsed_roles))
                else:
                    # Markdown/Text direkt verarbeiten
                    results.append(process_text_bytes(file_bytes, member, auto_update, parsed_roles))
    except BadZipFile as exc:
        raise HTTPException(status_code=422, detail=f"Ungültige ZIP-Datei: {exc}") from exc

    if not results:
        raise HTTPException(status_code=422, detail="Es konnten keine Dateien verarbeitet werden.")

    return {"files": results}


def extract_text_from_pdf(content: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(content))
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n\n".join(pages).strip()
    except Exception as exc:  # pragma: no cover - pypdf Fehler schwer zu simulieren
        raise HTTPException(status_code=422, detail=f"PDF konnte nicht gelesen werden: {exc}") from exc

    if not text:
        raise HTTPException(status_code=422, detail="Keine extrahierbaren Texte gefunden.")
    return text


def process_pdf_bytes(
    content: bytes,
    original_name: str,
    auto_update: bool,
    roles: Optional[list[str]],
) -> dict[str, str]:
    text = extract_text_from_pdf(content)

    filename = ensure_suffix(slugify(original_name))
    output_path = OUTPUT_DIR / filename
    output_path.write_text(text, encoding="utf-8")

    response: dict[str, str] = {
        "output_path": str(output_path),
        "relative_path": f"data/{filename}",
        "roles": ",".join(roles) if roles else "",
        "chars": str(len(text)),
    }

    if auto_update and RAG_SERVICE_URL:
        try:
            ingest_resp = httpx.post(
                f"{RAG_SERVICE_URL.rstrip('/')}/update",
                json={"path": response["relative_path"], "roles": roles},
                timeout=30,
            )
            ingest_resp.raise_for_status()
            response["rag_update"] = "ok"
        except Exception as exc:  # pragma: no cover
            response["rag_update"] = f"failed: {exc}"

    return response


def process_text_bytes(
    content: bytes,
    original_name: str,
    auto_update: bool,
    roles: Optional[list[str]],
) -> dict[str, str]:
    """Verarbeitet Markdown/Text-Dateien aus ZIP."""
    # Text dekodieren (UTF-8 mit Fallback auf Latin-1)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("latin-1", errors="replace")

    if not text.strip():
        return {"error": f"Datei {original_name} ist leer.", "original_name": original_name}

    filename = ensure_suffix(slugify(original_name))
    output_path = OUTPUT_DIR / filename
    output_path.write_text(text, encoding="utf-8")

    response: dict[str, str] = {
        "output_path": str(output_path),
        "relative_path": f"data/{filename}",
        "roles": ",".join(roles) if roles else "",
        "chars": str(len(text)),
        "original_name": original_name,
    }

    if auto_update and RAG_SERVICE_URL:
        try:
            ingest_resp = httpx.post(
                f"{RAG_SERVICE_URL.rstrip('/')}/update",
                json={"path": response["relative_path"], "roles": roles},
                timeout=30,
            )
            ingest_resp.raise_for_status()
            response["rag_update"] = "ok"
        except Exception as exc:  # pragma: no cover
            response["rag_update"] = f"failed: {exc}"

    return response


def parse_roles(raw: Optional[str]) -> Optional[list[str]]:
    if not raw:
        return None
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    return parts or None


# --- Aggregiertes Markdown Format ---

# Dokument-Typ Erkennung
DOC_TYPE_PATTERNS: dict[str, list[str]] = {
    "lastenheft": [
        r"lastenheft", r"anforderung", r"requirements",
        r"stakeholder", r"rahmenbedingung",
    ],
    "pflichtenheft": [
        r"pflichtenheft", r"spec", r"specification",
        r"abnahmekriterien", r"technische.*spezifikation",
    ],
    "architektur": [
        r"architektur", r"architecture", r"ARCHITECTURE",
        r"system.*design", r"komponenten.*übersicht",
    ],
    "design": [
        r"design", r"entwurf", r"konzept", r"datenmodell",
        r"sequenz", r"klassendiagramm",
    ],
}

CODE_EXTENSIONS: set[str] = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".cpp", ".c", ".h",
    ".go", ".rs", ".rb", ".php", ".cs", ".swift", ".kt", ".scala",
    ".sh", ".bash", ".zsh",
}


@dataclass
class ParsedFile:
    """Eine geparste Datei aus dem aggregierten Markdown."""
    source: str
    content: str
    language: str
    doc_type: str
    directory: str
    extension: str


@dataclass
class ParsedProject:
    """Ein geparstes Projekt aus dem aggregierten Markdown."""
    project_name: str
    project_id: str
    beschreibung: str
    verzeichnisstruktur: str
    files: list[ParsedFile] = field(default_factory=list)


def detect_doc_type(filepath: str, content: str) -> str:
    """Erkennt den Dokumenttyp basierend auf Pfad und Inhalt."""
    ext = Path(filepath).suffix.lower()
    if ext in CODE_EXTENSIONS:
        return "source_code"

    filepath_lower = filepath.lower()
    content_preview = content[:1000].lower() if content else ""

    for doc_type, patterns in DOC_TYPE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, filepath_lower) or re.search(pattern, content_preview):
                return doc_type

    # Fallback
    if ext in {".md", ".txt", ".rst"}:
        return "dokument"
    return "sonstiges"


def extract_project_name(beschreibung: str) -> str:
    """Extrahiert den Projektnamen aus der Projektbeschreibung."""
    patterns = [
        r"Projektname:\s*(.+?)(?:\n|$)",
        r"Projekt:\s*(.+?)(?:\n|$)",
        r"Name:\s*(.+?)(?:\n|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, beschreibung, re.IGNORECASE | re.MULTILINE)
        if match:
            name = match.group(1).strip()
            # Bereinige von Markdown-Formatierung
            name = re.sub(r"[*_`]", "", name)
            return name
    return "unbekannt"


def slugify_project(name: str) -> str:
    """Erzeugt eine URL-sichere Projekt-ID."""
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip().lower())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned or "projekt"


class AggregatedMarkdownParser:
    """Parser für das aggregierte Markdown-Format.

    Nutzt LangChains MarkdownHeaderTextSplitter für robustes Parsing.
    """

    def __init__(self) -> None:
        # Header-Konfiguration für den Splitter
        self.headers_to_split_on = [
            ("#", "section"),      # z.B. # DATEIINHALTE, # PROJEKTBESCHREIBUNG
            ("##", "dateiname"),   # z.B. ## DATEI: ./src/main.py
        ]
        self.splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=self.headers_to_split_on,
            strip_headers=False,
        )

    def parse(self, content: str) -> ParsedProject:
        """Parst eine aggregierte Markdown-Datei."""
        beschreibung = self._extract_projektbeschreibung(content)
        verzeichnisstruktur = self._extract_verzeichnisstruktur(content)
        files = self._extract_files_with_splitter(content)

        project_name = extract_project_name(beschreibung)
        project_id = slugify_project(project_name)

        return ParsedProject(
            project_name=project_name,
            project_id=project_id,
            beschreibung=beschreibung,
            verzeichnisstruktur=verzeichnisstruktur,
            files=files,
        )

    def _extract_projektbeschreibung(self, content: str) -> str:
        """Extrahiert die PROJEKTBESCHREIBUNG Sektion."""
        pattern = r"#\s*PROJEKTBESCHREIBUNG\s*\n(.*?)(?=\n---|\n#\s*DATEIINHALTE|$)"
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return ""

    def _extract_verzeichnisstruktur(self, content: str) -> str:
        """Extrahiert die VERZEICHNISSTRUKTUR Sektion."""
        pattern = r"#\s*VERZEICHNISSTRUKTUR\s*\n```(?:text)?\n(.*?)```"
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return ""

    def _extract_files_with_splitter(self, content: str) -> list[ParsedFile]:
        """Extrahiert Dateien mittels MarkdownHeaderTextSplitter."""
        files: list[ParsedFile] = []

        # Splitter anwenden
        docs = self.splitter.split_text(content)

        for doc in docs:
            metadata = doc.metadata
            text = doc.page_content

            # Nur DATEI-Sektionen verarbeiten
            dateiname = metadata.get("dateiname", "")
            if not dateiname or not dateiname.startswith("DATEI:"):
                continue

            # Dateipfad extrahieren (nach "DATEI: ")
            filepath = dateiname.replace("DATEI:", "").strip()
            if not filepath:
                continue

            # Code-Block-Inhalt und Sprache extrahieren
            language, file_content = self._extract_code_block(text)

            # Pfad-Komponenten
            path_obj = Path(filepath)
            directory = str(path_obj.parent)
            extension = path_obj.suffix.lower()

            # Dokument-Typ erkennen
            doc_type = detect_doc_type(filepath, file_content)

            files.append(ParsedFile(
                source=filepath,
                content=file_content,
                language=language,
                doc_type=doc_type,
                directory=directory,
                extension=extension,
            ))

        return files

    def _extract_code_block(self, text: str) -> tuple[str, str]:
        """Extrahiert Sprache und Inhalt aus einem Code-Block."""
        # Pattern: ```sprache\n...\n```
        pattern = r"```(\w*)\n(.*?)```"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            language = match.group(1).strip() or "text"
            content = match.group(2)
            return language, content
        # Fallback: gesamter Text ohne Code-Block
        return "text", text.strip()


@app.post("/extract/aggregated-md")
async def extract_aggregated_md(
    file: UploadFile = File(...),
    auto_update: bool = Form(False),
    roles: Optional[str] = Form(None),
    project_name_override: Optional[str] = Form(None),
) -> dict[str, Any]:
    """
    Extrahiert Dateien aus einer aggregierten Markdown-Datei.

    Das Format enthält:
    - # VERZEICHNISSTRUKTUR
    - # PROJEKTBESCHREIBUNG
    - # DATEIINHALTE mit ## DATEI: ./pfad/datei.ext Sektionen
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Dateiname fehlt.")

    try:
        raw_content = await file.read()
        content = raw_content.decode("utf-8")
    except UnicodeDecodeError:
        try:
            content = raw_content.decode("latin-1")
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Datei konnte nicht dekodiert werden: {exc}"
            ) from exc

    if not content.strip():
        raise HTTPException(status_code=400, detail="Datei ist leer.")

    # Parsen
    parser = AggregatedMarkdownParser()
    try:
        project = parser.parse(content)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Fehler beim Parsen: {exc}"
        ) from exc

    # Projekt-Name überschreiben falls angegeben
    if project_name_override:
        project.project_name = project_name_override
        project.project_id = slugify_project(project_name_override)

    if not project.files:
        raise HTTPException(
            status_code=422,
            detail="Keine DATEI-Sektionen gefunden. Format: ## DATEI: ./pfad/datei.ext"
        )

    # Response aufbauen
    parsed_roles = parse_roles(roles)

    chunks_info: list[dict[str, Any]] = []
    for f in project.files:
        chunks_info.append({
            "source": f.source,
            "doc_type": f.doc_type,
            "language": f.language,
            "directory": f.directory,
            "extension": f.extension,
            "chars": len(f.content),
        })

    meta_chunks: list[dict[str, Any]] = []
    if project.beschreibung:
        meta_chunks.append({
            "type": "projektbeschreibung",
            "chars": len(project.beschreibung),
        })
    if project.verzeichnisstruktur:
        meta_chunks.append({
            "type": "verzeichnisstruktur",
            "chars": len(project.verzeichnisstruktur),
        })

    response: dict[str, Any] = {
        "project_name": project.project_name,
        "project_id": project.project_id,
        "files_extracted": len(project.files),
        "chunks": chunks_info,
        "meta_chunks": meta_chunks,
        "roles": parsed_roles or [],
    }

    # Optional: RAG-Service Update
    if auto_update and RAG_SERVICE_URL:
        response["rag_update"] = await _trigger_rag_ingest(project, parsed_roles)

    return response


async def _trigger_rag_ingest(
    project: ParsedProject,
    roles: Optional[list[str]],
) -> str:
    """Sendet extrahierte Chunks an den RAG-Service."""
    try:
        # Projektbeschreibung als Meta-Chunk speichern
        if project.beschreibung:
            _save_chunk_as_file(
                project.project_id,
                "_meta",
                project.beschreibung,
                metadata={"doc_type": "meta", "language": "text"},
            )

        # Dateien als Chunks
        for f in project.files:
            _save_chunk_as_file(
                project.project_id,
                f.source,
                f.content,
                metadata={
                    "doc_type": f.doc_type,
                    "language": f.language,
                }
            )

        # Trigger update für das gesamte Projekt-Verzeichnis
        resp = httpx.post(
            f"{RAG_SERVICE_URL.rstrip('/')}/update",
            json={
                "path": f"data/{project.project_id}",
                "roles": roles,
            },
            timeout=60,
        )
        resp.raise_for_status()
        return "ok"

    except Exception as exc:
        return f"failed: {exc}"


def _save_chunk_as_file(
    project_id: str,
    source: str,
    content: str,
    metadata: Optional[dict[str, str]] = None,
) -> Path:
    """Speichert einen Chunk als Markdown-Datei."""
    # Projekt-Verzeichnis erstellen
    project_dir = OUTPUT_DIR / project_id
    project_dir.mkdir(parents=True, exist_ok=True)

    # Dateiname aus Source ableiten
    safe_name = re.sub(r"[^\w\-_.]", "_", source.replace("/", "_").replace("\\", "_"))
    if not safe_name.endswith(".md"):
        safe_name = f"{safe_name}.md"

    filepath = project_dir / safe_name

    # Metadaten als YAML-Frontmatter
    frontmatter = ""
    if metadata:
        frontmatter = "---\n"
        for key, value in metadata.items():
            frontmatter += f"{key}: {value}\n"
        frontmatter += "---\n\n"

    filepath.write_text(frontmatter + content, encoding="utf-8")
    return filepath
