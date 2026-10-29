package app_test

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"encoding/pem"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"testing"
	"time"

	"patchloop-backend/internal/app"
	"patchloop-backend/internal/config"
	"patchloop-backend/internal/fakeagent"
	"patchloop-backend/internal/githubstub"
	"patchloop-backend/internal/handler"
	"patchloop-backend/internal/memstore"
	"patchloop-backend/internal/service"
	"patchloop-backend/internal/slackstub"

	"github.com/gin-gonic/gin"
)

const (
	slackSigning = "slack-signing-secret"
	slackBot     = "xoxb-test-bot-token"
	ghWebhookKey = "gh-webhook-secret"
	appID        = "12345"
)

// fakeAuth maps "plk_<name>" bearer tokens to users without any accounts.
type fakeAuth struct{}

func (fakeAuth) Authenticate(ctx context.Context, plain string) (string, string, error) {
	name := strings.TrimPrefix(plain, "plk_")
	if name == "" || name == plain || strings.Contains(name, " ") {
		return "", "", context.Canceled
	}
	return "u-" + name, name + "@example.com", nil
}

type hookSink struct {
	mu       sync.Mutex
	payloads []map[string]any
	paths    []string
}

func (h *hookSink) get() []map[string]any {
	h.mu.Lock()
	defer h.mu.Unlock()
	return append([]map[string]any(nil), h.payloads...)
}

// memEnv is the whole system on in-memory stores: backend, fake agent,
// GitHub stub, Slack API stub and a webhook capture server.
type memEnv struct {
	t       *testing.T
	backend *httptest.Server
	agent   *fakeagent.Agent
	gh      *githubstub.Stub
	slack   *slackstub.Stub
	hook    *hookSink
	hookURL string
	store   *memstore.Store
	notes   *memstore.Notifications
	app     *app.App
	cfg     *config.Config
	logs    *syncBuf
	noRedir *http.Client
}

type syncBuf struct {
	mu sync.Mutex
	b  bytes.Buffer
}

func (s *syncBuf) Write(p []byte) (int, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.b.Write(p)
}
func (s *syncBuf) String() string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.b.String()
}

func testKeyPEMBase64(t *testing.T) (*rsa.PrivateKey, string) {
	t.Helper()
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	pemBytes := pem.EncodeToMemory(&pem.Block{Type: "RSA PRIVATE KEY", Bytes: x509.MarshalPKCS1PrivateKey(key)})
	return key, base64.StdEncoding.EncodeToString(pemBytes)
}

var sharedKey *rsa.PrivateKey
var sharedKeyB64 string
var keyOnce sync.Once

func newMemEnv(t *testing.T, mutate func(*config.Config)) *memEnv {
	t.Helper()
	gin.SetMode(gin.TestMode)
	keyOnce.Do(func() { sharedKey, sharedKeyB64 = testKeyPEMBase64(t) })

	logs := &syncBuf{}
	prev := slog.Default()
	slog.SetDefault(slog.New(slog.NewTextHandler(logs, &slog.HandlerOptions{Level: slog.LevelDebug})))
	oldW := gin.DefaultErrorWriter
	gin.DefaultErrorWriter = logs
	t.Cleanup(func() { slog.SetDefault(prev); gin.DefaultErrorWriter = oldW })

	agent := fakeagent.New(fakeagent.Options{Secret: testSecret, Delay: 5 * time.Millisecond})
	agentSv := httptest.NewServer(agent)
	t.Cleanup(agentSv.Close)

	gh := githubstub.New(appID, &sharedKey.PublicKey)
	ghSv := httptest.NewServer(gh)
	t.Cleanup(ghSv.Close)

	sl := slackstub.New(slackBot)
	slSv := httptest.NewServer(sl)
	t.Cleanup(slSv.Close)

	sink := &hookSink{}
	hookSv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var p map[string]any
		_ = json.NewDecoder(r.Body).Decode(&p)
		sink.mu.Lock()
		sink.payloads = append(sink.payloads, p)
		sink.paths = append(sink.paths, r.URL.Path)
		sink.mu.Unlock()
		_, _ = w.Write([]byte("ok"))
	}))
	t.Cleanup(hookSv.Close)

	encKey := base64.StdEncoding.EncodeToString(bytes.Repeat([]byte{9}, 32))
	cfg := &config.Config{
		JWTAccessSecret: "access-secret-for-tests", JWTRefreshSecret: "refresh-secret-for-tests",
		FrontendOrigin: "http://localhost:3000", FrontendURL: "http://front.test", PublicAppURL: "http://app.test",
		AgentURL: agentSv.URL, AgentSharedSecret: testSecret,
		GitHubAppID: appID, GitHubAppSlug: "patchloop-test", GitHubAppPrivateKey: sharedKeyB64,
		GitHubClientID: "cid", GitHubClientSecret: "csecret", GitHubWebhookSecret: ghWebhookKey,
		GitHubAPIURL: ghSv.URL, GitHubWebURL: ghSv.URL, TokenEncKey: encKey,
		SlackSigningSecret: slackSigning, SlackBotToken: slackBot, SlackAPIBase: slSv.URL,
		LiveRunsPerUserPerDay: 100, GuestRunsPerHour: 3, TasksPerUserPerHour: 50, DevMode: true,
	}
	if mutate != nil {
		mutate(cfg)
	}
	if cfg.SlackWebhookURL == "USE_HOOK" {
		cfg.SlackWebhookURL = hookSv.URL + "/global"
	}
	store := memstore.New()
	notes := store.NotificationStore()
	a := app.Build(cfg, app.Stores{Runs: store, GitHub: store, Slack: store, Notifications: notes, Dedupe: store},
		app.Auth{Handler: handler.NewAuthHandler(nil, handler.AuthHandlerConfig{}), TokenAuth: fakeAuth{}}, nil, nil)
	backend := httptest.NewServer(a.Router)
	t.Cleanup(backend.Close)
	agent.SetCallbackURL(backend.URL)

	return &memEnv{t: t, backend: backend, agent: agent, gh: gh, slack: sl, hook: sink, hookURL: hookSv.URL + "/hook", store: store, notes: notes,
		app: a, cfg: cfg, logs: logs,
		noRedir: &http.Client{CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}}
}

