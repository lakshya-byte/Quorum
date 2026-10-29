#!/usr/bin/env python3
"""Read one repo run's SSE stream through the backend (stdlib only) for scripts/e2e.sh.

Writes a JSON summary to --out: ordered event types, time to the first event, the pr/done/repo events and
whether node events carried multi-file `files` and a unified `diff`. Never raises; errors land in "error".
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # localhost: never use a proxy


def cookie_header(jar_path: str) -> str:
    pairs = []
    for line in open(jar_path, encoding="utf-8"):
        line = line.rstrip("\n")
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        elif not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) == 7:
            pairs.append(f"{parts[5]}={parts[6]}")
    return "; ".join(pairs)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--cookie-jar", required=True)
    ap.add_argument("--t0", type=float, required=True, help="epoch seconds just before the POST that created the run")
    ap.add_argument("--timeout", type=float, default=90)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    res: dict = {"types": [], "error": None, "first_event_ms": None, "first_type": None, "end_ms": None}
    events: list[dict] = []
    try:
        req = urllib.request.Request(a.url, headers={"Accept": "text/event-stream", "Cookie": cookie_header(a.cookie_jar)})
        with OPENER.open(req, timeout=a.timeout) as resp:
            res["status"] = resp.status
            res["content_type"] = resp.headers.get("content-type", "")
            for raw in resp:
                line = raw.decode("utf-8").rstrip("\r\n")
                if not line.startswith("data: "):
                    continue
                now = time.time()
                ev = json.loads(line[len("data: "):])
                if res["first_event_ms"] is None:
                    res["first_event_ms"] = round((now - a.t0) * 1000, 1)
                    res["first_type"] = ev.get("type")
                events.append(ev)
                res["types"].append(ev.get("type"))
                if ev.get("type") == "end":
                    res["end_ms"] = round((now - a.t0) * 1000, 1)
                    break
    except Exception as exc:
        res["error"] = f"{type(exc).__name__}: {exc}"

    def first(kind: str):
        return next((e.get("data") or {} for e in events if e.get("type") == kind), None)

    nodes = [e.get("data") or {} for e in events if e.get("type") == "node"]
    res["repo"] = first("repo")
    res["locate"] = first("locate")
    res["repro"] = first("repro")
    res["done"] = first("done")
    res["pr"] = first("pr")
    res["nodes"] = len(nodes)
    res["nodes_with_files"] = sum(1 for n in nodes if isinstance(n.get("files"), dict) and n["files"])
    res["nodes_with_diff"] = sum(1 for n in nodes if n.get("diff"))
    best = (res["done"] or {}).get("best") or {}
    res["best_files"] = sorted((best.get("files") or {}).keys()) if isinstance(best, dict) else []
    res["errors"] = [e.get("data") for e in events if e.get("type") == "error"]
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(res, fh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
