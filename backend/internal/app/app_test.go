package app_test

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/cookiejar"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"patchloop-backend/internal/app"
	"patchloop-backend/internal/config"
	"patchloop-backend/internal/db"
	"patchloop-backend/internal/fakeagent"

	"github.com/gin-gonic/gin"
	"go.mongodb.org/mongo-driver/v2/mongo"
	"go.mongodb.org/mongo-driver/v2/mongo/options"
)

const (
	testDB     = "patchloop_backend_test"
	testSecret = "test-agent-secret"
)

var (
	mongoOnce sync.Once
	mongoDB   *mongo.Database
	mongoErr  error
	emailSeq  atomic.Int64
)

// testDatabase connects once and resets only this package's own test DB.
func testDatabase(t *testing.T) *mongo.Database {
	t.Helper()
	mongoOnce.Do(func() {
		ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		defer cancel()
		client, err := mongo.Connect(options.Client().ApplyURI("mongodb://localhost:27017"))
		if err != nil {
			mongoErr = err
			return
		}
		if err := client.Ping(ctx, nil); err != nil {
			mongoErr = err
			return
		}
		mongoDB = client.Database(testDB)
		_ = mongoDB.Drop(ctx)
		mongoErr = db.EnsureIndexes(ctx, mongoDB)
	})
	if mongoErr != nil {
		t.Skipf("mongo not available: %v", mongoErr)
	}
	return mongoDB
}

type slackSink struct {
	mu       sync.Mutex
	payloads []map[string]any
	got      chan struct{}
}

type env struct {
	t       *testing.T
	backend *httptest.Server
	agentSv *httptest.Server
	agent   *fakeagent.Agent
	slack   *slackSink
	cfg     *config.Config
}

func newEnv(t *testing.T, mutate func(*config.Config)) *env {
	t.Helper()
	gin.SetMode(gin.TestMode)
	database := testDatabase(t)

	agent := fakeagent.New(fakeagent.Options{Secret: testSecret, Delay: 150 * time.Millisecond})
	agentSv := httptest.NewServer(agent)
	t.Cleanup(agentSv.Close)

	sink := &slackSink{got: make(chan struct{}, 10)}
	slackSv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var p map[string]any
		_ = json.NewDecoder(r.Body).Decode(&p)
		sink.mu.Lock()
		sink.payloads = append(sink.payloads, p)
		sink.mu.Unlock()
		sink.got <- struct{}{}
		_, _ = w.Write([]byte("ok"))
	}))
	t.Cleanup(slackSv.Close)

	cfg := &config.Config{
		JWTAccessSecret:       "access-secret-for-tests",
		JWTRefreshSecret:      "refresh-secret-for-tests",
		JWTAccessTTLMin:       15,
		JWTRefreshTTLDays:     30,
		ResendFromEmail:       "noreply@test",
		FrontendOrigin:        "http://localhost:3000",
		OTPTTLMin:             10,
		CookieDomain:          "",
		AgentURL:              agentSv.URL,
		AgentSharedSecret:     testSecret,
		SlackWebhookURL:       slackSv.URL,
		PublicAppURL:          "http://app.test",
		LiveRunsPerUserPerDay: 10,
		GuestRunsPerHour:      3,
		DevMode:               true,
	}
	if mutate != nil {
		mutate(cfg)
	}
	a := app.New(cfg, database, nil)
	backend := httptest.NewServer(a.Router)
	t.Cleanup(backend.Close)
	agent.SetCallbackURL(backend.URL)
	return &env{t: t, backend: backend, agentSv: agentSv, agent: agent, slack: sink, cfg: cfg}
}

