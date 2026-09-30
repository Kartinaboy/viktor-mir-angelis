from __future__ import annotations

import base64
import copy
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Callable

import requests
from filelock import FileLock

from .config import defaults, validate_settings
from .models import json_text, now, parse_backlog, safe_path, validate_workspace, write_backlog

SPEC = Path(__file__).resolve().parents[1] / "spec"


class Conflict(Exception):
    pass


def seed() -> dict:
    state = json.loads((SPEC / "STATE.json").read_text(encoding="utf-8-sig"))
    state.update({"current_priorities": [], "latest_findings": [], "pointers": [], "active_projects": []})
    data = {"schema_version": 1, "state": state,
            "backlog": parse_backlog((SPEC / "BACKLOG.csv").read_text(encoding="utf-8-sig")),
            "settings": defaults(), "runs": {}, "journal": [], "artifacts": {},
            "lease": None, "schedule_last": {}, "onboarding_completed": False, "updated_at": now()}
    validate_workspace(data)
    return data


def projections(data: dict) -> dict[str, str]:
    files = {
        "data/workspace.json": json_text(data),
        "data/state/STATE.json": json_text(data["state"]),
        "data/backlog/BACKLOG.csv": write_backlog(data["backlog"]),
        "data/settings.json": json_text(data["settings"]),
        "data/journal/JOURNAL.jsonl": "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in data["journal"]),
    }
    for run_id, run in data["runs"].items():
        files[safe_path(f"data/runs/{run_id}.json")] = json_text(run)
    for artifact in data["artifacts"].values():
        path = safe_path(artifact["path"])
        files[path] = artifact["content"]
        files[safe_path(path + ".metadata.json")] = json_text({k: v for k, v in artifact.items() if k != "content"})
    return files


class MemoryStore:
    """Only for tests. The production UI never selects this provider."""
    def __init__(self, data=None):
        import threading
        self.data = copy.deepcopy(data or seed())
        self.lock = threading.RLock()

    def load(self):
        with self.lock:
            return copy.deepcopy(self.data)

    def transact(self, mutation: Callable, message="Ангелис update"):
        with self.lock:
            data = self.load()
            result = mutation(data)
            validate_workspace(data)
            validate_settings(data["settings"])
            data["updated_at"] = now()
            self.data = data
            return result


class LocalStore:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "workspace.json"
        self.lock = FileLock(str(self.directory / ".workspace.lock"), timeout=30)
        with self.lock:
            if not self.path.exists():
                self._save(seed())
            else:
                # Refresh mirrors after a crash between the authoritative JSON and projections.
                self._save(self.load())

    def _atomic(self, target: Path, text: str):
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=".angelis-", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, target)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def _save(self, data):
        # Single atomic JSON is authoritative. Human-readable projections are recoverable mirrors.
        self._atomic(self.path, json_text(data))
        for path, content in projections(data).items():
            self._atomic(self.directory / path.removeprefix("data/"), content)

    def load(self):
        data = json.loads(self.path.read_text(encoding="utf-8"))
        validate_workspace(data)
        return data

    def transact(self, mutation: Callable, message="Ангелис update"):
        with self.lock:
            data = self.load()
            result = mutation(data)
            validate_workspace(data)
            validate_settings(data["settings"])
            data["updated_at"] = now()
            self._save(data)
            return result


class GitHubStore:
    """Atomic Git tree commits; compare-and-swap through fast-forward-only ref updates.

    No credentials or API keys are stored in workspace.json or Git commits.
    The data branch must be private. UI and Actions share the same branch.
    """
    def __init__(self, repository: str, token: str, branch="angelis-data"):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("GITHUB_REPO должен быть owner/repo")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", branch) or branch in {"main", "master"}:
            raise ValueError("Нужна отдельная ветка данных, например angelis-data")
        self.repository, self.branch = repository, branch
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
        repo = self._request("GET", "")
        if not repo.get("private"):
            raise ValueError("Состояние Ангелис можно сохранять только в приватном репозитории")
        if branch == repo["default_branch"]:
            raise ValueError("Ветка данных должна отличаться от основной ветки")
        if self._request("GET", f"/git/ref/heads/{branch}", allow_missing=True) is None:
            base = self._request("GET", f"/git/ref/heads/{repo['default_branch']}")
            try:
                self._request("POST", "/git/refs", {"ref": f"refs/heads/{branch}", "sha": base["object"]["sha"]})
            except Conflict:
                self._request("GET", f"/git/ref/heads/{branch}")
        if self._snapshot()[1] is None:
            self.transact(lambda data: None, "Initialize Ангелис state")

    def _request(self, method, path, body=None, allow_missing=False):
        response = self.session.request(method, f"https://api.github.com/repos/{self.repository}{path}", json=body, timeout=30)
        if response.status_code == 404 and allow_missing:
            return None
        if response.status_code in {409, 422}:
            raise Conflict("Данные изменились другим запуском; обновите экран")
        if not response.ok:
            # Don't include request headers, credentials, or provider error bodies.
            raise RuntimeError(f"GitHub: HTTP {response.status_code}. Проверьте права Contents и название репозитория.")
        return response.json()

    def _snapshot(self):
        ref = self._request("GET", f"/git/ref/heads/{self.branch}")
        sha = ref["object"]["sha"]
        file = self._request("GET", f"/contents/data/workspace.json?ref={sha}", allow_missing=True)
        if file is None:
            return sha, None
        if file.get("encoding") != "base64":
            file = self._request("GET", f"/git/blobs/{file['sha']}")
        data = json.loads(base64.b64decode(file["content"]))
        validate_workspace(data)
        return sha, data

    def load(self):
        _, data = self._snapshot()
        if data is None:
            raise RuntimeError("Состояние ещё не инициализировано")
        return data

    def transact(self, mutation: Callable, message="Ангелис update"):
        # Callback must be pure: never put API calls inside a mutation.
        for attempt in range(4):
            sha, previous = self._snapshot()
            data = copy.deepcopy(previous if previous is not None else seed())
            result = mutation(data)
            validate_workspace(data)
            validate_settings(data["settings"])
            data["updated_at"] = now()
            current = projections(data)
            if len(current["data/workspace.json"].encode("utf-8")) > 9_000_000:
                raise ValueError("Архив достиг 9 МБ. Экспортируйте данные; для роста нужна миграция хранилища.")
            old_files = projections(previous) if previous else {}
            changes = [{"path": path, "mode": "100644", "type": "blob", "content": text}
                       for path, text in current.items() if old_files.get(path) != text]
            commit = self._request("GET", f"/git/commits/{sha}")
            tree = self._request("POST", "/git/trees", {"base_tree": commit["tree"]["sha"], "tree": changes})
            new = self._request("POST", "/git/commits", {"message": message[:160], "tree": tree["sha"], "parents": [sha]})
            try:
                self._request("PATCH", f"/git/refs/heads/{self.branch}", {"sha": new["sha"], "force": False})
                return result
            except Conflict:
                if attempt == 3:
                    raise


def store_from_credentials(credentials: dict):
    mode = credentials.get("ANGELIS_STORAGE", "github")
    if mode == "local":
        return LocalStore(credentials.get("ANGELIS_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
    if mode != "github":
        raise ValueError("ANGELIS_STORAGE должен быть github или local")
    token = credentials.get("GITHUB_TOKEN")
    repo = credentials.get("GITHUB_REPO")
    if not token or not repo:
        raise ValueError("Нужны GITHUB_TOKEN и GITHUB_REPO в Secrets")
    return GitHubStore(repo, token, credentials.get("GITHUB_DATA_BRANCH", "angelis-data"))
