// Package fakeagent is a stand-in for the Python agent that follows the
// shared CONTRACT. It is used by backend tests and by cmd/fakeagent for
// local demos. Every SSE event carries "ts_ms" (unix ms when the fake agent
// wrote it) inside data so relay overhead can be measured end to end.
//
// Special bug ids:
//
//	"crash"   streams a few events, writes half an event, then drops the TCP connection
//	"unsolved" ends with solved=false
//	"missing" is rejected with 404
package fakeagent

import (
	"bytes"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"sync"
	"time"
)

type Options struct {
	Secret      string
	CallbackURL string        // backend base URL; empty disables completion callbacks
	Delay       time.Duration // between events
}

type Agent struct {
	opts Options

	mu           sync.Mutex
	runs         map[string]runInfo
	Traceparents []string // traceparent headers seen (for tests)
	Created      []map[string]any
}

type runInfo struct {
	BugID, UserID, Mode, Engine string
}

func New(opts Options) *Agent {
	if opts.Delay == 0 {
		opts.Delay = 100 * time.Millisecond
	}
	return &Agent{opts: opts, runs: map[string]runInfo{}}
}

var Bugs = []map[string]any{
	{"id": "cart", "title": "Cart total ignores quantity", "issue": "Totals are wrong for qty > 1", "tier": 1},
	{"id": "dates", "title": "Off-by-one in date range", "issue": "Last day excluded", "tier": 2},
	{"id": "unsolved", "title": "A bug the agents cannot fix", "issue": "Always fails", "tier": 3},
	{"id": "crash", "title": "Agent dies mid-run", "issue": "Simulates an agent crash", "tier": 3},
}