func (e *env) do(client *http.Client, method, path string, body any, hdr map[string]string) (int, map[string]any, []byte) {
	e.t.Helper()
	var rdr io.Reader
	if body != nil {
		b, _ := json.Marshal(body)
		rdr = bytes.NewReader(b)
	}
	req, _ := http.NewRequest(method, e.backend.URL+path, rdr)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	for k, v := range hdr {
		req.Header.Set(k, v)
	}
	if client == nil {
		client = http.DefaultClient
	}
	resp, err := client.Do(req)
	if err != nil {
		e.t.Fatalf("%s %s: %v", method, path, err)
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	var m map[string]any
	_ = json.Unmarshal(raw, &m)
	return resp.StatusCode, m, raw
}

// newUser signs up in DEV_MODE, reads the OTP from /internal/dev/otp,
// verifies it and returns a client holding the auth cookies.
func (e *env) newUser() (*http.Client, string) {
	e.t.Helper()
	jar, _ := cookiejar.New(nil)
	client := &http.Client{Jar: jar}
	email := fmt.Sprintf("user%d-%d@example.com", time.Now().UnixNano(), emailSeq.Add(1))
	st, _, raw := e.do(client, "POST", "/api/auth/signup", map[string]any{"email": email, "password": "password123", "companyName": "Acme"}, nil)
	if st != 201 {
		e.t.Fatalf("signup: %d %s", st, raw)
	}
	st, otp, raw := e.do(nil, "GET", "/internal/dev/otp?email="+email, nil, map[string]string{"X-Agent-Secret": testSecret})
	if st != 200 {
		e.t.Fatalf("dev otp: %d %s", st, raw)
	}
	st, _, raw = e.do(client, "POST", "/api/auth/verify-otp", map[string]any{"email": email, "code": otp["code"]}, nil)
	if st != 200 {
		e.t.Fatalf("verify: %d %s", st, raw)
	}
	return client, email
}

type sseEvent struct {
	Type string         `json:"type"`
	Data map[string]any `json:"data"`
	At   time.Time      `json:"-"`
}

func readSSE(t *testing.T, client *http.Client, url string, hdr map[string]string, timeout time.Duration) ([]sseEvent, *http.Response) {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, "GET", url, nil)
	for k, v := range hdr {
		req.Header.Set(k, v)
	}
	if client == nil {
		client = http.DefaultClient
	}
	resp, err := client.Do(req)
	if err != nil {
		t.Fatalf("sse connect: %v", err)
	}
	defer resp.Body.Close()
	var events []sseEvent
	sc := bufio.NewScanner(resp.Body)
	sc.Buffer(make([]byte, 1<<20), 1<<22)
	for sc.Scan() {
		line := sc.Text()
		if !strings.HasPrefix(line, "data:") {
			continue
		}
		var ev sseEvent
		if err := json.Unmarshal([]byte(strings.TrimSpace(strings.TrimPrefix(line, "data:"))), &ev); err != nil {
			continue // a half-written event from a crashed agent
		}
		ev.At = time.Now()
		events = append(events, ev)
		if ev.Type == "end" {
			break
		}
	}
	return events, resp
}

func TestAuthAndAPITokens(t *testing.T) {
	e := newEnv(t, nil)
	client, email := e.newUser()

	st, me, _ := e.do(client, "GET", "/api/auth/me", nil, nil)
	if st != 200 || me["user"].(map[string]any)["email"] != email {
		t.Fatalf("me with cookie: %d %v", st, me)
	}
	st, _, _ = e.do(nil, "GET", "/api/auth/me", nil, nil)
	if st != 401 {
		t.Fatalf("me without auth: %d", st)
	}

	st, tok, raw := e.do(client, "POST", "/api/tokens", map[string]any{"name": "laptop"}, nil)
	if st != 201 {
		t.Fatalf("create token: %d %s", st, raw)
	}
	plain, _ := tok["token"].(string)
	if !strings.HasPrefix(plain, "plk_") {
		t.Fatalf("token prefix: %q", plain)
	}
	bearer := map[string]string{"Authorization": "Bearer " + plain}
	st, me, _ = e.do(nil, "GET", "/api/auth/me", nil, bearer)
	if st != 200 || me["user"].(map[string]any)["email"] != email {
		t.Fatalf("me with bearer: %d %v", st, me)
	}

	st, _, raw = e.do(nil, "GET", "/api/tokens", nil, bearer)
	if st != 200 || strings.Contains(string(raw), plain) || strings.Contains(string(raw), "hash") {
		t.Fatalf("list tokens leaked secret or failed: %d %s", st, raw)
	}

	for _, bad := range []string{"Bearer plk_wrongwrongwrongwrongwrong", "Bearer nope", "Basic abc"} {
		st, _, _ = e.do(nil, "GET", "/api/auth/me", nil, map[string]string{"Authorization": bad})
		if st != 401 {
			t.Fatalf("bad auth %q: %d", bad, st)
		}
	}

	st, _, _ = e.do(client, "DELETE", "/api/tokens/"+tok["id"].(string), nil, nil)
	if st != 200 {
		t.Fatalf("delete token: %d", st)
	}
	st, _, _ = e.do(nil, "GET", "/api/auth/me", nil, bearer)
	if st != 401 {
		t.Fatalf("revoked token still works: %d", st)
	}

	// Dev OTP endpoint requires the agent secret.
	st, _, _ = e.do(nil, "GET", "/internal/dev/otp?email="+email, nil, nil)
	if st != 401 {
		t.Fatalf("dev otp without secret: %d", st)
	}
}

