package commands

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// repoBackend is a fake PatchLoop backend for the repo flow.
type repoBackend struct {
	t   *testing.T
	srv *httptest.Server

	mu            sync.Mutex
	solved        bool
	taskStatus    int // non-zero: POST /api/tasks answers this with taskBody
	taskBody      string
	taskReq       map[string]any
	statusPolls   atomic.Int32
	connectAfter  int32
	prAllowed     bool
	prReason      string
	merged        bool
	mergeReq      map[string]any
	followupMsg   string
	slackWebhook  string
	slackLinked   bool
	githubConnect bool
}

func newRepoBackend(t *testing.T) *repoBackend {
	b := &repoBackend{t: t, solved: true, prAllowed: true, connectAfter: 2, githubConnect: true}
	b.srv = httptest.NewServer(http.HandlerFunc(b.serve))
	t.Cleanup(b.srv.Close)
	return b
}

func writeBody(w http.ResponseWriter, status int, body string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = w.Write([]byte(body))
}

func (b *repoBackend) events(w http.ResponseWriter, id string) {
	w.Header().Set("Content-Type", "text/event-stream")
	fl := w.(http.Flusher)
	evs := []string{
		`{"type":"run_started","data":{"run_id":"a","bug_id":"octo/widgets","mode":"fake","engine":"graph"}}`,
		`{"type":"repo","data":{"full_name":"octo/widgets","branch":"main","files":14,"language":"python","test_command":"python -m unittest","truncated":false}}`,
		`{"type":"locate","data":{"files":[{"path":"src/app.py","reason":"defines paginate()"}]}}`,
		`{"type":"repro","data":{"path":"tests/test_repro.py","test_name":"test_last_page","failed_on_original":true,"output_tail":"x"}}`,
		`{"type":"round","data":{"depth":0}}`,
		`{"type":"node","data":{"id":1,"depth":1,"idea":"fix offset","passed":6,"total":6,"files":{"src/app.py":"x","src/b.py":"y"}}}`,
		fmt.Sprintf(`{"type":"done","data":{"solved":%v,"best":{"id":1,"passed":6,"total":6},"usage":{"prompt_tokens":10,"completion_tokens":5},"latency_ms":900}}`, b.solved),
	}
	if b.solved {
		evs = append(evs, `{"type":"pr","data":{"url":"https://github.com/octo/widgets/pull/43","number":43,"branch":"patchloop/x-1","fake":true,"updated":false}}`)
	}
	evs = append(evs, `{"type":"end"}`)
	for _, e := range evs {
		fmt.Fprintf(w, "data: %s\n\n", e)
		fl.Flush()
	}
}

