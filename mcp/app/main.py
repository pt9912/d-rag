from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import TextContent
from starlette.requests import Request
from starlette.responses import JSONResponse

RAG_SERVICE_URL = os.getenv("RAG_SERVICE_URL", "http://rag-service:8000")
SERVER_NAME = "rag-mcp-gateway"
SERVER_VERSION = "0.2.0"
DEFAULT_TRANSPORT = os.getenv("MCP_TRANSPORT", "streamable-http")

server = FastMCP(
    name=SERVER_NAME,
    instructions="Gateway zum RAG-Service. Stellt die Tools rag.query, rag.ingest und rag.update zur Verfügung.",
)


async def _call_rag(endpoint: str, payload: dict[str, Any]) -> httpx.Response:
    """Hilfsfunktion für HTTP-Aufrufe an den RAG-Dienst."""
    url = f"{RAG_SERVICE_URL}{endpoint}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as exc:  # pragma: no cover - Netzwerkfehler
            raise ToolError(
                f"RAG-Service antwortete mit Status {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except httpx.RequestError as exc:  # pragma: no cover - Netzwerkfehler
            raise ToolError(f"RAG-Service nicht erreichbar: {exc}") from exc


@server.tool(name="rag.query", description="Stellt eine Frage an den RAG-Dienst.")
async def rag_query(question: str, roles: list[str] | None = None) -> list[TextContent]:
    """Frage an den RAG-Service stellen."""
    resp = await _call_rag("/query", {"question": question, "roles": roles})
    data = resp.json()
    answer = data.get("answer") or ""
    contexts = data.get("contexts") or []
    return [
        TextContent(type="text", text=answer),
        TextContent(type="text", text=f"Contexts: {contexts}"),
    ]


@server.tool(name="rag.ingest", description="Ingestiert eine Datei in den RAG-Dienst.")
async def rag_ingest(path: str, roles: list[str] | None = None) -> str:
    """Datei in den Vectorstore ingestieren."""
    resp = await _call_rag("/ingest", {"path": path, "roles": roles})
    return f"Ingest result: {resp.text}"


@server.tool(name="rag.update", description="Aktualisiert eine Datei im Vectorstore.")
async def rag_update(path: str, roles: list[str] | None = None) -> str:
    """Datei im Vectorstore aktualisieren."""
    resp = await _call_rag("/update", {"path": path, "roles": roles})
    return f"Update result: {resp.text}"


@server.custom_route("/healthz", ["GET"])
async def health(_: Request) -> JSONResponse:
    """Health-Endpoint für Infrastruktur-Checks."""
    return JSONResponse({"status": "ok", "version": SERVER_VERSION})


app = server.streamable_http_app()


def main() -> None:  # pragma: no cover - Laufzeit-Einstieg
    """Optionaler CLI-Einstieg für stdio oder HTTP-Server."""
    server.run(transport=DEFAULT_TRANSPORT)


if __name__ == "__main__":  # pragma: no cover - Laufzeit-Einstieg
    main()