func TestDevOTPRouteAbsentWithoutDevMode(t *testing.T) {
	e := newEnv(t, func(c *config.Config) { c.DevMode = false })
	st, _, _ := e.do(nil, "GET", "/internal/dev/otp?email=a@b.c", nil, map[string]string{"X-Agent-Secret": testSecret})
	if st != 404 {
		t.Fatalf("dev otp route should not exist: %d", st)
	}
}

func TestRunStreamsIncrementallyAndCompletes(t *testing.T) {
	e := newEnv(t, nil)
	client, _ := e.newUser()

	st, created, raw := e.do(client, "POST", "/api/runs", map[string]any{"bugId": "cart", "engine": "graph"}, map[string]string{
		"traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
	})
	if st != 201 {
		t.Fatalf("create run: %d %s", st, raw)
	}
	runID := created["runId"].(string)
	if created["engine"] != "graph" || created["mode"] != "live" {
		t.Fatalf("unexpected create response: %v", created)
	}

	start := time.Now()
	events, resp := readSSE(t, client, e.backend.URL+"/api/runs/"+runID+"/events", map[string]string{
		"traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
	}, 15*time.Second)
	total := time.Since(start)
	if resp.StatusCode != 200 || resp.Header.Get("Content-Type") != "text/event-stream" ||
		resp.Header.Get("X-Accel-Buffering") != "no" || resp.Header.Get("Cache-Control") != "no-cache" {
		t.Fatalf("bad sse response: %d %v", resp.StatusCode, resp.Header)
	}
	want := []string{"run_started", "guard", "triage", "round", "node", "round", "node", "node", "node", "critic", "round", "node", "guard", "guard", "done", "end"}
	if len(events) != len(want) {
		t.Fatalf("got %d events, want %d: %+v", len(events), len(want), events)
	}
	for i, w := range want {
		if events[i].Type != w {
			t.Fatalf("event %d = %s, want %s", i, events[i].Type, w)
		}
	}
	// Incremental: the first event must arrive long before the stream ends
	// (the fake agent waits 150ms between 16 events, ~2.25s total).
	if first := events[0].At.Sub(start); first > total/3 {
		t.Fatalf("first event after %v of %v: stream is buffered", first, total)
	}
	// Relay overhead: agent write time vs client receive time.
	var worst time.Duration
	for _, ev := range events {
		if ts, ok := ev.Data["ts_ms"].(float64); ok {
			d := ev.At.Sub(time.UnixMicro(int64(ts * 1000)))
			if d > worst {
				worst = d
			}
		}
	}
	t.Logf("max relay delay %v over %d events", worst, len(events))
	if worst > 50*time.Millisecond {
		t.Fatalf("relay overhead %v > 50ms", worst)
	}

	// Trace context reached the agent and continues the caller's trace.
	tps := e.agent.TraceparentsSeen()
	if len(tps) < 2 || !strings.HasPrefix(tps[len(tps)-1], "00-0af7651916cd43dd8448eb211c80319c-") {
		t.Fatalf("traceparent not propagated: %v", tps)
	}

	// Completion callback arrives after the stream; Slack gets notified.
	var run map[string]any
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		_, run, _ = e.do(client, "GET", "/api/runs/"+runID, nil, nil)
		if run["status"] == "completed" {
			break
		}
		time.Sleep(50 * time.Millisecond)
	}
	if run["status"] != "completed" || run["solved"] != true || len(run["nodes"].([]any)) != 5 || run["agentRunId"] == "" {
		t.Fatalf("run not completed: %v", run)
	}
	for _, k := range []string{"id", "userId", "bugId", "agentRunId", "mode", "engine", "status", "solved", "bestNodeId", "nodes", "usage", "latencyMs", "prUrl", "createdAt", "completedAt"} {
		if _, ok := run[k]; !ok {
			t.Fatalf("run json missing %q: %v", k, run)
		}
	}

	select {
	case <-e.slack.got:
	case <-time.After(5 * time.Second):
		t.Fatal("slack not notified")
	}
	e.slack.mu.Lock()
	p := e.slack.payloads[0]
	e.slack.mu.Unlock()
	assertSlackShape(t, p, "http://app.test/runs/"+runID, false)

	// Open PR -> stored, second Slack message carries the PR button.
	st, pr, raw := e.do(client, "POST", "/api/runs/"+runID+"/pr", nil, nil)
	if st != 200 || !strings.HasPrefix(pr["url"].(string), "https://github.com/") {
		t.Fatalf("open pr: %d %s", st, raw)
	}
	_, run, _ = e.do(client, "GET", "/api/runs/"+runID, nil, nil)
	if run["prUrl"] != pr["url"] {
		t.Fatalf("prUrl not stored: %v", run["prUrl"])
	}
	select {
	case <-e.slack.got:
	case <-time.After(5 * time.Second):
		t.Fatal("slack not notified for PR")
	}
	e.slack.mu.Lock()
	p = e.slack.payloads[1]
	e.slack.mu.Unlock()
	assertSlackShape(t, p, "http://app.test/runs/"+runID, true)

	// My runs list contains it; another user cannot see it.
	st, _, raw = e.do(client, "GET", "/api/runs", nil, nil)
	if st != 200 || !strings.Contains(string(raw), runID) {
		t.Fatalf("list runs: %d %s", st, raw)
	}
	other, _ := e.newUser()
	for _, path := range []string{"/api/runs/" + runID, "/api/runs/" + runID + "/events"} {
		st, _, _ = e.do(other, "GET", path, nil, nil)
		if st != 404 {
			t.Fatalf("other user %s: %d", path, st)
		}
	}
}