func (b *repoBackend) serve(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path == "/health" {
		writeBody(w, 200, `{"status":"ok"}`)
		return
	}
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
	case p == "/api/github/status":
		n := b.statusPolls.Add(1)
		if b.githubConnect && n >= b.connectAfter {
			writeBody(w, 200, `{"connected":true,"mode":"app","login":"octo-owner","installationId":7,"appConfigured":true,"repoCount":2}`)
		} else {
			writeBody(w, 200, `{"connected":false,"mode":null,"login":"","appConfigured":true,"repoCount":0}`)
		}
	case p == "/api/github/connect":
		writeBody(w, 200, `{"url":"https://github.com/apps/patchloop/installations/new?state=abc"}`)
	case p == "/api/github/demo":
		writeBody(w, 200, `{"connected":true,"mode":"demo"}`)
	case p == "/api/github/repos":
		if r.URL.Query().Get("q") == "gadg" {
			writeBody(w, 200, `[{"fullName":"octo/gadgets","private":false,"defaultBranch":"trunk","description":"","language":"Go"}]`)
			return
		}
		writeBody(w, 200, `[{"fullName":"octo/widgets","private":true,"defaultBranch":"main","description":"Widgets","language":"Python"},{"fullName":"octo/gadgets","private":false,"defaultBranch":"trunk","description":"","language":"Go"}]`)
	case p == "/api/tasks" && r.Method == "POST":
		_ = json.NewDecoder(r.Body).Decode(&b.taskReq)
		if b.taskStatus != 0 {
			writeBody(w, b.taskStatus, b.taskBody)
			return
		}
		writeBody(w, 201, `{"runId":"r2","mode":"fake","engine":"graph","repo":"octo/widgets","branch":"main"}`)
	case p == "/api/runs/r2" && r.Method == "GET":
		pr := ""
		if b.solved {
			pr = "https://github.com/octo/widgets/pull/43"
		}
		writeBody(w, 200, fmt.Sprintf(`{"id":"r2","kind":"repo","repo":"octo/widgets","prUrl":%q,"prNumber":43,"latencyMs":4200,"cost":{"tokens":15},"solved":%v}`, pr, b.solved))
	case p == "/api/runs/r2/events" || p == "/api/runs/r3/events":
		b.mu.Unlock()
		b.events(w, p)
		b.mu.Lock()
	case p == "/api/runs/r2/pr" && r.Method == "GET":
		allowed := b.prAllowed
		writeBody(w, 200, fmt.Sprintf(`{"url":"https://github.com/octo/widgets/pull/43","number":43,"state":"open","mergeable":true,"checks":{"state":"success","failing":[]},"mergeAllowed":%v,"reason":%q}`, allowed, b.prReason))
	case p == "/api/runs/r2/merge":
		_ = json.NewDecoder(r.Body).Decode(&b.mergeReq)
		b.merged = true
		writeBody(w, 200, `{"merged":true,"url":"https://github.com/octo/widgets/pull/43","method":"squash","by":"octo-owner"}`)
	case p == "/api/runs/r2/followup":
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		b.followupMsg, _ = body["message"].(string)
		writeBody(w, 201, `{"runId":"r3","parentRunId":"r2"}`)
	case p == "/api/runs/r3":
		writeBody(w, 200, `{"id":"r3","kind":"repo","repo":"octo/widgets","prUrl":"https://github.com/octo/widgets/pull/43"}`)
	case p == "/api/settings/slack" && r.Method == "GET":
		writeBody(w, 200, fmt.Sprintf(`{"configured":%v,"webhookUrlMasked":%q,"linked":%v,"appConfigured":true}`, b.slackWebhook != "", "https://hooks.slack.com/…1234", b.slackLinked))
	case p == "/api/settings/slack" && r.Method == "PUT":
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		u, _ := body["webhookUrl"].(string)
		if !strings.HasPrefix(u, "https://hooks.slack.com/") {
			writeBody(w, 400, `{"error":"webhook must look like https://hooks.slack.com/services/...","code":"bad_request"}`)
			return
		}
		b.slackWebhook = u
		writeBody(w, 200, `{}`)
	case p == "/api/settings/slack" && r.Method == "DELETE":
		b.slackWebhook = ""
		writeBody(w, 200, `{}`)
	case p == "/api/settings/slack/test":
		writeBody(w, 200, `{"ok":true}`)
	case p == "/api/slack/link-code":
		writeBody(w, 201, `{"code":"ABCD2345","expiresAt":"2030-01-01T00:00:00Z","command":"/patchloop link ABCD2345"}`)
	default:
		writeBody(w, 404, `{"error":"no such endpoint","code":"not_found"}`)
	}
}

func setupCLI(t *testing.T, b *repoBackend) {
	t.Helper()
	t.Setenv("PATCHLOOP_CONFIG", filepath.Join(t.TempDir(), "config.json"))
	t.Setenv("NO_COLOR", "1")
	if _, _, err := run(t, "login", "--token", goodToken, "--api", b.srv.URL); err != nil {
		t.Fatal(err)
	}
}

func exitCode(err error) int {
	var ee *ExitError
	if errors.As(err, &ee) {
		return ee.Code
	}
	if err != nil {
		return -1
	}
	return 0
}

func TestFixRepoSolved(t *testing.T) {
	b := newRepoBackend(t)
	setupCLI(t, b)
	out, errOut, err := run(t, "fix", "--repo", "octo/widgets", "--branch", "main", "pagination", "returns", "the wrong last page")
	if err != nil {
		t.Fatalf("fix: %v\n%s\n%s", err, out, errOut)
	}
	if b.taskReq["repo"] != "octo/widgets" || b.taskReq["task"] != "pagination returns the wrong last page" ||
		b.taskReq["autoPr"] != true || b.taskReq["branch"] != "main" {
		t.Fatalf("task request: %v", b.taskReq)
	}
	for _, want := range []string{"⎇ repo octo/widgets@main", "14 files", "⌖ locate", "src/app.py", "✔ reproducer test_last_page", "── round 0 ──", "#1 [6/6] fix offset", "2 files", "✓ SOLVED", "⇪ PR #43 opened: https://github.com/octo/widgets/pull/43", "[fake mode]", "PR: https://github.com/octo/widgets/pull/43"} {
		if !strings.Contains(out, want) {
			t.Errorf("stdout lacks %q:\n%s", want, out)
		}
	}
	if strings.Contains(out, "\x1b[") {
		t.Error("colour codes with NO_COLOR")
	}
	if !strings.Contains(errOut, "run r2 started on octo/widgets@main") || !strings.Contains(errOut, "patchloop merge r2") || !strings.Contains(errOut, "cost: 15 tokens") {
		t.Errorf("stderr:\n%s", errOut)
	}
}

