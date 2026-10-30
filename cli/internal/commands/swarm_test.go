package commands

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

// swarmBackend is a fake PatchLoop backend that streams swarm runs.
type swarmBackend struct {
	t   *testing.T
	srv *httptest.Server

	mu         sync.Mutex
	scenario   string // complete | partial | failed | needs_input | blocked
	taskReq    map[string]any
	answerReq  map[string]any
	answerRuns int
	downloads  []string
}

func newSwarmBackend(t *testing.T, scenario string) *swarmBackend {
	b := &swarmBackend{t: t, scenario: scenario}
	b.srv = httptest.NewServer(http.HandlerFunc(b.serve))
	t.Cleanup(b.srv.Close)
	return b
}

const planEv = `{"type":"plan","data":{"task_type":"ui","task_type_source":"auto","summary":"ui task: 2 units, 2 hard gates",` +
	`"criteria":[{"id":"build","kind":"build","hard":true,"description":"build succeeds","verifier":"npm run build"},` +
	`{"id":"ui_overflow","kind":"ui_overflow","hard":true,"description":"no horizontal overflow","verifier":"playwright"},` +
	`{"id":"vision_rubric","kind":"vision","hard":false,"description":"looks better","verifier":"rubric"}],` +
	`"units":[{"id":"u1","title":"Responsive header","scope_files":["Header.css"],"depends_on":[],"variants":2,"role":"worker"},` +
	`{"id":"u2","title":"Fluid grid","scope_files":["grid.css"],"depends_on":["u1"],"variants":1,"role":"worker"}],` +
	`"swarm":{"max_parallel":3,"workers_planned":3,"limits":{}}}}`

func verifyEv(round int, ok bool) string {
	st, hp := "pass", "true"
	if !ok {
		st, hp = "fail", "false"
	}
	return fmt.Sprintf(`{"type":"verify","data":{"round":%d,"results":[`+
		`{"criterion_id":"build","kind":"build","hard":true,"status":"pass","detail":"build ok","artifacts":[]},`+
		`{"criterion_id":"ui_overflow","kind":"ui_overflow","hard":true,"status":%q,"detail":"overflow at 375px","artifacts":["shot-after-375"]},`+
		`{"criterion_id":"vision_rubric","kind":"vision","hard":false,"status":"advisory","score":0.82,"detail":"clearly better","artifacts":[]}],`+
		`"hard_pass":%s,"summary":{"pass":1,"fail":0,"skip":0,"advisory":1}}}`, round, st, hp)
}