func assertSlackShape(t *testing.T, p map[string]any, runURL string, withPR bool) {
	t.Helper()
	if s, _ := p["text"].(string); s == "" {
		t.Fatalf("slack payload has no fallback text: %v", p)
	}
	blocks, _ := p["blocks"].([]any)
	if len(blocks) < 3 {
		t.Fatalf("slack blocks: %v", p)
	}
	b, _ := json.Marshal(p)
	if !strings.Contains(string(b), "6/6 passed") {
		t.Fatalf("slack payload lacks tests passed: %s", b)
	}
	var actions map[string]any
	for _, bl := range blocks {
		if m := bl.(map[string]any); m["type"] == "actions" {
			actions = m
		}
	}
	if actions == nil {
		t.Fatalf("no actions block: %s", b)
	}
	urls := []string{}
	for _, el := range actions["elements"].([]any) {
		m := el.(map[string]any)
		if m["type"] != "button" {
			t.Fatalf("non-button element: %v", m)
		}
		urls = append(urls, m["url"].(string))
	}
	if !strings.Contains(strings.Join(urls, " "), runURL) {
		t.Fatalf("run link missing: %v", urls)
	}
	if withPR != (len(urls) == 2) {
		t.Fatalf("PR button presence wrong (withPR=%v): %v", withPR, urls)
	}
}

