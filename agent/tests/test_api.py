import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

SECRET = "test-secret"
HEADERS = {"X-Agent-Secret": SECRET}


@pytest.fixture
def client(tmp_path: Path):
    settings = Settings(shared_secret=SECRET, backend_callback_url="", mode="fake", runs_dir=tmp_path)
    with TestClient(create_app(settings)) as c:
        yield c


def read_sse(client: TestClient, run_id: str) -> list[dict]:
    events = []
    with client.stream("GET", f"/runs/{run_id}/events", headers=HEADERS) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        for line in resp.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))
    return events


def test_health_needs_no_secret(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok", "mode": "fake"}


def test_routes_require_secret(client: TestClient) -> None:
    assert client.get("/bugs").status_code == 401
    assert client.get("/bugs", headers={"X-Agent-Secret": "wrong"}).status_code == 401
    assert client.post("/runs", json={"bug_id": "cart"}).status_code == 401


def test_list_bugs(client: TestClient) -> None:
    bugs = client.get("/bugs", headers=HEADERS).json()
    assert {b["id"] for b in bugs} == {"paginate", "slugify", "cart", "average"}


def test_fake_run_streams_nodes_and_ends(client: TestClient, tmp_path: Path) -> None:
    resp = client.post("/runs", json={"bug_id": "cart", "user_id": "u1"}, headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "fake"

    events = read_sse(client, body["run_id"])
    types = [e["type"] for e in events]
    assert "node" in types
    assert types[-2] == "done" and events[-2]["data"]["solved"] is True
    assert types[-1] == "end"

    run = client.get(f"/runs/{body['run_id']}", headers=HEADERS).json()
    assert run["status"] == "done"
    assert (tmp_path / f"{body['run_id']}.json").is_file()


def test_unknown_bug_and_unsolved_pr(client: TestClient) -> None:
    assert client.post("/runs", json={"bug_id": "nope"}, headers=HEADERS).status_code == 404
    assert client.post("/runs/missing/pr", headers=HEADERS).status_code == 404


def test_replay_falls_back_to_fake_without_saved_runs(client: TestClient) -> None:
    body = client.post("/runs", json={"bug_id": "average", "replay": True}, headers=HEADERS).json()
    assert body["mode"] == "fake"
    assert client.get("/replays", headers=HEADERS).json() == []


def test_replay_streams_a_saved_real_run(client: TestClient, tmp_path: Path) -> None:
    best = {"id": 1, "parent": 0, "depth": 1, "idea": "fix", "code": "x", "output": "OK",
            "passed": 6, "total": 6, "score": 0.99, "model": "m"}
    record = {
        "run_id": "abc123", "bug_id": "cart", "mode": "live", "status": "done", "created_at": 1.0,
        "events": [
            {"type": "node", "data": {**best, "id": 0, "parent": None, "depth": 0, "passed": 1, "score": 0.16}},
            {"type": "round", "data": {"depth": 1}},
            {"type": "node", "data": best},
            {"type": "done", "data": {"solved": True, "best": best, "usage": {}}},
        ],
    }
    (tmp_path / "abc123.json").write_text(json.dumps(record))

    assert [r["run_id"] for r in client.get("/replays", headers=HEADERS).json()] == ["abc123"]
    body = client.post("/runs", json={"bug_id": "cart", "replay": True}, headers=HEADERS).json()
    assert body["mode"] == "replay" and body["replay_of"] == "abc123"
    types = [e["type"] for e in read_sse(client, body["run_id"])]
    assert types == ["node", "round", "node", "done", "end"]