func TestFixRepoNoPRAndUnsolved(t *testing.T) {
	b := newRepoBackend(t)
	b.solved = false
	setupCLI(t, b)
	out, _, err := run(t, "fix", "--repo", "octo/widgets", "--no-pr", "hard bug")
	if exitCode(err) != 1 {
		t.Fatalf("unsolved must exit 1, got %v", err)
	}
	if b.taskReq["autoPr"] != false || !strings.Contains(out, "✗ NOT SOLVED") || strings.Contains(out, "PR:") {
		t.Fatalf("unsolved output (autoPr=%v):\n%s", b.taskReq["autoPr"], out)
	}
}

func TestFixRepoErrorsExitTwoWithHints(t *testing.T) {
	b := newRepoBackend(t)
	setupCLI(t, b)
	cases := []struct {
		name       string
		status     int
		body       string
		wantErr    string
		wantHint   string
		extraArgs  []string
		repo       string
		neverAsked bool
	}{
		{"not connected", 409, `{"error":"connect github first","code":"github_not_connected"}`, "connect github first", "patchloop connect github", nil, "octo/widgets", false},
		{"not granted", 403, `{"error":"that repository is not granted","code":"repo_not_granted"}`, "not granted", "Grant the repo", nil, "octo/widgets", false},
		{"rate limited", 429, `{"error":"task limit reached","code":"rate_limited","retryAfterSec":1200}`, "task limit", "21 minutes", nil, "octo/widgets", false},
		{"bad repo flag", 0, ``, "owner/name", "", nil, "not-a-repo", true},
	}
	for _, tc := range cases {
		b.taskStatus, b.taskBody, b.taskReq = tc.status, tc.body, nil
		_, errOut, err := run(t, "fix", "--repo", tc.repo, "something")
		if exitCode(err) != 2 {
			t.Errorf("%s: exit %d (%v)", tc.name, exitCode(err), err)
		}
		if !strings.Contains(errOut, tc.wantErr) || (tc.wantHint != "" && !strings.Contains(errOut, "hint: ") && !strings.Contains(errOut, tc.wantHint)) || !strings.Contains(errOut, tc.wantHint) {
			t.Errorf("%s: stderr %q", tc.name, errOut)
		}
		if tc.neverAsked && b.taskReq != nil {
			t.Errorf("%s: invalid repo reached the server", tc.name)
		}
	}
	// Bad token: friendly login hint.
	t.Setenv("PATCHLOOP_TOKEN", "")
	b.taskStatus = 0
}

func TestFixJSONEmitsRawEvents(t *testing.T) {
	b := newRepoBackend(t)
	setupCLI(t, b)
	out, _, err := run(t, "fix", "--repo", "octo/widgets", "--json", "bug")
	if err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimSpace(out), "\n")
	if len(lines) != 9 {
		t.Fatalf("want 9 raw events, got %d:\n%s", len(lines), out)
	}
	for _, l := range lines {
		if !json.Valid([]byte(l)) {
			t.Fatalf("not json: %q", l)
		}
	}
}

func TestWatchRepoRunUsesRepoView(t *testing.T) {
	b := newRepoBackend(t)
	setupCLI(t, b)
	out, _, err := run(t, "watch", "r2")
	if err != nil || !strings.Contains(out, "⌖ locate") {
		t.Fatalf("watch: %v\n%s", err, out)
	}
}

func TestConnectGitHubPollsUntilInstalled(t *testing.T) {
	b := newRepoBackend(t)
	setupCLI(t, b)
	pollEvery, pollTimeout = 5*time.Millisecond, 5*time.Second
	var opened string
	openURL = func(u string) error { opened = u; return nil }
	t.Cleanup(func() { pollEvery, pollTimeout, openURL = 2*time.Second, 5*time.Minute, openBrowser })

	b.statusPolls.Store(-100) // "not connected" for the pre-check and the first polls
	b.connectAfter = -97
	out, _, err := run(t, "connect", "github")
	if err != nil {
		t.Fatalf("connect: %v\n%s", err, out)
	}
	if !strings.Contains(out, "https://github.com/apps/patchloop/installations/new?state=abc") || opened == "" ||
		!strings.Contains(out, "Connected as octo-owner: 2 repositories") {
		t.Fatalf("connect output (opened=%q):\n%s", opened, out)
	}
	// --no-open prints the URL only.
	opened = ""
	b.statusPolls.Store(-100)
	if _, _, err := run(t, "connect", "github", "--no-open"); err != nil || opened != "" {
		t.Fatalf("no-open: %v opened=%q", err, opened)
	}
	// Demo account.
	out, _, err = run(t, "connect", "github", "--demo")
	if err != nil || !strings.Contains(out, "demo/shop-api") {
		t.Fatalf("demo: %v %s", err, out)
	}
	if _, _, err := run(t, "connect", "gitlab"); err == nil {
		t.Fatal("unknown provider accepted")
	}
}