func newID() string {
	b := make([]byte, 8)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

// SetCallbackURL sets the backend base URL for completion callbacks.
func (a *Agent) SetCallbackURL(u string) {
	a.mu.Lock()
	a.opts.CallbackURL = u
	a.mu.Unlock()
}

func (a *Agent) TraceparentsSeen() []string {
	a.mu.Lock()
	defer a.mu.Unlock()
	return append([]string(nil), a.Traceparents...)
}

func (a *Agent) CreatedRuns() []map[string]any {
	a.mu.Lock()
	defer a.mu.Unlock()
	return append([]map[string]any(nil), a.Created...)
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func (a *Agent) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path == "/health" {
		writeJSON(w, 200, map[string]any{"status": "ok", "mode": "fake"})
		return
	}
	if r.Header.Get("X-Agent-Secret") != a.opts.Secret {
		writeJSON(w, 401, map[string]any{"detail": "bad secret"})
		return
	}
	a.mu.Lock()
	if tp := r.Header.Get("traceparent"); tp != "" {
		a.Traceparents = append(a.Traceparents, tp)
	}
	a.mu.Unlock()

	path := strings.Trim(r.URL.Path, "/")
	parts := strings.Split(path, "/")
	switch {
	case r.Method == http.MethodGet && path == "bugs":
		writeJSON(w, 200, Bugs)
	case r.Method == http.MethodPost && path == "runs":
		a.createRun(w, r)
	case r.Method == http.MethodGet && len(parts) == 3 && parts[0] == "runs" && parts[2] == "events":
		a.stream(w, r, parts[1])
	case r.Method == http.MethodGet && len(parts) == 2 && parts[0] == "runs":
		a.mu.Lock()
		info, ok := a.runs[parts[1]]
		a.mu.Unlock()
		if !ok {
			writeJSON(w, 404, map[string]any{"detail": "run not found"})
			return
		}
		writeJSON(w, 200, map[string]any{"run_id": parts[1], "bug_id": info.BugID, "mode": info.Mode, "status": "done"})
	case r.Method == http.MethodPost && len(parts) == 3 && parts[0] == "runs" && parts[2] == "pr":
		a.mu.Lock()
		info, ok := a.runs[parts[1]]
		a.mu.Unlock()
		if !ok {
			writeJSON(w, 404, map[string]any{"detail": "run not found"})
			return
		}
		writeJSON(w, 200, map[string]any{"url": "https://github.com/example/patchloop-demo/pull/" + fmt.Sprint(len(info.BugID)+40)})
	default:
		writeJSON(w, 404, map[string]any{"detail": "not found"})
	}
}

func (a *Agent) createRun(w http.ResponseWriter, r *http.Request) {
	var body struct {
		BugID  string `json:"bug_id"`
		UserID string `json:"user_id"`
		Engine string `json:"engine"`
		Replay bool   `json:"replay"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeJSON(w, 422, map[string]any{"detail": "bad body"})
		return
	}
	found := false
	for _, b := range Bugs {
		if b["id"] == body.BugID {
			found = true
		}
	}
	if !found {
		writeJSON(w, 404, map[string]any{"detail": "unknown bug: " + body.BugID})
		return
	}
	mode := "live"
	if body.Replay {
		mode = "replay"
	}
	engine := body.Engine
	if engine == "" {
		engine = "loop"
	}
	id := newID()
	a.mu.Lock()
	a.runs[id] = runInfo{BugID: body.BugID, UserID: body.UserID, Mode: mode, Engine: engine}
	a.Created = append(a.Created, map[string]any{"bug_id": body.BugID, "user_id": body.UserID, "engine": body.Engine, "replay": body.Replay})
	a.mu.Unlock()
	writeJSON(w, 200, map[string]any{"run_id": id, "mode": mode, "engine": engine})
}

type event struct {
	Type string         `json:"type"`
	Data map[string]any `json:"data,omitempty"`
}

func nodes(solved bool) []map[string]any {
	mk := func(id, parent, depth int, idea string, passed, total int) map[string]any {
		return map[string]any{
			"id": id, "parent": parent, "depth": depth, "idea": idea, "strategy": idea,
			"code":   "def total(items):\n    return sum(i.price * i.qty for i in items)\n",
			"output": fmt.Sprintf("%d passed, %d failed", passed, total-passed),
			"passed": passed, "total": total, "score": float64(passed) / float64(total),
			"model": "nemotron-nano", "latency_ms": 900 + id*37, "tokens": 400 + id*11,
			"policy":   map[string]any{"ok": true, "reasons": []string{}},
			"security": map[string]any{"ok": true, "new_findings": 0},
		}
	}
	out := []map[string]any{
		mk(0, -1, 0, "original code", 2, 6),
		mk(1, 0, 1, "multiply price by quantity", 5, 6),
		mk(2, 0, 1, "handle empty cart", 3, 6),
		mk(3, 0, 1, "re-read the failing tests", 2, 6),
		mk(4, 1, 2, "round to cents after summing", 6, 6),
	}
	if !solved {
		out[4]["passed"] = 5
		out[4]["score"] = 5.0 / 6
		out[4]["output"] = "5 passed, 1 failed"
	}
	return out
}

func (a *Agent) stream(w http.ResponseWriter, r *http.Request, id string) {
	a.mu.Lock()
	info, ok := a.runs[id]
	a.mu.Unlock()
	if !ok {
		writeJSON(w, 404, map[string]any{"detail": "run not found"})
		return
	}
	flusher, _ := w.(http.Flusher)
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("X-Accel-Buffering", "no")
	w.WriteHeader(200)
	if flusher != nil {
		flusher.Flush()
	}

	solved := info.BugID != "unsolved"
	ns := nodes(solved)
	evs := []event{
		{"run_started", map[string]any{"run_id": id, "bug_id": info.BugID, "mode": info.Mode, "engine": info.Engine}},
		{"guard", map[string]any{"stage": "input", "verdict": "pass", "reasons": []string{}, "latency_ms": 12}},
		{"triage", map[string]any{"cause": "quantity is ignored when summing", "strategies": []string{"multiply by qty", "edge cases", "re-read tests"}}},
		{"round", map[string]any{"depth": 0}},
		{"node", ns[0]},
		{"round", map[string]any{"depth": 1}},
		{"node", ns[1]}, {"node", ns[2]}, {"node", ns[3]},
		{"critic", map[string]any{"node_id": 2, "lesson": "empty carts already work; focus on quantity"}},
		{"round", map[string]any{"depth": 2}},
		{"node", ns[4]},
		{"guard", map[string]any{"stage": "policy", "verdict": "pass", "reasons": []string{}, "latency_ms": 8}},
		{"guard", map[string]any{"stage": "output", "verdict": "pass", "reasons": []string{}, "latency_ms": 9}},
		{"done", map[string]any{"solved": solved, "best": ns[4], "usage": map[string]any{"prompt_tokens": 3120, "completion_tokens": 880}, "latency_ms": 4200, "time_to_first_node_ms": 350}},
		{"end", nil},
	}
	if info.BugID == "crash" {
		evs = evs[:5]
	}

	for i, ev := range evs {
		if i > 0 {
			select {
			case <-r.Context().Done():
				return
			case <-time.After(a.opts.Delay):
			}
		}
		if ev.Data == nil && ev.Type != "end" {
			ev.Data = map[string]any{}
		}
		if ev.Data != nil {
			ev.Data["ts_ms"] = float64(time.Now().UnixNano()) / 1e6
		}
		b, _ := json.Marshal(ev)
		if _, err := fmt.Fprintf(w, "data: %s\n\n", b); err != nil {
			return
		}
		if flusher != nil {
			flusher.Flush()
		}
	}

	if info.BugID == "crash" {
		time.Sleep(a.opts.Delay)
		_, _ = w.Write([]byte(`data: {"type": "node", "data": {"id": 9, "par`))
		if flusher != nil {
			flusher.Flush()
		}
		if hj, ok := w.(http.Hijacker); ok {
			if conn, _, err := hj.Hijack(); err == nil {
				conn.Close()
			}
		}
		return
	}

	a.callback(id, info, solved, ns)
}

func (a *Agent) callback(id string, info runInfo, solved bool, ns []map[string]any) {
	a.mu.Lock()
	cb := a.opts.CallbackURL
	a.mu.Unlock()
	if cb == "" {
		return
	}
	body, _ := json.Marshal(map[string]any{
		"run_id": id, "user_id": info.UserID, "bug_id": info.BugID, "mode": info.Mode, "engine": info.Engine,
		"solved": solved, "best_node_id": 4, "nodes": ns,
		"usage": map[string]any{"prompt_tokens": 3120, "completion_tokens": 880}, "latency_ms": 4200,
	})
	req, err := http.NewRequest(http.MethodPost, strings.TrimRight(cb, "/")+"/internal/runs/"+id+"/complete", bytes.NewReader(body))
	if err != nil {
		return
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Agent-Secret", a.opts.Secret)
	resp, err := (&http.Client{Timeout: 10 * time.Second}).Do(req)
	if err == nil {
		resp.Body.Close()
	}
}
