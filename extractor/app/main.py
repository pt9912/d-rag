from __future__ import annotations

import os
import re
from io import BytesIO
from pathlib import Path
from typing import Optional, Sequence

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pypdf import PdfReader
from zipfile import ZipFile, BadZipFile

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
            members = [item for item in archive.namelist() if item.lower().endswith(".pdf")]
            if not members:
                raise HTTPException(status_code=422, detail="ZIP enthält keine PDF-Dateien.")

            results = []
            parsed_roles = parse_roles(roles)
            for member in members:
                pdf_bytes = archive.read(member)
                if not pdf_bytes:
                    continue
                results.append(process_pdf_bytes(pdf_bytes, member, auto_update, parsed_roles))
    except BadZipFile as exc:
        raise HTTPException(status_code=422, detail=f"Ungültige ZIP-Datei: {exc}") from exc

    if not results:
        raise HTTPException(status_code=422, detail="Es konnten keine PDFs verarbeitet werden.")

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
        "roles": roles or [],
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


def parse_roles(raw: Optional[str]) -> Optional[list[str]]:
    if not raw:
        return None
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    return parts or None