func TestConnectGitHubTimesOut(t *testing.T) {
	b := newRepoBackend(t)
	b.githubConnect = false
	setupCLI(t, b)
	pollEvery, pollTimeout = 5*time.Millisecond, 60*time.Millisecond
	openURL = func(string) error { return nil }
	t.Cleanup(func() { pollEvery, pollTimeout, openURL = 2*time.Second, 5*time.Minute, openBrowser })
	_, errOut, err := run(t, "connect", "github")
	if exitCode(err) != 2 || !strings.Contains(errOut, "timed out") {
		t.Fatalf("timeout: %v %q", err, errOut)
	}
}

func TestRepos(t *testing.T) {
	b := newRepoBackend(t)
	setupCLI(t, b)
	out, _, err := run(t, "repos")
	if err != nil || !strings.Contains(out, "octo/widgets") || !strings.Contains(out, "private") || !strings.Contains(out, "trunk") {
		t.Fatalf("repos: %v\n%s", err, out)
	}
	out, _, _ = run(t, "repos", "--q", "gadg")
	if strings.Contains(out, "widgets") || !strings.Contains(out, "octo/gadgets") {
		t.Fatalf("filtered:\n%s", out)
	}
	out, _, _ = run(t, "repos", "--json")
	var rs []map[string]any
	if err := json.Unmarshal([]byte(out), &rs); err != nil || len(rs) != 2 {
		t.Fatalf("json: %v %s", err, out)
	}
}

func TestMerge(t *testing.T) {
	b := newRepoBackend(t)
	setupCLI(t, b)

	// Refused by the gate: exit 1 with the reason, nothing posted.
	b.prAllowed, b.prReason = false, "checks are failing: unit"
	_, errOut, err := run(t, "merge", "r2", "--yes")
	if exitCode(err) != 1 || !strings.Contains(errOut, "not merging: checks are failing: unit") || b.merged {
		t.Fatalf("refused: %v %q merged=%v", err, errOut, b.merged)
	}

	// Allowed but the user says no.
	b.prAllowed, b.prReason = true, ""
	root := NewRoot()
	var out, eb bytes.Buffer
	root.SetOut(&out)
	root.SetErr(&eb)
	root.SetIn(strings.NewReader("n\n"))
	root.SetArgs([]string{"merge", "r2"})
	apiFlag = ""
	if err := root.Execute(); exitCode(err) != 1 || b.merged || !strings.Contains(eb.String(), "cancelled") {
		t.Fatalf("declined: %v merged=%v %q", err, b.merged, eb.String())
	}
	if !strings.Contains(out.String(), "checks: success") {
		t.Fatalf("checks not shown: %s", out.String())
	}

	// Confirmed.
	root = NewRoot()
	out.Reset()
	eb.Reset()
	root.SetOut(&out)
	root.SetErr(&eb)
	root.SetIn(strings.NewReader("y\n"))
	root.SetArgs([]string{"merge", "r2", "--method", "rebase"})
	apiFlag = ""
	if err := root.Execute(); err != nil || !b.merged || b.mergeReq["method"] != "rebase" || !strings.Contains(out.String(), "Merged by octo-owner") {
		t.Fatalf("confirmed: %v merged=%v %v\n%s", err, b.merged, b.mergeReq, out.String())
	}

	// --yes --json
	b.merged = false
	o, _, err := run(t, "merge", "r2", "--yes", "--json")
	if err != nil || !b.merged || !strings.Contains(o, `"merged": true`) {
		t.Fatalf("yes/json: %v %s", err, o)
	}
}

func TestChangesStreamsFollowup(t *testing.T) {
	b := newRepoBackend(t)
	setupCLI(t, b)
	out, errOut, err := run(t, "changes", "r2", "also", "handle", "page", "zero")
	if err != nil || b.followupMsg != "also handle page zero" || !strings.Contains(out, "⇪ PR") || !strings.Contains(errOut, "follow-up run r3 started") {
		t.Fatalf("changes: %v %q\n%s\n%s", err, b.followupMsg, out, errOut)
	}
	if _, _, err := run(t, "changes", "r2"); err == nil {
		t.Fatal("missing message accepted")
	}
}