func (b *swarmBackend) events() []string {
	evs := []string{
		`{"type":"run_started","data":{"run_id":"a","bug_id":"octo/widgets","mode":"fake","engine":"graph","kind":"repo"}}`,
		`{"type":"repo","data":{"full_name":"octo/widgets","branch":"main","files":14,"language":"javascript","test_command":"npm test","truncated":false}}`,
	}
	if b.scenario == "needs_input" {
		return append(evs,
			`{"type":"clarify","data":{"questions":[{"id":"q1","text":"Which page?"},{"id":"q2","text":"What is done?"}]}}`,
			`{"type":"done","data":{"solved":false,"outcome":"needs_input","task_type":"auto","usage":{"prompt_tokens":10,"completion_tokens":5},"latency_ms":500,"agents":{"spawned":1,"peak_parallel":1}}}`,
			`{"type":"end"}`)
	}
	evs = append(evs, planEv,
		`{"type":"agent","data":{"id":"planner","role":"planner","unit_id":null,"variant":null,"status":"done","model":"super","isolation":"local","summary":"plan ready"}}`,
		`{"type":"unit","data":{"id":"u1","status":"running","files":["Header.css"]}}`,
		`{"type":"agent","data":{"id":"u1-v1","role":"worker","unit_id":"u1","variant":1,"status":"running","model":"nano","isolation":"local"}}`,
		`{"type":"agent","data":{"id":"u1-v2","role":"worker","unit_id":"u1","variant":2,"status":"running","model":"nano","isolation":"local"}}`,
		`{"type":"tool","data":{"agent_id":"u1-v1","name":"write_file","target":"Header.css","ok":true,"ms":12}}`,
		`{"type":"budget","data":{"tokens_used":1200,"tokens_limit":2000000,"wall_s":3,"wall_limit_s":3600,"workers_active":2}}`,
		`{"type":"agent","data":{"id":"u1-v1","role":"worker","unit_id":"u1","variant":1,"status":"done","model":"nano","isolation":"local","summary":"checks pass"}}`,
		`{"type":"agent","data":{"id":"u1-v2","role":"worker","unit_id":"u1","variant":2,"status":"cancelled","model":"nano","isolation":"local"}}`,
		`{"type":"unit","data":{"id":"u1","status":"passed","winner_variant":1,"files":["Header.css"]}}`,
		`{"type":"merge","data":{"status":"ok","units":["u1"],"conflicts":[]}}`,
		`{"type":"artifact","data":{"id":"shot-after-375","kind":"screenshot","label":"after","phase":"after","viewport":"375","mime":"image/png"}}`,
	)
	ok := b.scenario == "complete" || b.scenario == "partial"
	if b.scenario == "failed" {
		evs = append(evs, verifyEv(1, false), verifyEv(2, false))
	} else if ok {
		evs = append(evs, verifyEv(1, false), `{"type":"unit","data":{"id":"r1","status":"passed","winner_variant":1,"files":["Header.css"]}}`, verifyEv(2, true))
	} else {
		evs = append(evs, verifyEv(1, false))
	}
	outcome := map[string]string{"complete": "complete", "partial": "partial", "failed": "failed", "blocked": "blocked"}[b.scenario]
	hp := 2
	if !ok {
		hp = 1
	}
	evs = append(evs, fmt.Sprintf(`{"type":"done","data":{"solved":%v,"outcome":%q,"task_type":"ui","criteria":{"hard_pass":%d,"hard_total":2,"advisory":[{"criterion_id":"vision_rubric","score":0.82,"detail":"clearly better"}]},`+
		`"usage":{"prompt_tokens":300,"completion_tokens":100},"latency_ms":4200,"agents":{"spawned":5,"peak_parallel":3}}}`, outcome == "complete", outcome, hp))
	if ok {
		evs = append(evs, `{"type":"pr","data":{"url":"https://github.com/octo/widgets/pull/43","number":43,"branch":"patchloop/x","fake":true,"updated":false,"commits":2}}`)
	}
	return append(evs, `{"type":"end"}`)
}

