import base64
import copy
import json

import pytest

from core.storage import Conflict, GitHubStore, projections, seed


class FakeAPI:
    def __init__(self, private=True):
        self.private = private
        self.head = "initial"
        self.snapshots = {"initial": projections(seed())}
        self.trees = {}
        self.parents = {}
        self.conflict_once = False
        self.index = 0

    def request(self, method, path, body=None, allow_missing=False):
        if path == "" and method == "GET":
            return {"private": self.private, "default_branch": "main"}
        if path == "/git/ref/heads/angelis-data":
            return {"object": {"sha": self.head}}
        if path.startswith("/contents/data/workspace.json?ref="):
            sha = path.split("=")[-1]
            content = self.snapshots[sha]["data/workspace.json"].encode()
            return {"encoding": "base64", "content": base64.b64encode(content).decode()}
        if path.startswith("/git/commits/"):
            return {"tree": {"sha": path.rsplit("/", 1)[-1]}}
        if method == "POST" and path == "/git/trees":
            files = copy.deepcopy(self.snapshots[body["base_tree"]])
            for item in body["tree"]:
                files[item["path"]] = item["content"]
            self.index += 1
            tree_id = f"tree-{self.index}"
            self.trees[tree_id] = files
            return {"sha": tree_id}
        if method == "POST" and path == "/git/commits":
            sha = f"commit-{self.index}"
            self.snapshots[sha] = self.trees[body["tree"]]
            self.parents[sha] = body["parents"][0]
            return {"sha": sha}
        if method == "PATCH":
            assert body["force"] is False
            if self.conflict_once:
                self.conflict_once = False
                data = json.loads(self.snapshots[self.head]["data/workspace.json"])
                data["state"]["active_questions"].append("Concurrent external update")
                self.snapshots["concurrent"] = {**self.snapshots[self.head], "data/workspace.json": json.dumps(data)}
                self.head = "concurrent"
                raise Conflict()
            assert self.parents[body["sha"]] == self.head
            self.head = body["sha"]
            return {"object": {"sha": self.head}}
        raise AssertionError((method, path, body))


@pytest.mark.parametrize("private", [True, False])
def test_git_commit_is_atomic_and_retries_without_losing_concurrent_edits(monkeypatch, private):
    api = FakeAPI(private)
    monkeypatch.setattr(GitHubStore, "_request", lambda self, *args, **kwargs: api.request(*args, **kwargs))
    store = GitHubStore("owner/workspace", "test-token")
    api.conflict_once = True
    store.transact(lambda data: data["state"]["active_questions"].append("Our new question"))
    data = store.load()
    assert data["state"]["active_questions"].count("Our new question") == 1
    assert "Concurrent external update" in data["state"]["active_questions"]
    committed = api.snapshots[api.head]
    assert "data/state/STATE.json" in committed
    assert "data/backlog/BACKLOG.csv" in committed
    assert json.loads(committed["data/state/STATE.json"])["active_questions"] == data["state"]["active_questions"]