func TestSlackCommands(t *testing.T) {
	b := newRepoBackend(t)
	setupCLI(t, b)
	out, _, err := run(t, "slack", "link")
	if err != nil || !strings.Contains(out, "/patchloop link ABCD2345") {
		t.Fatalf("link: %v %s", err, out)
	}
	if _, errOut, err := run(t, "slack", "set", "https://evil.example.com/x"); exitCode(err) != 2 || !strings.Contains(errOut, "hooks.slack.com") {
		t.Fatalf("bad webhook: %v %q", err, errOut)
	}
	if _, _, err := run(t, "slack", "set", "https://hooks.slack.com/services/T0/B0/xxxx1234"); err != nil || b.slackWebhook == "" {
		t.Fatalf("set: %v", err)
	}
	if out, _, err := run(t, "slack", "test"); err != nil || !strings.Contains(out, "Test message sent") {
		t.Fatalf("test: %v %s", err, out)
	}
	if _, _, err := run(t, "slack", "clear"); err != nil || b.slackWebhook != "" {
		t.Fatalf("clear: %v", err)
	}
}

func TestStatusAndDoctor(t *testing.T) {
	b := newRepoBackend(t)
	setupCLI(t, b)
	b.statusPolls.Store(100)
	out, _, err := run(t, "status")
	if err != nil || !strings.Contains(out, "reachable") || !strings.Contains(out, "connected as octo-owner (app), 2 repos") || !strings.Contains(out, "account linked: false") {
		t.Fatalf("status: %v\n%s", err, out)
	}
	out, _, _ = run(t, "status", "--json")
	var st map[string]any
	if err := json.Unmarshal([]byte(out), &st); err != nil || st["apiReachable"] != true {
		t.Fatalf("status json: %v %s", err, out)
	}

	out, _, err = run(t, "doctor")
	if err != nil {
		t.Fatalf("doctor: %v\n%s", err, out)
	}
	for _, want := range []string{"✓ API reachable", "✓ Logged in", "✓ GitHub", "! Slack", "patchloop slack link"} {
		if !strings.Contains(out, want) {
			t.Errorf("doctor lacks %q:\n%s", want, out)
		}
	}

	// GitHub not connected: failing check with a fix, exit 1.
	b.githubConnect = false
	out, _, err = run(t, "doctor")
	if exitCode(err) != 1 || !strings.Contains(out, "✗ GitHub") || !strings.Contains(out, "patchloop connect github") {
		t.Fatalf("doctor failing: %v\n%s", err, out)
	}

	// Server down.
	t.Setenv("PATCHLOOP_API", "http://127.0.0.1:1")
	out, _, err = run(t, "doctor")
	if exitCode(err) != 1 || !strings.Contains(out, "✗ API reachable") {
		t.Fatalf("doctor offline: %v\n%s", err, out)
	}
	// Not logged in at all.
	t.Setenv("PATCHLOOP_CONFIG", filepath.Join(t.TempDir(), "none.json"))
	t.Setenv("PATCHLOOP_API", b.srv.URL)
	out, _, err = run(t, "doctor")
	if exitCode(err) != 1 || !strings.Contains(out, "✗ Logged in") || !strings.Contains(out, "patchloop login") {
		t.Fatalf("doctor logged out: %v\n%s", err, out)
	}
}

func TestRunsShowsRepoRunsAndCompletionExists(t *testing.T) {
	b := newRepoBackend(t)
	setupCLI(t, b)
	out, _, err := run(t, "completion", "bash")
	if err != nil || !strings.Contains(out, "patchloop") {
		t.Fatalf("completion: %v", err)
	}
	for _, sub := range []string{"connect", "repos", "merge", "changes", "slack", "status", "doctor", "fix", "pr", "watch", "runs"} {
		if _, _, err := run(t, sub, "--help"); err != nil {
			t.Errorf("%s --help: %v", sub, err)
		}
	}
}

func TestPRStatus(t *testing.T) {
	b := newRepoBackend(t)
	setupCLI(t, b)
	out, _, err := run(t, "pr", "r2", "--status")
	if err != nil || !strings.Contains(out, "PR #43") || !strings.Contains(out, "patchloop merge r2") {
		t.Fatalf("pr --status: %v\n%s", err, out)
	}
	b.prAllowed, b.prReason = false, "checks are still running"
	out, _, _ = run(t, "pr", "r2", "--status")
	if !strings.Contains(out, "not mergeable yet: checks are still running") {
		t.Fatalf("pr --status refused:\n%s", out)
	}
}