// api calls the backend as the named user ("" = unauthenticated). The body is
// decoded as a JSON object when possible.
func (e *memEnv) api(user, method, path string, body any) (int, map[string]any, []byte) {
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
	if user != "" {
		req.Header.Set("Authorization", "Bearer plk_"+user)
	}
	resp, err := e.noRedir.Do(req)
	if err != nil {
		e.t.Fatalf("%s %s: %v", method, path, err)
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	var m map[string]any
	_ = json.Unmarshal(raw, &m)
	if m == nil {
		m = map[string]any{}
	}
	m["_location"] = resp.Header.Get("Location")
	return resp.StatusCode, m, raw
}

// apiList is api for endpoints that return a JSON array.
func (e *memEnv) apiList(user, path string) (int, []map[string]any) {
	e.t.Helper()
	st, _, raw := e.api(user, "GET", path, nil)
	var out []map[string]any
	_ = json.Unmarshal(raw, &out)
	return st, out
}

func (e *memEnv) post(path string, header http.Header, body []byte) (int, []byte) {
	e.t.Helper()
	req, _ := http.NewRequest("POST", e.backend.URL+path, bytes.NewReader(body))
	for k, v := range header {
		req.Header[k] = v
	}
	resp, err := e.noRedir.Do(req)
	if err != nil {
		e.t.Fatal(err)
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	return resp.StatusCode, raw
}

func (e *memEnv) ghWebhook(event, delivery string, payload any, secret string) (int, []byte) {
	b, _ := json.Marshal(payload)
	h := http.Header{}
	h.Set("X-GitHub-Event", event)
	h.Set("X-GitHub-Delivery", delivery)
	h.Set("X-Hub-Signature-256", service.SignGitHubBody(secret, b))
	h.Set("Content-Type", "application/json")
	return e.post("/api/github/webhook", h, b)
}

func (e *memEnv) slackPost(path, contentType string, body []byte) (int, []byte) {
	ts, sig := service.SignSlackRequest(slackSigning, body, time.Now())
	h := http.Header{}
	h.Set("X-Slack-Request-Timestamp", ts)
	h.Set("X-Slack-Signature", sig)
	h.Set("Content-Type", contentType)
	return e.post(path, h, body)
}

func (e *memEnv) slackCommand(slackUser, channel, text string) (int, map[string]any) {
	form := url.Values{"command": {"/patchloop"}, "text": {text}, "user_id": {slackUser}, "channel_id": {channel}}
	st, raw := e.slackPost("/slack/commands", "application/x-www-form-urlencoded", []byte(form.Encode()))
	var m map[string]any
	_ = json.Unmarshal(raw, &m)
	return st, m
}

func (e *memEnv) slackInteraction(payload map[string]any) int {
	b, _ := json.Marshal(payload)
	form := url.Values{"payload": {string(b)}}
	st, _ := e.slackPost("/slack/interactions", "application/x-www-form-urlencoded", []byte(form.Encode()))
	return st
}

func (e *memEnv) slackEvent(env map[string]any) int {
	b, _ := json.Marshal(env)
	st, _ := e.slackPost("/slack/events", "application/json", b)
	return st
}

// eventually polls cond for up to 10s.
func eventually(t *testing.T, what string, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(10 * time.Second)
	for time.Now().Before(deadline) {
		if cond() {
			return
		}
		time.Sleep(15 * time.Millisecond)
	}
	t.Fatalf("timed out waiting for %s", what)
}

// connectApp runs the GitHub App install flow for user (installation 777).
func (e *memEnv) connectApp(user string, withCode bool) {
	e.t.Helper()
	st, m, raw := e.api(user, "GET", "/api/github/connect", nil)
	if st != 200 {
		e.t.Fatalf("connect: %d %s", st, raw)
	}
	u, _ := url.Parse(m["url"].(string))
	q := url.Values{"installation_id": {"777"}, "setup_action": {"install"}, "state": {u.Query().Get("state")}}
	if withCode {
		q.Set("code", "goodcode")
	}
	st, m, raw = e.api("", "GET", "/api/github/callback?"+q.Encode(), nil)
	if st != 302 || !strings.Contains(m["_location"].(string), "github=connected") {
		e.t.Fatalf("callback: %d %v %s", st, m["_location"], raw)
	}
}

// startTask creates a repo task and returns the run id.
func (e *memEnv) startTask(user, repo, task string) string {
	e.t.Helper()
	st, m, raw := e.api(user, "POST", "/api/tasks", map[string]any{"repo": repo, "task": task})
	if st != 201 {
		e.t.Fatalf("task: %d %s", st, raw)
	}
	return m["runId"].(string)
}

func (e *memEnv) getRun(user, id string) map[string]any {
	e.t.Helper()
	_, m, _ := e.api(user, "GET", "/api/runs/"+id, nil)
	return m
}

func (e *memEnv) waitCompleted(user, id string) map[string]any {
	e.t.Helper()
	var run map[string]any
	eventually(e.t, "run "+id+" completed", func() bool {
		run = e.getRun(user, id)
		return run["status"] == "completed"
	})
	return run
}