func TestDailyCapFallsBackToReplay(t *testing.T) {
	e := newEnv(t, func(c *config.Config) { c.LiveRunsPerUserPerDay = 2 })
	client, _ := e.newUser()
	for i := 0; i < 2; i++ {
		st, r, raw := e.do(client, "POST", "/api/runs", map[string]any{"bugId": "cart"}, nil)
		if st != 201 || r["mode"] != "live" || r["notice"] != nil {
			t.Fatalf("run %d: %d %s", i, st, raw)
		}
	}
	// Explicit replays do not count against the cap.
	st, r, _ := e.do(client, "POST", "/api/runs", map[string]any{"bugId": "cart", "replay": true}, nil)
	if st != 201 || r["mode"] != "replay" || r["notice"] != nil {
		t.Fatalf("replay run: %d %v", st, r)
	}
	st, r, raw := e.do(client, "POST", "/api/runs", map[string]any{"bugId": "cart"}, nil)
	if st != 201 || r["mode"] != "replay" {
		t.Fatalf("capped run: %d %s", st, raw)
	}
	if n, _ := r["notice"].(string); !strings.Contains(n, "limit") {
		t.Fatalf("capped run lacks notice: %v", r)
	}
	created := e.agent.CreatedRuns()
	if last := created[len(created)-1]; last["replay"] != true {
		t.Fatalf("agent not asked for replay: %v", last)
	}
}

func TestRunValidation(t *testing.T) {
	e := newEnv(t, nil)
	client, _ := e.newUser()
	cases := []struct {
		body map[string]any
		code int
	}{
		{map[string]any{}, 400},
		{map[string]any{"bugId": "cart", "engine": "magic"}, 400},
		{map[string]any{"bugId": "../etc"}, 400},
		{map[string]any{"bugId": "missing"}, 404}, // agent says unknown bug
	}
	for _, c := range cases {
		st, _, raw := e.do(client, "POST", "/api/runs", c.body, nil)
		if st != c.code {
			t.Fatalf("%v: got %d %s", c.body, st, raw)
		}
		var m map[string]any
		if json.Unmarshal(raw, &m) != nil || m["error"] == nil {
			t.Fatalf("error body not {error}: %s", raw)
		}
	}
	st, _, _ := e.do(nil, "POST", "/api/runs", map[string]any{"bugId": "cart"}, nil)
	if st != 401 {
		t.Fatalf("unauthenticated create: %d", st)
	}
}

func TestGuestRunsRateLimitedAndReplayOnly(t *testing.T) {
	e := newEnv(t, nil)
	st, _, raw := e.do(nil, "GET", "/api/demo/bugs", nil, nil)
	if st != 200 || !strings.Contains(string(raw), "cart") {
		t.Fatalf("demo bugs: %d %s", st, raw)
	}
	var first string
	for i := 0; i < 3; i++ {
		st, r, raw := e.do(nil, "POST", "/api/demo/runs", map[string]any{"bugId": "cart"}, nil)
		if st != 201 || r["mode"] != "replay" {
			t.Fatalf("guest run %d: %d %s", i, st, raw)
		}
		if first == "" {
			first = r["runId"].(string)
		}
	}
	st, r, _ := e.do(nil, "POST", "/api/demo/runs", map[string]any{"bugId": "cart"}, nil)
	if st != 429 || r["error"] == nil {
		t.Fatalf("4th guest run: %d %v", st, r)
	}
	for _, c := range e.agent.CreatedRuns() {
		if c["replay"] != true || c["user_id"] != "" {
			t.Fatalf("guest run reached agent as live or with user: %v", c)
		}
	}
	events, _ := readSSE(t, nil, e.backend.URL+"/api/demo/runs/"+first+"/events", nil, 15*time.Second)
	if len(events) == 0 || events[len(events)-1].Type != "end" {
		t.Fatalf("guest stream: %+v", events)
	}
	// Guest runs are not readable via the authenticated API, and user runs
	// are not streamable via the demo API.
	client, _ := e.newUser()
	st, _, _ = e.do(client, "GET", "/api/runs/"+first, nil, nil)
	if st != 404 {
		t.Fatalf("user reading guest run: %d", st)
	}
	_, ur, _ := e.do(client, "POST", "/api/runs", map[string]any{"bugId": "cart"}, nil)
	st, _, _ = e.do(nil, "GET", "/api/demo/runs/"+ur["runId"].(string)+"/events", nil, nil)
	if st != 404 {
		t.Fatalf("demo events for user run: %d", st)
	}
}

