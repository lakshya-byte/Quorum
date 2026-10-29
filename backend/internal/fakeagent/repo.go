package fakeagent

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"regexp"
	"strings"
	"sync"
	"time"
)

// repoRun is a repo-flow run. Unlike bug runs it executes in the background
// from creation (like the real agent), appending to a replayable log, so a
// run completes even when nobody streams it.
type repoRun struct {
	mu       sync.Mutex
	events   []event
	finished bool
	wake     chan struct{}

	id, repo, branch, task, source string
	autoPR, demo, hasToken         bool
	followup                       map[string]any
	solved                         bool
	prURL, prBranch                string
	prNumber                       int
	crash                          bool
}

func (r *repoRun) append(ev event) {
	r.mu.Lock()
	r.events = append(r.events, ev)
	old := r.wake
	r.wake = make(chan struct{})
	r.mu.Unlock()
	close(old)
}

func (r *repoRun) finish() {
	r.mu.Lock()
	r.finished = true
	old := r.wake
	r.wake = make(chan struct{})
	r.mu.Unlock()
	close(old)
}

// snapshot returns events from index i, whether the run is finished, and a
// channel that closes on the next change.
func (r *repoRun) snapshot(i int) ([]event, bool, <-chan struct{}) {
	r.mu.Lock()
	defer r.mu.Unlock()
	return append([]event(nil), r.events[i:]...), r.finished, r.wake
}

var slugRe = regexp.MustCompile(`[^a-z0-9]+`)

func slug(s string) string {
	s = strings.Trim(slugRe.ReplaceAllString(strings.ToLower(s), "-"), "-")
	if len(s) > 30 {
		s = strings.Trim(s[:30], "-")
	}
	if s == "" {
		s = "fix"
	}
	return s
}