func (b *swarmBackend) serve(w http.ResponseWriter, r *http.Request) {
	if r.Header.Get("Authorization") != "Bearer "+goodToken {
		writeBody(w, 401, `{"error":"invalid or revoked api token","code":"unauthorized"}`)
		return
	}
	b.mu.Lock()
	defer b.mu.Unlock()
	p := r.URL.Path
	switch {
	case p == "/api/auth/me":
		writeBody(w, 200, `{"user":{"id":"u1","email":"dev@example.com","companyName":"Acme"}}`)
	case p == "/api/tasks" && r.Method == "POST":
		_ = json.NewDecoder(r.Body).Decode(&b.taskReq)
		writeBody(w, 201, `{"runId":"s1","mode":"fake","engine":"graph","repo":"octo/widgets","branch":"main","taskType":"ui","limits":{"maxWorkers":4,"maxTokens":100000},"limitsClamped":true}`)
	case p == "/api/runs/s1/events" || p == "/api/runs/s2/events":
		w.Header().Set("Content-Type", "text/event-stream")
		fl := w.(http.Flusher)
		for _, e := range b.events() {
			fmt.Fprintf(w, "data: %s\n\n", e)
			fl.Flush()
		}
	case p == "/api/runs/s1" || p == "/api/runs/s2":
		pr := ""
		if b.scenario == "complete" || b.scenario == "partial" {
			pr = "https://github.com/octo/widgets/pull/43"
		}
		qs := "[]"
		if b.scenario == "needs_input" {
			qs = `[{"id":"q1","text":"Which page?"},{"id":"q2","text":"What is done?"}]`
		}
		writeBody(w, 200, fmt.Sprintf(`{"id":%q,"kind":"repo","repo":"octo/widgets","outcome":%q,"taskType":"ui","prUrl":%q,"cost":{"tokens":400},"latencyMs":4200,`+
			`"questions":%s,"artifacts":[{"id":"shot-after-375","mime":"image/png","kind":"screenshot"}]}`, strings.TrimPrefix(p, "/api/runs/"), b.scenario, pr, qs))
	case p == "/api/runs/s1/answers" && r.Method == "POST":
		_ = json.NewDecoder(r.Body).Decode(&b.answerReq)
		b.answerRuns++
		b.scenario = "complete" // the child run completes
		writeBody(w, 201, `{"runId":"s2","parentRunId":"s1"}`)
	case p == "/api/runs/s1/artifacts":
		writeBody(w, 200, `[{"id":"shot-after-375","kind":"screenshot","label":"After (375px)","phase":"after","viewport":"375","mime":"image/png","size":8},`+
			`{"id":"../../evil","kind":"log","label":"bad id","phase":"n/a","mime":"text/plain","size":1},`+
			`{"id":"build-log","kind":"log","label":"build","phase":"n/a","mime":"text/plain","size":5}]`)
	case strings.HasPrefix(p, "/api/runs/s1/artifacts/"):
		id := strings.TrimPrefix(p, "/api/runs/s1/artifacts/")
		b.downloads = append(b.downloads, id)
		if id == "shot-after-375" {
			w.Header().Set("Content-Type", "image/png")
			_, _ = w.Write([]byte("\x89PNG\r\n\x1a\n"))
			return
		}
		_, _ = w.Write([]byte("hello"))
	case p == "/api/runs/s1/pr":
		writeBody(w, 200, `{"url":"https://github.com/octo/widgets/pull/43","number":43,"state":"open","mergeable":true,"checks":{"state":"success","failing":[]},"mergeAllowed":true,"reason":"","warning":"partial result: review carefully"}`)
	case p == "/api/runs":
		writeBody(w, 200, `[{"id":"s1","kind":"repo","repo":"octo/widgets","source":"cli","mode":"fake","status":"completed","outcome":"partial","taskType":"ui","createdAt":"2030-01-01T10:00:00Z","prUrl":"https://x/pull/1"},`+
			`{"id":"old","kind":"repo","repo":"octo/old","source":"web","mode":"fake","status":"completed","solved":true,"createdAt":"2029-01-01T10:00:00Z"}]`)
	default:
		writeBody(w, 404, `{"error":"no such endpoint","code":"not_found"}`)
	}
}

func setupSwarm(t *testing.T, scenario string) *swarmBackend {
	b := newSwarmBackend(t, scenario)
	t.Setenv("PATCHLOOP_CONFIG", filepath.Join(t.TempDir(), "config.json"))
	t.Setenv("NO_COLOR", "1")
	if _, _, err := run(t, "login", "--token", goodToken, "--api", b.srv.URL); err != nil {
		t.Fatal(err)
	}
	return b
}

func TestDoSwarmCompleteOutputAndRequest(t *testing.T) {
	b := setupSwarm(t, "complete")
	out, errOut, err := run(t, "do", "--repo", "octo/widgets", "--type", "UI", "--strict", "vision_rubric,secrets",
		"--limits", "workers=9,tokens=500000,wall=600", "--branch", "main", "make", "the", "header", "responsive")
	if err != nil {
		t.Fatalf("do: %v\n%s\n%s", err, out, errOut)
	}
	if b.taskReq["taskType"] != "ui" || b.taskReq["task"] != "make the header responsive" || b.taskReq["autoPr"] != true {
		t.Fatalf("request: %v", b.taskReq)
	}
	strict := b.taskReq["strict"].([]any)
	lim := b.taskReq["limits"].(map[string]any)
	if len(strict) != 2 || strict[0] != "vision_rubric" || lim["maxWorkers"] != float64(9) || lim["maxTokens"] != float64(500000) || lim["maxWallS"] != float64(600) {
		t.Fatalf("strict/limits: %v %v", strict, lim)
	}
	for _, want := range []string{
		"plan: ui task (auto) - 2 units, 2 hard + 1 advisory criteria, up to 3 agents in parallel",
		"criterion [hard] ui_overflow: no horizontal overflow", "criterion [advisory] vision_rubric",
		"unit u2: Fluid grid (after u1)",
		"agent u1-v1 (worker) running", "agent u1-v2 (worker) cancelled",
		"unit u1 passed (variant 1 won)", "merge ok (u1)", "artifact shot-after-375 (screenshot, after, 375px)",
		"verify round 1: 1/2 hard gates pass", "fail     ui_overflow: overflow at 375px", "advisory vision_rubric 0.82: clearly better",
		"verify round 2: 2/2 hard gates pass",
		"✓ COMPLETE  2/2 hard gates pass", "◇ advisory vision_rubric 0.82", "5 agents (peak 3 in parallel)",
		"⇪ PR #43 opened (2 commits",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("stdout lacks %q:\n%s", want, out)
		}
	}
	if strings.Contains(out, "\x1b[") || strings.Contains(out, "write_file") {
		t.Errorf("plain mode must have no escape codes and no tool chatter:\n%s", out)
	}
	lines := strings.Split(strings.TrimSpace(out), "\n")
	if lines[len(lines)-1] != "PR: https://github.com/octo/widgets/pull/43" {
		t.Errorf("the PR url must be the last stdout line, got %q", lines[len(lines)-1])
	}
	if !strings.Contains(errOut, "limits were clamped by the server to workers=4 tokens=100000") || !strings.Contains(errOut, "1 artifacts") || !strings.Contains(errOut, "patchloop merge s1") {
		t.Errorf("stderr:\n%s", errOut)
	}
}