func TestInternalCompleteRequiresSecret(t *testing.T) {
	e := newEnv(t, nil)
	body := map[string]any{"run_id": "abc", "solved": true}
	for _, hdr := range []map[string]string{nil, {"X-Agent-Secret": "wrong"}, {"X-Agent-Secret": testSecret + "x"}} {
		st, _, _ := e.do(nil, "POST", "/internal/runs/abc/complete", body, hdr)
		if st != 401 {
			t.Fatalf("hdr %v: %d", hdr, st)
		}
	}
	st, _, _ := e.do(nil, "POST", "/internal/runs/abc/complete", body, map[string]string{"X-Agent-Secret": testSecret})
	if st != 404 {
		t.Fatalf("unknown run with right secret: %d", st)
	}
}

func TestAgentKilledMidRunGivesCleanErrorEvent(t *testing.T) {
	e := newEnv(t, nil)
	client, _ := e.newUser()
	_, r, raw := e.do(client, "POST", "/api/runs", map[string]any{"bugId": "crash"}, nil)
	if r["runId"] == nil {
		t.Fatalf("create: %s", raw)
	}
	start := time.Now()
	events, _ := readSSE(t, client, e.backend.URL+"/api/runs/"+r["runId"].(string)+"/events", nil, 10*time.Second)
	if time.Since(start) > 5*time.Second {
		t.Fatalf("stream hung for %v", time.Since(start))
	}
	n := len(events)
	if n < 3 || events[n-2].Type != "error" || events[n-1].Type != "end" {
		t.Fatalf("expected ... error, end; got %+v", events)
	}
	if events[n-2].Data["stage"] != "relay" || events[n-2].Data["message"] == "" {
		t.Fatalf("bad error event: %+v", events[n-2])
	}
	if events[0].Type != "run_started" {
		t.Fatalf("events before the crash were lost: %+v", events)
	}
}

func TestAgentDownBeforeStream(t *testing.T) {
	e := newEnv(t, nil)
	client, _ := e.newUser()
	_, r, _ := e.do(client, "POST", "/api/runs", map[string]any{"bugId": "cart"}, nil)
	e.agentSv.Close()
	events, resp := readSSE(t, client, e.backend.URL+"/api/runs/"+r["runId"].(string)+"/events", nil, 10*time.Second)
	if resp.StatusCode != 200 || len(events) != 2 || events[0].Type != "error" || events[1].Type != "end" {
		t.Fatalf("got %d %+v", resp.StatusCode, events)
	}
	// Creating a run while the agent is down is a clean 502.
	st, m, _ := e.do(client, "POST", "/api/runs", map[string]any{"bugId": "cart"}, nil)
	if st != 502 || m["error"] == nil {
		t.Fatalf("create with agent down: %d %v", st, m)
	}
}

func TestClientDisconnectCancelsUpstream(t *testing.T) {
	e := newEnv(t, nil)
	client, _ := e.newUser()
	_, r, _ := e.do(client, "POST", "/api/runs", map[string]any{"bugId": "cart"}, nil)
	ctx, cancel := context.WithCancel(context.Background())
	req, _ := http.NewRequestWithContext(ctx, "GET", e.backend.URL+"/api/runs/"+r["runId"].(string)+"/events", nil)
	resp, err := client.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	br := bufio.NewReader(resp.Body)
	if _, err := br.ReadString('\n'); err != nil {
		t.Fatal(err)
	}
	cancel()
	resp.Body.Close()
	// The fake agent stops writing once its request context is cancelled;
	// with no completion callback the run stays "running".
	time.Sleep(3 * time.Second)
	_, run, _ := e.do(client, "GET", "/api/runs/"+r["runId"].(string), nil, nil)
	if run["status"] != "running" {
		t.Fatalf("upstream was not cancelled; run status %v", run["status"])
	}
}
