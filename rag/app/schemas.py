from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

SourceType = Literal["file", "git"]


class DocumentRequest(BaseModel):
    source_type: SourceType = Field(
        default="file",
        description="Quelle der Daten (lokale Datei oder konfiguriertes Git-Repo).",
    )
    path: Path | None = Field(
        default=None,
        description="Pfad zur Datei. Für Git-Quellen ist dies der relative Pfad im Repo.",
    )
    patterns: list[str] | None = Field(
        default=None,
        description="Zusätzliche Glob-Pattern (bei Git relativ zum Repo).",
    )
    repo: str | None = Field(default=None, description="Name des Git-Repos aus der Konfiguration.")
    branch: str | None = Field(default=None, description="Optionaler Branch-Override.")
    commit: str | None = Field(default=None, description="Optionaler Commit-SHA für Checkout.")
    roles: list[str] | None = Field(
        default=None,
        description="Optionaler Satz an Rollen, die Zugriff auf das Dokument erhalten sollen.",
    )


class IngestRequest(DocumentRequest):
    """Request-Payload für /ingest."""


class UpdateRequest(DocumentRequest):
    previous_commit: str | None = Field(
        default=None,
        description="Commit-SHA der vorherigen Version für Delta-Updates in Git-Repos.",
    )


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3, description="Natürliche Frage an das Wissensmodell.")
    roles: list[str] | None = Field(
        default=None,
        description="Rollen des anfragenden Nutzers (zur Kontext-Filterung).",
    )


class QueryResponse(BaseModel):
    answer: str
    contexts: list[dict[str, object]]
