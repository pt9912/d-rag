from __future__ import annotations

import hmac
import json
from hashlib import sha256
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .rag_pipeline import RAGPipeline
from .schemas import IngestRequest, QueryRequest, QueryResponse, UpdateRequest

app = FastAPI(
    title="Local RAG Service",
    version="0.1.0",
    description="Eigenständige RAG-API basierend auf Qdrant und Ollama.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

settings = get_settings()
pipeline = RAGPipeline()


@app.on_event("startup")
async def startup_event() -> None:
    try:
        ingested = pipeline.ingest_file(settings.default_dataset_path)
        if ingested:
            print(f"[RAG] {ingested} Chunks aus {settings.default_dataset_path} ingestiert.")
    except FileNotFoundError:
        print(f"[RAG] Keine Startdatei unter {settings.default_dataset_path} gefunden.")
    except Exception as exc:
        print(f"[RAG] Fehler beim Auto-Ingest: {exc}")


@app.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ingest")
def ingest(req: IngestRequest) -> dict[str, int]:
    try:
        ingested = pipeline.ingest(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"chunks": ingested}


@app.post("/update")
def update(req: UpdateRequest) -> dict[str, int]:
    try:
        chunks = pipeline.update(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"chunks": chunks}


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest) -> QueryResponse:
    try:
        result = pipeline.answer(req.question, req.roles)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return QueryResponse(**result)


def verify_signature(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
) -> None:
    secret = settings.webhook_secret
    if not secret:
        return
    if not x_hub_signature_256:
        raise HTTPException(status_code=401, detail="Fehlende Webhook-Signatur.")

    algorithm, _, provided_sig = x_hub_signature_256.partition("=")
    if algorithm.lower() != "sha256" or not provided_sig:
        raise HTTPException(status_code=401, detail="Ungültiges Signaturformat.")

    body = request.state.body
    computed = hmac.new(secret.encode(), body, sha256).hexdigest()
    if not hmac.compare_digest(computed, provided_sig):
        raise HTTPException(status_code=401, detail="Webhook-Signatur ungültig.")


@app.middleware("http")
async def capture_body(request: Request, call_next):
    request.state.body = await request.body()
    return await call_next(request)


@app.post("/git/webhook/{repo_name}")
async def git_webhook(
    repo_name: str,
    request: Request,
    signature_validated: None = Depends(verify_signature),
    x_github_event: str | None = Header(default=None, alias="X-GitHub-Event"),
) -> dict[str, Any]:
    payload = await request.json()
    event = x_github_event or payload.get("object_kind", "push")
    if event != "push":
        return {"status": "ignored", "reason": f"Event {event} wird nicht verarbeitet"}

    try:
        after = payload["after"]
        before = payload.get("before") or payload.get("checkout_sha")
        ref = payload.get("ref", "refs/heads/main").split("/", 2)[-1]
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"Pflichtfeld fehlt: {exc}") from exc

    update_req = UpdateRequest(
        source_type="git",
        repo=repo_name,
        branch=ref,
        commit=after,
        previous_commit=before,
    )
    try:
        chunks = pipeline.update(update_req)
    except Exception as exc:  # pragma: no cover - Laufzeitfehler
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "chunks": chunks, "commit": after}