func TestExitCodesByOutcome(t *testing.T) {
	for _, tc := range []struct {
		scenario string
		code     int
		want     string
	}{
		{"complete", 0, "✓ COMPLETE"},
		{"partial", 3, "◐ PARTIAL"},
		{"failed", 1, "✗ FAILED"},
		{"blocked", 1, "⊘ BLOCKED"},
		{"needs_input", 4, "? NEEDS INPUT"},
	} {
		setupSwarm(t, tc.scenario)
		out, errOut, err := run(t, "do", "--repo", "octo/widgets", "something")
		if exitCode(err) != tc.code || !strings.Contains(out, tc.want) {
			t.Errorf("%s: exit %d (want %d), output:\n%s\n%s", tc.scenario, exitCode(err), tc.code, out, errOut)
		}
		if tc.scenario == "partial" && !strings.Contains(errOut, "partial result") {
			t.Errorf("partial hint missing: %s", errOut)
		}
		if tc.scenario == "needs_input" && (!strings.Contains(out, "1. [q1] Which page?") || !strings.Contains(out, "patchloop answer s1")) {
			t.Errorf("needs_input must print the questions and the answer command:\n%s", out)
		}
		if tc.scenario == "failed" && strings.Contains(out, "PR:") {
			t.Errorf("failed run printed a PR:\n%s", out)
		}
	}
}

func TestDoRequiresRepoAndValidatesFlags(t *testing.T) {
	b := setupSwarm(t, "complete")
	for _, args := range [][]string{
		{"do", "no repo"},
		{"do", "--repo", "octo/widgets", "--type", "wizardry", "x"},
		{"do", "--repo", "octo/widgets", "--limits", "workers=-1", "x"},
		{"do", "--repo", "octo/widgets", "--limits", "bogus=1", "x"},
		{"do", "--repo", "octo/widgets", "--limits", "workers", "x"},
		{"fix", "--type", "ui", "cart"},
	} {
		if _, _, err := run(t, args...); err == nil {
			t.Errorf("%v accepted", args)
		}
	}
	if b.taskReq != nil {
		t.Fatalf("invalid flags reached the server: %v", b.taskReq)
	}
	// fix keeps working with --repo and defaults the type to the server's (auto): none sent.
	if _, _, err := run(t, "fix", "--repo", "octo/widgets", "x"); err != nil {
		t.Fatal(err)
	}
	if _, has := b.taskReq["taskType"]; has {
		t.Errorf("fix must not send a task type by default: %v", b.taskReq)
	}
}

func TestDoJSONKeepsRawEventsAndExitCode(t *testing.T) {
	setupSwarm(t, "partial")
	out, _, err := run(t, "do", "--repo", "octo/widgets", "--json", "x")
	if exitCode(err) != 3 {
		t.Fatalf("exit %d", exitCode(err))
	}
	lines := strings.Split(strings.TrimSpace(out), "\n")
	types := map[string]bool{}
	for _, l := range lines {
		var ev struct{ Type string }
		if json.Unmarshal([]byte(l), &ev) != nil {
			t.Fatalf("not json: %q", l)
		}
		types[ev.Type] = true
	}
	for _, want := range []string{"plan", "agent", "tool", "unit", "merge", "verify", "artifact", "budget", "done", "pr"} {
		if !types[want] {
			t.Errorf("raw event %q missing", want)
		}
	}
}

