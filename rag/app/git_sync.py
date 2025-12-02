from __future__ import annotations

from pathlib import Path
from typing import List

from git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo

from .config import GitRepoConfig


class GitSyncError(Exception):
    """Allgemeine Fehlerklasse für Git-Synchronisationsprobleme."""


def sync_repo(repo_cfg: GitRepoConfig, ref: str | None = None) -> tuple[Path, str]:
    """Stellt sicher, dass ein lokaler Checkout vorhanden ist und gibt den commit hash zurück."""
    worktree = Path(repo_cfg.local_path or "")
    if not worktree:
        raise GitSyncError("Git-Repo-Konfiguration enthält keinen lokalen Pfad.")

    try:
        if worktree.exists():
            repo = Repo(worktree)
        else:
            worktree.parent.mkdir(parents=True, exist_ok=True)
            repo = _clone_repo(repo_cfg, worktree)
    except InvalidGitRepositoryError as exc:
        raise GitSyncError(f"Ungültiges Repository unter {worktree}") from exc

    try:
        _fetch_updates(repo, repo_cfg.depth)
    except GitCommandError as exc:  # pragma: no cover - Git-Fehler schwer testbar
        raise GitSyncError(f"Konnte Updates für {repo_cfg.name} nicht abrufen: {exc}") from exc

    target = ref or repo_cfg.branch
    try:
        commit = _checkout(repo, target, repo_cfg.branch)
    except GitCommandError as exc:  # pragma: no cover
        raise GitSyncError(f"Checkout von {target} fehlgeschlagen: {exc}") from exc

    return worktree, commit


def diff_changed_files(repo_cfg: GitRepoConfig, base: str, target: str) -> list[tuple[str, str, str | None]]:
    """Gibt eine Liste geänderter Dateien zwischen zwei Commits zurück.

    Rückgabeformat: (Status, neuer Pfad, alter Pfad falls vorhanden)
    """
    worktree = Path(repo_cfg.local_path or "")
    if not worktree:
        raise GitSyncError("Git-Repo-Konfiguration enthält keinen lokalen Pfad.")

    try:
        repo = Repo(worktree)
    except (InvalidGitRepositoryError, NoSuchPathError) as exc:
        raise GitSyncError(f"Repository {worktree} nicht gefunden.") from exc

    try:
        diff_output = repo.git.diff("--name-status", base, target)
    except GitCommandError as exc:
        raise GitSyncError(f"Diff zwischen {base} und {target} fehlgeschlagen: {exc}") from exc

    changes: list[tuple[str, str, str | None]] = []
    for line in diff_output.splitlines():
        parts = line.split("\t")
        status = parts[0]
        old_path: str | None = None
        if status.startswith("R") and len(parts) == 3:
            old_path, new_path = parts[1], parts[2]
            path = new_path
        else:
            path = parts[-1]
        changes.append((status, path, old_path))
    return changes


def _clone_repo(repo_cfg: GitRepoConfig, worktree: Path) -> Repo:
    clone_kwargs: dict[str, object] = {"branch": repo_cfg.branch}
    if repo_cfg.depth:
        clone_kwargs["depth"] = repo_cfg.depth
        clone_kwargs["single_branch"] = True
    return Repo.clone_from(repo_cfg.url, worktree, **clone_kwargs)


def _fetch_updates(repo: Repo, depth: int | None) -> None:
    remote = repo.remotes.origin
    fetch_kwargs: dict[str, object] = {}
    if depth:
        fetch_kwargs["depth"] = depth
    remote.fetch(**fetch_kwargs)


def _checkout(repo: Repo, ref: str, default_branch: str) -> str:
    try:
        repo.git.checkout(ref)
    except GitCommandError:
        # Fallback: remote branch?
        repo.git.checkout("-B", ref, f"origin/{ref}")
    if ref == default_branch:
        repo.git.reset("--hard", f"origin/{default_branch}")
    return repo.head.commit.hexsha
