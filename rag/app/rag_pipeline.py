from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path
from typing import Iterable, Sequence

from .config import GitRepoConfig, get_settings
from .git_sync import diff_changed_files, sync_repo
from .ollama_client import OllamaClient
from .reranker_client import RerankerClient
from .schemas import DocumentRequest, IngestRequest, UpdateRequest
from .text_utils import chunk_text, read_text_file
from .vectorstore import VectorDocument, VectorStore


class RAGPipeline:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.ollama = OllamaClient()
        self.vectorstore = VectorStore()
        self.reranker = RerankerClient()

    def ingest(self, req: IngestRequest) -> int:
        if req.source_type == "git":
            return self._ingest_git(req)
        return self.ingest_file(req.path, req.roles)

    def update(self, req: UpdateRequest) -> int:
        if req.source_type == "git":
            return self._update_git(req)
        return self.update_file(req.path, req.roles)

    def ingest_file(self, path: Path | None = None, roles: Sequence[str] | None = None) -> int:
        target = path or self.settings.default_dataset_path
        metadata = {
            "source": str(target),
            "source_kind": "file",
        }
        return self._ingest_documents([(read_text_file(target), metadata)], roles)

    def update_file(self, path: Path | None = None, roles: Sequence[str] | None = None) -> int:
        """Entfernt bestehende Chunks eines Dokuments und ingestiert die aktuelle Version."""
        target = path or self.settings.default_dataset_path
        self.vectorstore.delete_by_metadata(source=str(target))
        return self.ingest_file(target, roles)

    def answer(self, question: str, roles: Sequence[str] | None = None) -> dict[str, object]:
        allowed_roles = self._normalize_roles(roles)
        embed = self.ollama.embed([question])
        if not embed:
            raise RuntimeError("Konnte Anfrage nicht einbetten.")
        vector = embed[0]

        initial_k = (
            self.settings.reranker_initial_k
            if self.reranker.enabled
            else self.settings.max_context_chunks
        )
        contexts = self.vectorstore.search(vector, initial_k, allowed_roles)

        if self.reranker.enabled and contexts:
            contexts = self.reranker.rerank(
                query=question,
                documents=contexts,
                top_k=self.settings.max_context_chunks,
            )

        context_text = "\n\n".join(
            f"Quelle: {ctx['source']}\n{ctx['text']}" for ctx in contexts if ctx["text"]
        )
        prompt = (
            "Du bist ein präziser Assistent. Nutze ausschließlich den bereitgestellten Kontext.\n"
            "Wenn du keine Antwort im Kontext findest, sage, dass es nicht bekannt ist.\n\n"
            f"Kontext:\n{context_text}\n\nFrage: {question}\nAntwort:"
        )
        answer = self.ollama.generate(prompt)
        return {"answer": answer, "contexts": contexts}

    def _ingest_git(
        self,
        req: DocumentRequest,
        *,
        repo_cfg: GitRepoConfig | None = None,
        worktree: Path | None = None,
        commit: str | None = None,
    ) -> int:
        repo_cfg = repo_cfg or self._prepare_repo_config(req)
        branch = req.branch or repo_cfg.branch

        if worktree is None or commit is None:
            worktree, commit = sync_repo(repo_cfg, ref=req.commit or branch)

        patterns = self._git_patterns(req, repo_cfg)
        files = self._collect_git_files(worktree, patterns)
        if not files:
            raise FileNotFoundError(f"Keine passenden Dateien in {repo_cfg.name} gefunden.")

        documents = []
        for file_path in files:
            text = read_text_file(file_path)
            metadata = self._build_git_metadata(repo_cfg, worktree, file_path, commit, branch)
            documents.append((text, metadata))
        return self._ingest_documents(documents, req.roles)

    def _update_git(self, req: UpdateRequest) -> int:
        repo_cfg = self._prepare_repo_config(req)
        branch = req.branch or repo_cfg.branch
        worktree, new_commit = sync_repo(repo_cfg, ref=req.commit or branch)
        patterns = self._git_patterns(req, repo_cfg)

        if req.previous_commit:
            documents = []
            changes = diff_changed_files(repo_cfg, req.previous_commit, new_commit)
            for status, rel_path_str, old_path in changes:
                rel_path = Path(rel_path_str)
                if not self._matches_patterns(rel_path, patterns):
                    continue
                if status.startswith("D"):
                    self.vectorstore.delete_by_metadata(
                        git_repo=repo_cfg.name,
                        git_path=rel_path.as_posix(),
                    )
                    continue
                if old_path and status.startswith("R"):
                    self.vectorstore.delete_by_metadata(
                        git_repo=repo_cfg.name,
                        git_path=Path(old_path).as_posix(),
                    )
                file_path = (worktree / rel_path).resolve()
                if not file_path.is_file():
                    continue
                text = read_text_file(file_path)
                metadata = self._build_git_metadata(repo_cfg, worktree, file_path, new_commit, branch)
                documents.append((text, metadata))
            if not documents:
                return 0
            return self._ingest_documents(documents, req.roles)

        return self._ingest_git(
            req,
            repo_cfg=repo_cfg,
            worktree=worktree,
            commit=new_commit,
        )

    def _ingest_documents(
        self,
        sources: Iterable[tuple[str, dict[str, object]]],
        roles: Sequence[str] | None,
    ) -> int:
        allowed_roles = self._normalize_roles(roles)
        chunk_texts: list[str] = []
        documents: list[VectorDocument] = []
        for text, metadata in sources:
            chunks = chunk_text(
                text,
                self.settings.chunk_size,
                self.settings.chunk_overlap,
                tokenizer_name=self.settings.tokenizer_encoding,
            )
            for chunk in chunks:
                chunk_texts.append(chunk)
                documents.append(
                    VectorDocument(
                        content=chunk,
                        metadata={
                            **metadata,
                            "roles": allowed_roles,
                        },
                    )
                )

        if not chunk_texts:
            return 0

        vectors = self.ollama.embed(chunk_texts)
        if not vectors:
            return 0

        vector_size = len(vectors[0])
        self.vectorstore.ensure_collection(vector_size)
        self.vectorstore.upsert(vectors=vectors, documents=documents)
        return len(chunk_texts)

    def _prepare_repo_config(self, req: DocumentRequest) -> GitRepoConfig:
        if not req.repo:
            raise ValueError("Für Git-Quellen muss ein Repository angegeben werden.")
        repo_cfg = self.settings.get_git_repo(req.repo)
        updates: dict[str, object] = {}
        if req.branch:
            updates["branch"] = req.branch
        if updates:
            repo_cfg = repo_cfg.model_copy(update=updates)
        return repo_cfg

    def _git_patterns(self, req: DocumentRequest, repo_cfg: GitRepoConfig) -> list[str]:
        patterns: list[str] = []
        if req.path:
            patterns.append(req.path.as_posix())
        if req.patterns:
            patterns.extend(req.patterns)
        if not patterns and repo_cfg.default_glob:
            patterns.append(repo_cfg.default_glob)
        if not patterns:
            raise ValueError("Es wurde kein Pfad oder Pattern für das Git-Repo angegeben.")
        return [p.lstrip("/") for p in patterns]

    def _collect_git_files(self, worktree: Path, patterns: list[str]) -> list[Path]:
        files: set[Path] = set()
        for pattern in patterns:
            if self._is_glob(pattern):
                matches = [
                    candidate
                    for candidate in worktree.glob(pattern)
                    if candidate.is_file()
                ]
                files.update(matches)
                continue

            candidate = (worktree / pattern).resolve()
            if candidate.is_file():
                files.add(candidate)
            elif candidate.is_dir():
                files.update(path for path in candidate.rglob("*") if path.is_file())
        return sorted(files)

    def _matches_patterns(self, rel_path: Path, patterns: list[str]) -> bool:
        rel_posix = rel_path.as_posix()
        for pattern in patterns:
            if self._is_glob(pattern):
                if fnmatch(rel_posix, pattern):
                    return True
            else:
                normalized = pattern.rstrip("/")
                if rel_posix == normalized or rel_posix.startswith(f"{normalized}/"):
                    return True
        return False

    def _build_git_metadata(
        self,
        repo_cfg: GitRepoConfig,
        worktree: Path,
        file_path: Path,
        commit: str,
        branch: str,
    ) -> dict[str, object]:
        relative_path = file_path.relative_to(worktree).as_posix()
        return {
            "source": str(file_path),
            "source_kind": "git",
            "git_repo": repo_cfg.name,
            "git_url": repo_cfg.url,
            "git_branch": branch,
            "git_commit": commit,
            "git_path": relative_path,
        }

    def _normalize_roles(self, roles: Sequence[str] | None) -> list[str]:
        if roles:
            cleaned = [r.strip() for r in roles if r and r.strip()]
            if cleaned:
                return cleaned
        return self.settings.default_roles

    @staticmethod
    def _is_glob(pattern: str) -> bool:
        return any(char in pattern for char in "*?[]")