func (a *Agent) createRepoRun(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Task        string  `json:"task"`
		GitHubToken *string `json:"github_token"`
		UserID      string  `json:"user_id"`
		Engine      string  `json:"engine"`
		AutoPR      bool    `json:"auto_pr"`
		RunURL      string  `json:"run_url"`
		Source      string  `json:"source"`
		IssueRef    *int    `json:"issue_ref"`
		Repo        struct {
			FullName string `json:"full_name"`
			Branch   string `json:"branch"`
		} `json:"repo"`
		Followup map[string]any `json:"followup"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeJSON(w, 422, map[string]any{"detail": "bad body"})
		return
	}
	if strings.TrimSpace(body.Task) == "" || body.Repo.FullName == "" {
		writeJSON(w, 422, map[string]any{"detail": "task and repo.full_name are required"})
		return
	}
	demo := strings.HasPrefix(body.Repo.FullName, "demo/")
	hasToken := body.GitHubToken != nil && *body.GitHubToken != ""
	if !demo && !hasToken {
		writeJSON(w, 400, map[string]any{"detail": "github_token is required for non-demo repos"})
		return
	}
	engine := body.Engine
	if engine == "" {
		engine = "graph"
	}
	id := newID()
	rr := &repoRun{
		id: id, repo: body.Repo.FullName, branch: body.Repo.Branch, task: body.Task, source: body.Source,
		autoPR: body.AutoPR, demo: demo, hasToken: hasToken, followup: body.Followup, wake: make(chan struct{}),
		solved: !strings.Contains(strings.ToLower(body.Task), "unsolvable"),
		crash:  strings.Contains(strings.ToLower(body.Task), "crashagent"),
	}
	a.mu.Lock()
	a.runs[id] = runInfo{BugID: body.Repo.FullName, UserID: body.UserID, Mode: "fake", Engine: engine}
	a.repoRuns[id] = rr
	a.prSeq++
	seq := a.prSeq
	created := map[string]any{"repo": body.Repo.FullName, "branch": body.Repo.Branch, "task": body.Task, "user_id": body.UserID,
		"engine": body.Engine, "auto_pr": body.AutoPR, "run_url": body.RunURL, "source": body.Source,
		"has_token": hasToken, "followup": body.Followup, "issue_ref": body.IssueRef}
	if hasToken {
		created["github_token"] = *body.GitHubToken // for tests only; never logged or echoed
	}
	a.Created = append(a.Created, created)
	a.mu.Unlock()

	if body.Followup != nil {
		rr.prBranch, _ = body.Followup["pr_branch"].(string)
		if n, ok := body.Followup["pr_number"].(float64); ok {
			rr.prNumber = int(n)
		}
	} else {
		rr.prBranch = fmt.Sprintf("patchloop/%s-%d", slug(body.Task), time.Now().Unix())
		rr.prNumber = 40 + seq
	}
	rr.prURL = fmt.Sprintf("https://github.com/%s/pull/%d", rr.repo, rr.prNumber)

	go a.executeRepoRun(rr, engine, body.UserID, body.RunURL)
	writeJSON(w, 200, map[string]any{"run_id": id, "mode": "fake", "engine": engine, "trace_id": "trace-" + id})
}

func repoNodes(solved bool, repo string) []map[string]any {
	file := "src/app.py"
	fixed := "def paginate(items, page, size):\n    start = (page - 1) * size\n    return items[start:start + size]\n"
	diff := "--- a/src/app.py\n+++ b/src/app.py\n@@ -1,3 +1,3 @@\n def paginate(items, page, size):\n-    start = page * size\n+    start = (page - 1) * size\n     return items[start:start + size]\n"
	ns := nodes(solved)
	for _, n := range ns {
		n["code"] = fixed
		n["files"] = map[string]any{file: fixed}
		n["diff"] = diff
	}
	return ns
}

func (a *Agent) executeRepoRun(rr *repoRun, engine, userID, runURL string) {
	ns := repoNodes(rr.solved, rr.repo)
	delay := a.opts.Delay
	emit := func(typ string, data map[string]any) {
		if data == nil {
			data = map[string]any{}
		}
		data["ts_ms"] = float64(time.Now().UnixNano()) / 1e6
		rr.append(event{Type: typ, Data: data})
		time.Sleep(delay)
	}
	emit("run_started", map[string]any{"run_id": rr.id, "bug_id": rr.repo, "mode": "fake", "engine": engine, "kind": "repo"})
	emit("repo", map[string]any{"full_name": rr.repo, "branch": rr.branch, "files": 14, "language": "python", "test_command": "python -m unittest", "truncated": false})
	emit("guard", map[string]any{"stage": "input", "verdict": "pass", "reasons": []string{}, "latency_ms": 12})
	emit("triage", map[string]any{"cause": "the page offset is computed from page instead of page-1", "strategies": []string{"fix offset", "edge cases", "re-read tests"}})
	emit("locate", map[string]any{"files": []map[string]any{{"path": "src/app.py", "reason": "defines paginate()"}}})
	if rr.crash {
		return // never finishes: simulates an agent that died mid-run
	}
	emit("repro", map[string]any{"path": "tests/test_repro_pagination.py", "test_name": "test_last_page_is_returned", "failed_on_original": true, "output_tail": "AssertionError: [] != [9, 10]"})
	if rr.followup != nil {
		emit("round", map[string]any{"depth": 0})
		emit("node", ns[4])
	} else {
		emit("round", map[string]any{"depth": 0})
		emit("node", ns[0])
		emit("round", map[string]any{"depth": 1})
		emit("node", ns[1])
		emit("node", ns[2])
		emit("node", ns[3])
		emit("critic", map[string]any{"node_id": 2, "lesson": "empty input already works; focus on the offset"})
		emit("round", map[string]any{"depth": 2})
		emit("node", ns[4])
	}
	emit("guard", map[string]any{"stage": "output", "verdict": "pass", "reasons": []string{}, "latency_ms": 9})
	usage := map[string]any{"prompt_tokens": 3120, "completion_tokens": 880}
	emit("done", map[string]any{"solved": rr.solved, "best": ns[4], "usage": usage, "latency_ms": 4200})

	prURL := ""
	if rr.solved && (rr.autoPR || rr.followup != nil) {
		prURL = rr.prURL
		emit("pr", map[string]any{"url": rr.prURL, "branch": rr.prBranch, "number": rr.prNumber, "fake": true, "updated": rr.followup != nil})
	}
	rr.append(event{Type: "end"})
	rr.finish()
	a.repoCallback(rr, userID, ns, prURL, usage)
}

func (a *Agent) repoCallback(rr *repoRun, userID string, ns []map[string]any, prURL string, usage map[string]any) {
	a.mu.Lock()
	cb := a.opts.CallbackURL
	a.mu.Unlock()
	if cb == "" {
		return
	}
	payload := map[string]any{
		"run_id": rr.id, "user_id": userID, "bug_id": rr.repo, "kind": "repo", "repo": rr.repo, "branch": rr.branch, "task": rr.task,
		"mode": "fake", "engine": "graph", "solved": rr.solved, "best_node_id": 4, "nodes": ns, "usage": usage, "latency_ms": 4200,
		"files_changed": []string{"src/app.py"},
		"safety":        map[string]any{"policy": map[string]any{"ok": true}, "security": map[string]any{"tool": "bandit", "new_findings": 0}, "guard": map[string]any{"input": "pass", "output": "pass"}},
	}
	if prURL != "" {
		payload["pr_url"], payload["pr_number"], payload["pr_branch"] = prURL, rr.prNumber, rr.prBranch
	}
	body, _ := json.Marshal(payload)
	req, err := http.NewRequest(http.MethodPost, strings.TrimRight(cb, "/")+"/internal/runs/"+rr.id+"/complete", bytes.NewReader(body))
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

// streamRepo replays the run log to a client and follows it until the end.
func (a *Agent) streamRepo(w http.ResponseWriter, r *http.Request, rr *repoRun) {
	flusher, _ := w.(http.Flusher)
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("X-Accel-Buffering", "no")
	w.WriteHeader(200)
	if flusher != nil {
		flusher.Flush()
	}
	i := 0
	for {
		evs, done, wake := rr.snapshot(i)
		for _, ev := range evs {
			b, _ := json.Marshal(ev)
			if _, err := fmt.Fprintf(w, "data: %s\n\n", b); err != nil {
				return
			}
			i++
		}
		if flusher != nil {
			flusher.Flush()
		}
		if done && len(evs) == 0 {
			return
		}
		if len(evs) > 0 {
			continue
		}
		select {
		case <-r.Context().Done():
			return
		case <-wake:
		case <-time.After(30 * time.Second):
			_, _ = w.Write([]byte(": keepalive\n\n"))
		}
	}
}

// openRepoPR handles POST /runs/:id/pr for repo runs.
func (a *Agent) openRepoPR(w http.ResponseWriter, r *http.Request, rr *repoRun) {
	var body struct {
		GitHubToken string `json:"github_token"`
	}
	_ = json.NewDecoder(r.Body).Decode(&body)
	if !rr.demo && body.GitHubToken == "" {
		writeJSON(w, 400, map[string]any{"detail": "github_token is required"})
		return
	}
	if !rr.solved {
		writeJSON(w, 400, map[string]any{"detail": "run is not solved"})
		return
	}
	writeJSON(w, 200, map[string]any{"url": rr.prURL, "number": rr.prNumber, "branch": rr.prBranch, "fake": true})
}
