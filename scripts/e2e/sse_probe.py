#!/usr/bin/env python3
"""SSE probe for scripts/e2e.sh (stdlib only).

Reads one run's event stream through the backend and, at the same time, straight from the agent,
then checks the CONTRACT event order and fields and measures time to first node and relay overhead.
Prints one line per check: NAME<TAB>PASS|FAIL<TAB>detail, plus METRIC lines.
"""
from __future__ import annotations

import argparse
import json
import statistics
import threading
import time
import urllib.request

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # localhost: never use a proxy

NODE_FIELDS = {"id", "parent", "depth", "idea", "strategy", "code", "output", "passed", "total", "score",
               "model", "latency_ms", "tokens", "policy", "security"}
REQUIRED = {
    "run_started": {"run_id", "bug_id", "mode", "engine"},
    "guard": {"stage", "verdict", "reasons", "latency_ms"},
    "triage": {"cause", "strategies"},
    "round": {"depth"},
    "node": NODE_FIELDS,
    "critic": {"node_id", "lesson"},
    "done": {"solved", "best", "usage", "latency_ms", "time_to_first_node_ms"},
    "error": {"stage", "message"},
    "pr": {"url"},
}


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


def read_stream(url: str, headers: dict[str, str], out: dict, timeout: float) -> None:
    out.update(events=[], arrivals=[], headers={}, error=None, connected=None)
    try:
        req = urllib.request.Request(url, headers={"Accept": "text/event-stream", **headers})
        with OPENER.open(req, timeout=timeout) as resp:
            out["connected"] = time.time()
            out["status"] = resp.status
            out["headers"] = {k.lower(): v for k, v in resp.headers.items()}
            for raw in resp:
                line = raw.decode("utf-8").rstrip("\r\n")
                if not line.startswith("data: "):
                    continue
                out["arrivals"].append(time.time())
                ev = json.loads(line[len("data: "):])
                out["events"].append(ev)
                if ev.get("type") == "end":
                    break
    except Exception as exc:  # reported as a FAIL, never raised
        out["error"] = f"{type(exc).__name__}: {exc}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend-events", required=True)
    ap.add_argument("--cookie-jar", default="")
    ap.add_argument("--agent-events", default="")
    ap.add_argument("--agent-secret", default="")
    ap.add_argument("--t0", type=float, required=True, help="epoch seconds just before POST /api/runs")
    ap.add_argument("--min-rounds", type=int, default=2)
    ap.add_argument("--prefix", default="stream")
    ap.add_argument("--timeout", type=float, default=60)
    a = ap.parse_args()

    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((f"{a.prefix}: {name}", ok, detail))

    b: dict = {}
    g: dict = {}
    hdr = {"Cookie": cookie_header(a.cookie_jar)} if a.cookie_jar else {}
    threads = [threading.Thread(target=read_stream, args=(a.backend_events, hdr, b, a.timeout))]
    if a.agent_events:
        threads.append(threading.Thread(target=read_stream,
                                        args=(a.agent_events, {"X-Agent-Secret": a.agent_secret}, g, a.timeout)))
    for t in threads:
        t.start()
    for t in threads:
        t.join(a.timeout + 5)

    if b.get("error") or not b.get("events"):
        check("SSE through backend", False, b.get("error") or "no events")
        emit(results, {})
        return 0
    ct = b["headers"].get("content-type", "")
    check("SSE headers (text/event-stream, no-cache)",
          ct.startswith("text/event-stream") and "no-cache" in b["headers"].get("cache-control", ""), ct)

    ev = b["events"]
    types = [e.get("type") for e in ev]
    check("run_started first", types[0] == "run_started", types[0])
    check("end last", types[-1] == "end", types[-1])
    check("every message is {type,data}", all("type" in e and (e["type"] == "end" or isinstance(e.get("data"), dict))
                                               for e in ev), "")
    missing = []
    for e in ev:
        need = REQUIRED.get(e["type"], set())
        lack = need - set((e.get("data") or {}).keys())
        if lack:
            missing.append(f"{e['type']}:{sorted(lack)}")
    check("CONTRACT fields on every event", not missing, "; ".join(missing[:4]))

    def idx(pred, default=None):
        return next((i for i, e in enumerate(ev) if pred(e)), default)

    gi = idx(lambda e: e["type"] == "guard" and e["data"].get("stage") == "input")
    first_child = idx(lambda e: e["type"] == "node" and e["data"].get("parent") is not None)
    ti = idx(lambda e: e["type"] == "triage")
    check("guard input before first proposal", gi is not None and first_child is not None and gi < first_child,
          f"guard@{gi} first-proposal@{first_child}")
    if gi is not None:
        check("guard input verdict pass", ev[gi]["data"].get("verdict") == "pass", ev[gi]["data"].get("verdict"))
    check("triage before first non-root node", ti is not None and first_child is not None and ti < first_child,
          f"triage@{ti} first-proposal@{first_child}")
    rounds = [e["data"]["depth"] for e in ev if e["type"] == "round"]
    check(f">= {a.min_rounds} rounds", len(rounds) >= a.min_rounds, f"rounds={rounds}")
    if a.min_rounds >= 2:
        r2 = idx(lambda e: e["type"] == "round" and e["data"].get("depth") == 2)
        ci = idx(lambda e: e["type"] == "critic")
        check("critic before round 2", ci is not None and r2 is not None and ci < r2, f"critic@{ci} round2@{r2}")
    di = idx(lambda e: e["type"] == "done")
    check("done present, solved", di is not None and ev[di]["data"].get("solved") is True,
          f"done@{di} solved={ev[di]['data'].get('solved') if di is not None else None}")
    go = idx(lambda e: e["type"] == "guard" and e["data"].get("stage") == "output")
    check("guard output after done", go is not None and di is not None and go > di, f"guard-output@{go}")
    blocked = [e["data"]["id"] for e in ev if e["type"] == "node" and not e["data"]["policy"]["ok"]]
    check("policy gate blocked a tampering candidate", bool(blocked), f"blocked node ids {blocked}")

    metrics: dict[str, float] = {}
    fn = idx(lambda e: e["type"] == "node")
    if fn is not None:
        metrics["ttfn_ms_client"] = (b["arrivals"][fn] - a.t0) * 1000
        check("first node <= 1000 ms after POST (fake mode)", metrics["ttfn_ms_client"] <= 1000,
              f"{metrics['ttfn_ms_client']:.0f} ms")
    if di is not None:
        metrics["ttfn_ms_agent"] = float(ev[di]["data"].get("time_to_first_node_ms") or -1)
        metrics["run_latency_ms"] = float(ev[di]["data"].get("latency_ms") or -1)
    metrics["end_ms_client"] = (b["arrivals"][-1] - a.t0) * 1000

    if a.agent_events:
        if g.get("error") or not g.get("events"):
            check("agent stream (direct, for relay overhead)", False, g.get("error") or "no events")
        else:
            same = [e.get("type") for e in g["events"]] == types
            check("backend relays the agent stream byte-for-byte (same events)", same and g["events"] == ev,
                  f"agent={len(g['events'])} backend={len(ev)}")
            start = max(b["connected"], g["connected"])
            deltas = [(tb - tg) * 1000 for tb, tg in zip(b["arrivals"], g["arrivals"]) if tg > start + 0.005]
            if deltas:
                metrics["relay_p50_ms"] = statistics.median(deltas)
                metrics["relay_max_ms"] = max(deltas)
                check("relay overhead <= 50 ms (max over live events)", metrics["relay_max_ms"] <= 50,
                      f"p50 {metrics['relay_p50_ms']:.1f} ms, max {metrics['relay_max_ms']:.1f} ms, n={len(deltas)}")
    emit(results, metrics)
    return 0


def emit(results, metrics) -> None:
    for name, ok, detail in results:
        print(f"{name}\t{'PASS' if ok else 'FAIL'}\t{detail}")
    for k, v in metrics.items():
        print(f"METRIC\t{k}\t{v:.1f}")


if __name__ == "__main__":
    raise SystemExit(main())
