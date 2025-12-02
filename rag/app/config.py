from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings


class GitRepoConfig(BaseModel):
    """Konfigurationsobjekt für eine Git-Datenquelle."""

    name: str
    url: str
    branch: str = "main"
    depth: int | None = Field(default=None, gt=0)
    local_path: Path | None = None
    default_glob: str | None = None
    auto_update: bool = True


class Settings(BaseSettings):
    ollama_base_url: str = "http://ollama:11434"
    ollama_llm_model: str = "llama3"
    ollama_embed_model: str = "nomic-embed-text"
    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: str | None = None
    reranker_url: str | None = "http://reranker:80"
    reranker_top_k: int = 4
    reranker_initial_k: int = 20
    collection_name: str = "demo_documents"
    default_dataset_path: Path = Path("data/demo.md")
    data_roots: List[Path] = Field(default_factory=lambda: [Path("data")])
    git_workspace_root: Path = Path("/repos")
    git_repos: List[GitRepoConfig] = Field(default_factory=list)
    webhook_secret: str | None = Field(
        default=None,
        description="Gemeinsames Secret zur Signaturprüfung eingehender Webhooks.",
    )
    default_roles: List[str] = ["public"]
    max_context_chunks: int = 4
    chunk_size: int = 600
    chunk_overlap: int = 120
    tokenizer_encoding: str | None = Field(
        default="cl100k_base",
        description="tiktoken-Encoding für Token-basiertes Chunking (None -> Whitespace-Split).",
    )

    class Config:
        env_prefix = ""
        env_file = ".env"
        env_file_encoding = "utf-8"

    @field_validator("git_repos")
    @classmethod
    def _unique_repo_names(cls, repos: List[GitRepoConfig]) -> List[GitRepoConfig]:
        names: set[str] = set()
        for repo in repos:
            if repo.name in names:
                raise ValueError(f"Doppelte Git-Repo-Konfiguration für '{repo.name}'")
            names.add(repo.name)
        return repos

    def get_git_repo(self, name: str) -> GitRepoConfig:
        for repo in self.git_repos:
            if repo.name == name:
                target_path = repo.local_path or (self.git_workspace_root / repo.name)
                return repo.model_copy(update={"local_path": target_path})
        raise KeyError(f"Unbekanntes Git-Repository: {name}")


@lru_cache
def get_settings() -> Settings:
    return Settings()