func TestAnswerRerunsAndExits(t *testing.T) {
	b := setupSwarm(t, "needs_input")
	out, _, err := run(t, "answer", "s1", "1: the cart module\n2: totals include shipping")
	if err != nil {
		t.Fatalf("answer: %v\n%s", err, out)
	}
	a := b.answerReq["answers"].(map[string]any)
	if a["q1"] != "the cart module" || a["q2"] != "totals include shipping" || b.answerRuns != 1 {
		t.Fatalf("answers: %v", b.answerReq)
	}
	if !strings.Contains(out, "✓ COMPLETE") {
		t.Fatalf("child run output:\n%s", out)
	}

	// --set and plain text.
	b.scenario = "needs_input"
	if _, _, err := run(t, "answer", "s1", "--set", "q2=done means green", "just the cart"); err != nil {
		t.Fatal(err)
	}
	a = b.answerReq["answers"].(map[string]any)
	if a["q1"] != "just the cart" || a["q2"] != "done means green" {
		t.Fatalf("mixed answers: %v", a)
	}
	if _, _, err := run(t, "answer", "s1"); err == nil {
		t.Fatal("answer without text accepted")
	}
}

func TestArtifactsListAndSaveAreSafe(t *testing.T) {
	b := setupSwarm(t, "complete")
	out, _, err := run(t, "artifacts", "s1")
	if err != nil || !strings.Contains(out, "shot-after-375") || !strings.Contains(out, "image/png") {
		t.Fatalf("list: %v\n%s", err, out)
	}
	dir := filepath.Join(t.TempDir(), "out")
	out, errOut, err := run(t, "artifacts", "s1", "--save", dir)
	if err != nil {
		t.Fatalf("save: %v\n%s", err, errOut)
	}
	if !strings.Contains(out, "Saved 2 artifacts") || !strings.Contains(errOut, `unsafe id "../../evil"`) {
		t.Fatalf("save output:\n%s\n%s", out, errOut)
	}
	for _, f := range []string{"shot-after-375.png", "build-log.txt"} {
		if _, err := os.Stat(filepath.Join(dir, f)); err != nil {
			t.Errorf("missing %s: %v", f, err)
		}
	}
	for _, d := range b.downloads {
		if strings.Contains(d, "..") {
			t.Fatalf("an unsafe id was requested: %q", d)
		}
	}
	entries, _ := os.ReadDir(filepath.Dir(dir))
	if len(entries) != 1 {
		t.Errorf("files were written outside the target directory: %v", entries)
	}
	out, _, err = run(t, "artifacts", "s1", "--json")
	var arts []map[string]any
	if err != nil || json.Unmarshal([]byte(out), &arts) != nil || len(arts) != 3 {
		t.Fatalf("json: %v %s", err, out)
	}
}

func TestRunsAndPRStatusAreOutcomeAware(t *testing.T) {
	setupSwarm(t, "partial")
	out, _, err := run(t, "runs")
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"TYPE", "OUTCOME", "ui", "partial", "complete"} {
		if !strings.Contains(out, want) {
			t.Errorf("runs lacks %q:\n%s", want, out)
		}
	}
	out, _, err = run(t, "pr", "s1", "--status")
	if err != nil || !strings.Contains(out, "warning: partial result") {
		t.Fatalf("pr status: %v\n%s", err, out)
	}
}

func TestParseLimitsAndAnswers(t *testing.T) {
	l, err := parseLimits("workers=4, tokens=1000 ,wall=60")
	if err != nil || l.MaxWorkers != 4 || l.MaxTokens != 1000 || l.MaxWallS != 60 {
		t.Fatalf("%+v %v", l, err)
	}
	if l, err := parseLimits(""); l != nil || err != nil {
		t.Fatal("empty limits")
	}
	got := parseAnswers(nil, "hello")
	if got["q1"] != "hello" {
		t.Fatalf("no questions: %v", got)
	}
}
