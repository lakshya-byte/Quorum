package app_test

import (
	"encoding/json"
	"strings"
	"testing"

	"patchloop-backend/internal/config"
	"patchloop-backend/internal/models"
)

func TestGitHubAppConnectReposAndBranches(t *testing.T) {
	e := newMemEnv(t, nil)

	st, m, _ := e.api("alice", "GET", "/api/github/status", nil)
	if st != 200 || m["connected"] != false || m["appConfigured"] != true || m["mode"] != nil {
		t.Fatalf("initial status: %d %v", st, m)
	}
	if st, _, _ := e.api("", "GET", "/api/github/status", nil); st != 401 {
		t.Fatalf("status without auth: %d", st)
	}

	// Install flow: connect URL -> callback with installation_id + code.
	st, m, _ = e.api("alice", "GET", "/api/github/connect", nil)
	u := m["url"].(string)
	if st != 200 || !strings.Contains(u, "/apps/patchloop-test/installations/new?state=") {
		t.Fatalf("connect url: %d %v", st, m)
	}
	e.connectApp("alice", true)

	st, m, _ = e.api("alice", "GET", "/api/github/status", nil)
	if m["connected"] != true || m["mode"] != "app" || m["login"] != "octo-owner" || m["installationId"] != float64(777) || m["repoCount"] != float64(2) {
		t.Fatalf("status after connect: %v", m)
	}

	// The user token is stored encrypted, never as plaintext.
	raw := e.store.RawGitHub("u-alice")
	if raw.EncUserToken == "" || strings.Contains(raw.EncUserToken, "ghu_") || raw.EncRefreshToken == "" || strings.Contains(raw.EncRefreshToken, "ghr_") {
		t.Fatalf("user token not encrypted at rest: %+v", raw)
	}
	if e.gh.Mints() != 1 {
		t.Fatalf("expected one installation token mint (cached after), got %d", e.gh.Mints())
	}

	st, repos := e.apiList("alice", "/api/github/repos")
	if st != 200 || len(repos) != 2 || repos[0]["fullName"] != "octo/widgets" || repos[0]["private"] != true || repos[1]["description"] != "" || repos[1]["defaultBranch"] != "trunk" {
		t.Fatalf("repos: %d %v", st, repos)
	}
	st, repos = e.apiList("alice", "/api/github/repos?q=gadg")
	if st != 200 || len(repos) != 1 || repos[0]["fullName"] != "octo/gadgets" {
		t.Fatalf("repo search: %v", repos)
	}
	st, bs := e.apiList("alice", "/api/github/repos/octo/widgets/branches")
	if st != 200 || len(bs) != 2 || bs[0]["name"] != "main" || bs[0]["default"] != true || bs[1]["default"] != false {
		t.Fatalf("branches: %v", bs)
	}
	if st, _, _ := e.api("alice", "GET", "/api/github/repos/octo/..%2Fx/branches", nil); st != 400 && st != 404 {
		t.Fatalf("bad repo name accepted: %d", st)
	}

	// Another user sees nothing.
	st, m, _ = e.api("bob", "GET", "/api/github/repos", nil)
	if st != 409 || m["code"] != "github_not_connected" || m["error"] != "connect github first" {
		t.Fatalf("bob repos: %d %v", st, m)
	}

	st, _, _ = e.api("alice", "DELETE", "/api/github", nil)
	if st != 200 {
		t.Fatalf("disconnect: %d", st)
	}
	_, m, _ = e.api("alice", "GET", "/api/github/status", nil)
	if m["connected"] != false {
		t.Fatalf("still connected: %v", m)
	}
}

func TestGitHubCallbackRejectsBadStateAndBadCode(t *testing.T) {
	e := newMemEnv(t, nil)
	for _, q := range []string{"state=garbage&installation_id=1", "installation_id=1", "state=a.b&installation_id=1"} {
		st, m, _ := e.api("", "GET", "/api/github/callback?"+q, nil)
		if st != 302 || !strings.Contains(m["_location"].(string), "github=error") || !strings.Contains(m["_location"].(string), "invalid_state") {
			t.Fatalf("%s: %d %v", q, st, m["_location"])
		}
	}
	// A state minted for alice cannot be tampered into bob's.
	_, m, _ := e.api("alice", "GET", "/api/github/connect", nil)
	state := strings.Split(m["url"].(string), "state=")[1]
	st, loc, _ := e.api("", "GET", "/api/github/callback?installation_id=5&state="+state+"x", nil)
	if st != 302 || !strings.Contains(loc["_location"].(string), "invalid_state") {
		t.Fatalf("tampered state accepted: %v", loc["_location"])
	}
	// Bad OAuth code -> error redirect, nothing stored.
	st, loc, _ = e.api("", "GET", "/api/github/callback?installation_id=5&code=bad&state="+state, nil)
	if st != 302 || !strings.Contains(loc["_location"].(string), "github=error") {
		t.Fatalf("bad code: %v", loc["_location"])
	}
	if strings.Contains(loc["_location"].(string), "bad_verification_code") {
		t.Fatalf("GitHub error text leaked into the redirect URL")
	}
	_, m, _ = e.api("alice", "GET", "/api/github/status", nil)
	if m["connected"] != false {
		t.Fatalf("connected despite failed exchange: %v", m)
	}
}

func TestGitHubNotConfigured(t *testing.T) {
	e := newMemEnv(t, func(c *config.Config) { c.GitHubAppID, c.GitHubAppSlug, c.GitHubAppPrivateKey = "", "", "" })
	st, m, _ := e.api("alice", "GET", "/api/github/connect", nil)
	if st != 503 || m["error"] != "github app not configured" || m["code"] != "not_configured" {
		t.Fatalf("connect unconfigured: %d %v", st, m)
	}
	_, m, _ = e.api("alice", "GET", "/api/github/status", nil)
	if m["appConfigured"] != false {
		t.Fatalf("appConfigured: %v", m)
	}
	// The demo account still works.
	if st, _, _ := e.api("alice", "POST", "/api/github/demo", nil); st != 200 {
		t.Fatalf("demo: %d", st)
	}
}

func TestNoEncryptionKeyRefusesToStoreTokens(t *testing.T) {
	e := newMemEnv(t, func(c *config.Config) { c.TokenEncKey, c.DevMode = "", false })
	_, m, _ := e.api("alice", "GET", "/api/github/connect", nil)
	state := strings.Split(m["url"].(string), "state=")[1]
	_, loc, _ := e.api("", "GET", "/api/github/callback?installation_id=5&code=goodcode&state="+state, nil)
	if !strings.Contains(loc["_location"].(string), "github=error") {
		t.Fatalf("stored a token without an encryption key: %v", loc["_location"])
	}
	if e.store.RawGitHub("u-alice") != nil {
		t.Fatal("connection saved without encryption")
	}
	// Slack webhooks are secrets too.
	st, m, _ := e.api("alice", "PUT", "/api/settings/slack", map[string]any{"webhookUrl": "https://hooks.slack.com/services/T000/B000/XXXXXXXX"})
	if st != 503 || m["code"] != "not_configured" {
		t.Fatalf("webhook stored without key: %d %v", st, m)
	}
}

func TestDemoAccountOffline(t *testing.T) {
	e := newMemEnv(t, nil)
	st, m, _ := e.api("alice", "POST", "/api/github/demo", nil)
	if st != 200 || m["mode"] != "demo" {
		t.Fatalf("demo connect: %d %v", st, m)
	}
	_, m, _ = e.api("alice", "GET", "/api/github/status", nil)
	if m["connected"] != true || m["mode"] != "demo" || m["login"] != "demo-user" || m["repoCount"] != float64(3) {
		t.Fatalf("demo status: %v", m)
	}
	_, repos := e.apiList("alice", "/api/github/repos")
	names := []string{}
	for _, r := range repos {
		names = append(names, r["fullName"].(string))
	}
	if strings.Join(names, ",") != "demo/inventory-api,demo/billing-utils,demo/text-tools" {
		t.Fatalf("demo repos: %v", names)
	}
	_, bs := e.apiList("alice", "/api/github/repos/demo/text-tools/branches")
	if len(bs) != 1 || bs[0]["name"] != "main" {
		t.Fatalf("demo branches: %v", bs)
	}

	id := e.startTask("alice", "demo/inventory-api", "reserve() lets stock go negative")
	run := e.waitCompleted("alice", id)
	created := e.agent.CreatedRuns()
	if created[0]["has_token"] != false || created[0]["repo"] != "demo/inventory-api" || created[0]["branch"] != "main" {
		t.Fatalf("demo run must carry no token: %v", created[0])
	}
	if run["kind"] != "repo" || run["solved"] != true || !strings.HasPrefix(run["prUrl"].(string), "https://github.com/demo/inventory-api/pull/") {
		t.Fatalf("demo run: %v", run)
	}

	// A demo user cannot aim at a real repo.
	st, m, _ = e.api("alice", "POST", "/api/tasks", map[string]any{"repo": "octo/widgets", "task": "x"})
	if st == 201 {
		t.Fatalf("demo account started a run on a real repo: %v", m)
	}

	// Fake PR info and merge, no GitHub traffic at all.
	st, m, _ = e.api("alice", "GET", "/api/runs/"+id+"/pr", nil)
	if st != 200 || m["mergeAllowed"] != true || m["fake"] != true {
		t.Fatalf("demo pr: %d %v", st, m)
	}
	st, m, _ = e.api("alice", "POST", "/api/runs/"+id+"/merge", map[string]any{})
	if st != 200 || m["merged"] != true || m["fake"] != true {
		t.Fatalf("demo merge: %d %v", st, m)
	}
	if len(e.gh.Calls()) != 0 {
		t.Fatalf("demo mode touched GitHub: %v", e.gh.Calls())
	}
}

func TestRepoTaskEndToEndAndTokenNeverLeaks(t *testing.T) {
	e := newMemEnv(t, nil)
	// A per-user webhook receives the completion card.
	e.connectApp("alice", true)
	if st, _, raw := e.api("alice", "PUT", "/api/settings/slack", map[string]any{"webhookUrl": e.hookURL}); st != 200 {
		t.Fatalf("set webhook: %d %s", st, raw)
	}

	var bodies []string
	capture := func(raw []byte) { bodies = append(bodies, string(raw)) }

	st, m, raw := e.api("alice", "POST", "/api/tasks", map[string]any{"repo": "octo/widgets", "task": "pagination returns the wrong last page"})
	capture(raw)
	if st != 201 || m["branch"] != "main" || m["repo"] != "octo/widgets" {
		t.Fatalf("create task: %d %s", st, raw)
	}
	id := m["runId"].(string)

	// SSE relay covers repo runs and the new event types.
	events, resp := readSSE(t, nil, e.backend.URL+"/api/runs/"+id+"/events", map[string]string{"Authorization": "Bearer plk_alice"}, 15e9)
	if resp.StatusCode != 200 {
		t.Fatalf("sse: %d", resp.StatusCode)
	}
	seen := map[string]bool{}
	for _, ev := range events {
		seen[ev.Type] = true
	}
	for _, want := range []string{"repo", "locate", "repro", "node", "done", "pr", "end"} {
		if !seen[want] {
			t.Errorf("stream lacks %q event", want)
		}
	}

	run := e.waitCompleted("alice", id)
	rawRun, _ := json.Marshal(run)
	capture(rawRun)

	// The agent got the installation token (not the user token) and a run link.
	created := e.agent.CreatedRuns()
	if len(created) != 1 {
		t.Fatalf("agent runs: %v", created)
	}
	c := created[0]
	if c["github_token"] != e.gh.InstallToken || c["source"] != "cli" || c["auto_pr"] != true || c["branch"] != "main" ||
		c["run_url"] != "http://app.test/runs/"+id {
		t.Fatalf("agent request: %v", c)
	}

	if run["kind"] != "repo" || run["source"] != "cli" || run["repo"] != "octo/widgets" || run["branch"] != "main" ||
		run["task"] != "pagination returns the wrong last page" || run["solved"] != true {
		t.Fatalf("run fields: %v", run)
	}
	if !strings.HasPrefix(run["prBranch"].(string), "patchloop/") || run["prNumber"].(float64) < 41 ||
		!strings.HasPrefix(run["prUrl"].(string), "https://github.com/octo/widgets/pull/") {
		t.Fatalf("pr fields: %v", run)
	}
	cost := run["cost"].(map[string]any)
	if cost["tokens"] != float64(4000) || run["latencyMs"] != float64(4200) || run["traceId"] == "" || run["traceId"] == nil {
		t.Fatalf("cost/latency/trace: %v", run)
	}
	safety := run["safety"].(map[string]any)
	if safety["guard"] == nil || safety["policy"] == nil || safety["security"] == nil {
		t.Fatalf("safety: %v", safety)
	}
	if files, _ := run["filesChanged"].([]any); len(files) != 1 || files[0] != "src/app.py" {
		t.Fatalf("filesChanged: %v", run["filesChanged"])
	}

	// In-app notification + webhook completion card with the PR button.
	eventually(t, "pr_opened notification", func() bool {
		for _, n := range e.notes.Notesx() {
			if n.Kind == "pr_opened" && n.RunID == id && n.UserID == "u-alice" {
				return true
			}
		}
		return false
	})
	eventually(t, "slack webhook card", func() bool { return len(e.hook.get()) == 1 })
	card, _ := json.Marshal(e.hook.get()[0])
	if !strings.Contains(string(card), run["prUrl"].(string)) || !strings.Contains(string(card), "octo/widgets") ||
		!strings.Contains(string(card), "pagination returns the wrong last page") || !strings.Contains(string(card), "Review PR") {
		t.Fatalf("completion card: %s", card)
	}
	eventually(t, "slackSent flag", func() bool { return e.getRun("alice", id)["slackSent"] == true })

	// List includes the new fields; another user cannot see the run.
	st, list := e.apiList("alice", "/api/runs")
	if st != 200 || len(list) != 1 || list[0]["kind"] != "repo" || list[0]["repo"] != "octo/widgets" {
		t.Fatalf("list: %v", list)
	}
	if st, _, _ := e.api("bob", "GET", "/api/runs/"+id, nil); st != 404 {
		t.Fatalf("bob reads alice's run: %d", st)
	}

	// Tokens never appear in any response we saw, nor in any log line.
	_, _, raw = e.api("alice", "GET", "/api/github/status", nil)
	capture(raw)
	_, _, raw = e.api("alice", "GET", "/api/runs", nil)
	capture(raw)
	_, _, raw = e.api("alice", "GET", "/api/settings/slack", nil)
	capture(raw)
	all := strings.Join(bodies, "\n") + "\n" + e.logs.String()
	for _, secret := range []string{e.gh.InstallToken, e.gh.UserToken, "ghr_refresh", "SECRET_TOKEN"} {
		if strings.Contains(all, secret) {
			t.Fatalf("secret %q leaked into a response or log", secret)
		}
	}
	// Nor in the stored run document or the event stream.
	evJSON, _ := json.Marshal(events)
	if strings.Contains(string(evJSON), "SECRET_TOKEN") || strings.Contains(string(rawRun), e.gh.InstallToken) {
		t.Fatal("token leaked into events or run record")
	}
}

func TestTaskValidationAuthAndRateLimit(t *testing.T) {
	e := newMemEnv(t, func(c *config.Config) { c.TasksPerUserPerHour = 4 })
	if st, _, _ := e.api("", "POST", "/api/tasks", map[string]any{"repo": "octo/widgets", "task": "x"}); st != 401 {
		t.Fatalf("guest task: %d", st)
	}
	st, m, _ := e.api("alice", "POST", "/api/tasks", map[string]any{"repo": "octo/widgets", "task": "x"})
	if st != 409 || m["error"] != "connect github first" {
		t.Fatalf("not connected: %d %v", st, m)
	}
	e.connectApp("alice", true)

	bad := []map[string]any{
		{"repo": "octo", "task": "x"},
		{"repo": "octo/widgets", "task": ""},
		{"repo": "octo/widgets", "task": strings.Repeat("a", 4001)},
		{"repo": "octo/../etc", "task": "x"},
		{"repo": "octo/widgets", "branch": "../../x", "task": "x"},
		{"repo": "octo/widgets", "branch": "-rf", "task": "x"},
	}
	for _, b := range bad {
		st, m, _ := e.api("alice", "POST", "/api/tasks", b)
		if st != 400 || m["code"] != "bad_request" {
			t.Errorf("%v: %d %v", b, st, m)
		}
	}
	st, m, _ = e.api("alice", "POST", "/api/tasks", map[string]any{"repo": "someone/else", "task": "x"})
	if st != 403 || m["code"] != "repo_not_granted" {
		t.Fatalf("ungranted repo: %d %v", st, m)
	}
	if len(e.agent.CreatedRuns()) != 0 {
		t.Fatal("agent called for an invalid task")
	}

	// 4 per hour per user (two attempts above already used budget); others unaffected.
	for i := 0; i < 2; i++ {
		e.startTask("alice", "octo/widgets", "task")
	}
	st, m, _ = e.api("alice", "POST", "/api/tasks", map[string]any{"repo": "octo/widgets", "task": "x"})
	if st != 429 || m["code"] != "rate_limited" {
		t.Fatalf("rate limit: %d %v", st, m)
	}
	e.api("bob", "POST", "/api/github/demo", nil)
	e.startTask("bob", "demo/text-tools", "fine")
}

func TestAgentDownAtTaskCreationGivesCleanError(t *testing.T) {
	e := newMemEnv(t, func(c *config.Config) { c.AgentURL = "http://127.0.0.1:1" })
	e.connectApp("alice", true)
	st, m, _ := e.api("alice", "POST", "/api/tasks", map[string]any{"repo": "octo/widgets", "task": "x"})
	if st != 502 || m["code"] != "agent_unavailable" {
		t.Fatalf("agent down: %d %v", st, m)
	}
	if strings.Contains(e.logs.String(), e.gh.InstallToken) {
		t.Fatal("token logged on agent failure")
	}
	_, list := e.apiList("alice", "/api/runs")
	if len(list) != 1 || list[0]["status"] != "failed" {
		t.Fatalf("failed run not recorded: %v", list)
	}
}

func TestMergeGate(t *testing.T) {
	e := newMemEnv(t, nil)
	e.connectApp("alice", true)
	id := e.startTask("alice", "octo/widgets", "fix it")
	e.waitCompleted("alice", id)

	tr, fl := true, false
	cases := []struct {
		name    string
		setup   func()
		allowed bool
		reason  string
		warning string
	}{
		{"green", func() {}, true, "", ""},
		{"failing check", func() {
			e.gh.CheckRuns = []map[string]any{{"name": "unit", "status": "completed", "conclusion": "failure"}, {"name": "lint", "status": "completed", "conclusion": "success"}}
		}, false, "checks are failing: unit", ""},
		{"pending check", func() {
			e.gh.CheckRuns = []map[string]any{{"name": "unit", "status": "in_progress"}}
		}, false, "checks are still running", ""},
		{"failing commit status", func() {
			e.gh.CheckRuns = nil
			e.gh.Statuses = []map[string]any{{"context": "ci/legacy", "state": "failure"}}
		}, false, "ci/legacy", ""},
		{"no checks configured", func() { e.gh.CheckRuns, e.gh.Statuses = nil, nil }, true, "", "no checks configured"},
		{"conflicts", func() {
			e.gh.CheckRuns = []map[string]any{{"name": "ci", "status": "completed", "conclusion": "success"}}
			e.gh.Mergeable = &fl
		}, false, "not mergeable", ""},
		{"mergeability unknown", func() { e.gh.Mergeable = nil }, false, "still computing", ""},
		{"closed", func() { e.gh.Mergeable = &tr; e.gh.PRState = "closed" }, false, "closed", ""},
	}
	for _, tc := range cases {
		tc.setup()
		st, m, raw := e.api("alice", "GET", "/api/runs/"+id+"/pr", nil)
		if st != 200 || m["mergeAllowed"] != tc.allowed || !strings.Contains(m["reason"].(string), tc.reason) {
			t.Fatalf("%s: %d %s", tc.name, st, raw)
		}
		if tc.warning != "" && m["warning"] != tc.warning {
			t.Fatalf("%s: warning %v", tc.name, m["warning"])
		}
		if !tc.allowed {
			st, m, _ := e.api("alice", "POST", "/api/runs/"+id+"/merge", map[string]any{})
			if st != 409 || m["code"] != "merge_refused" || !strings.Contains(m["reason"].(string), tc.reason) {
				t.Fatalf("%s: merge not refused: %d %v", tc.name, st, m)
			}
		}
	}
	if len(e.gh.CallsTo("PUT ")) != 0 {
		t.Fatal("a merge call reached GitHub although every gate refused")
	}

	// Reset to green: only the owner may merge, using their OWN token.
	e.gh.PRState, e.gh.Mergeable = "open", &tr
	e.gh.CheckRuns = []map[string]any{{"name": "ci", "status": "completed", "conclusion": "success"}}
	if st, _, _ := e.api("bob", "POST", "/api/runs/"+id+"/merge", map[string]any{}); st != 404 {
		t.Fatalf("bob merged alice's run: %d", st)
	}
	if st, _, _ := e.api("", "POST", "/api/runs/"+id+"/merge", map[string]any{}); st != 401 {
		t.Fatalf("anonymous merge: %d", st)
	}
	st, m, raw := e.api("alice", "POST", "/api/runs/"+id+"/merge", map[string]any{"method": "squash"})
	if st != 200 || m["merged"] != true || m["by"] != "octo-owner" {
		t.Fatalf("merge: %d %s", st, raw)
	}
	puts := e.gh.CallsTo("PUT /repos/octo/widgets/pulls/")
	if len(puts) != 1 || puts[0].Auth != e.gh.UserToken || puts[0].Body["merge_method"] != "squash" || puts[0].Body["sha"] != "abc123" {
		t.Fatalf("merge must use the user's token and pin the head sha: %+v", puts)
	}
	run := e.getRun("alice", id)
	merged := run["merged"].(map[string]any)
	if merged["by"] != "octo-owner" || merged["at"] == nil {
		t.Fatalf("merged record: %v", run["merged"])
	}
	found := false
	for _, n := range e.notes.Notesx() {
		found = found || (n.Kind == "merged" && n.RunID == id)
	}
	if !found {
		t.Fatal("no merged notification")
	}
	// Second merge is refused.
	st, m, _ = e.api("alice", "POST", "/api/runs/"+id+"/merge", map[string]any{})
	if st != 409 || !strings.Contains(m["reason"].(string), "already merged") {
		t.Fatalf("double merge: %d %v", st, m)
	}
	if st, m, _ := e.api("alice", "POST", "/api/runs/"+id+"/merge", map[string]any{"method": "yolo"}); st != 409 && st != 400 {
		t.Fatalf("bad method: %d %v", st, m)
	}
}

func TestMergeNeedsUserAuthorization(t *testing.T) {
	e := newMemEnv(t, nil)
	e.connectApp("alice", false) // installed, but never authorised as a user
	id := e.startTask("alice", "octo/widgets", "fix it")
	e.waitCompleted("alice", id)
	st, m, _ := e.api("alice", "POST", "/api/runs/"+id+"/merge", map[string]any{})
	if st != 409 || m["code"] != "merge_refused" || !strings.Contains(m["reason"].(string), "reconnect GitHub") {
		t.Fatalf("merge without user token: %d %v", st, m)
	}
	if len(e.gh.CallsTo("PUT ")) != 0 {
		t.Fatal("merged with the installation token")
	}
}

func TestGitHubRejectingMergeIsReportedNotHidden(t *testing.T) {
	e := newMemEnv(t, nil)
	e.connectApp("alice", true)
	id := e.startTask("alice", "octo/widgets", "fix it")
	e.waitCompleted("alice", id)
	e.gh.MergeFail = 405
	st, m, _ := e.api("alice", "POST", "/api/runs/"+id+"/merge", map[string]any{})
	if st != 409 || m["code"] != "merge_refused" || !strings.Contains(m["reason"].(string), "GitHub refused") {
		t.Fatalf("github refusal: %d %v", st, m)
	}
	if run := e.getRun("alice", id); run["merged"] != nil {
		t.Fatalf("marked merged although GitHub refused: %v", run["merged"])
	}
}

func TestFollowupPushesToSamePR(t *testing.T) {
	e := newMemEnv(t, nil)
	e.connectApp("alice", true)
	id := e.startTask("alice", "octo/widgets", "fix it")
	parent := e.waitCompleted("alice", id)

	st, m, raw := e.api("alice", "POST", "/api/runs/"+id+"/followup", map[string]any{"message": "please also handle page 0"})
	if st != 201 {
		t.Fatalf("followup: %d %s", st, raw)
	}
	child := m["runId"].(string)
	cr := e.waitCompleted("alice", child)
	if cr["parentRunId"] != id || cr["prUrl"] != parent["prUrl"] || cr["prNumber"] != parent["prNumber"] || cr["prBranch"] != parent["prBranch"] || cr["source"] != "cli" {
		t.Fatalf("child: %v", cr)
	}
	created := e.agent.CreatedRuns()
	fu := created[1]["followup"].(map[string]any)
	files := fu["previous_files"].(map[string]any)
	if fu["pr_branch"] != parent["prBranch"] || fu["pr_number"] != parent["prNumber"] || fu["message"] != "please also handle page 0" || files["src/app.py"] == nil {
		t.Fatalf("agent followup: %v", fu)
	}
	if created[1]["task"] != "fix it" || created[1]["github_token"] != e.gh.InstallToken {
		t.Fatalf("followup request: %v", created[1])
	}
	eventually(t, "pr_updated notification", func() bool {
		for _, n := range e.notes.Notesx() {
			if n.Kind == "pr_updated" && n.RunID == child {
				return true
			}
		}
		return false
	})

	// Other users cannot; empty message is rejected; limit is 5 per PR.
	if st, _, _ := e.api("bob", "POST", "/api/runs/"+id+"/followup", map[string]any{"message": "x"}); st != 404 {
		t.Fatalf("bob followup: %d", st)
	}
	if st, _, _ := e.api("alice", "POST", "/api/runs/"+id+"/followup", map[string]any{"message": ""}); st != 400 {
		t.Fatalf("empty message: %d", st)
	}
	for i := 0; i < 4; i++ {
		st, m, raw := e.api("alice", "POST", "/api/runs/"+id+"/followup", map[string]any{"message": "again"})
		if st != 201 {
			t.Fatalf("followup %d: %d %s", i+2, st, raw)
		}
		e.waitCompleted("alice", m["runId"].(string))
	}
	st, m, _ = e.api("alice", "POST", "/api/runs/"+id+"/followup", map[string]any{"message": "one too many"})
	if st != 429 || m["code"] != "rate_limited" {
		t.Fatalf("sixth followup: %d %v", st, m)
	}
}

func TestFollowupRequiresAPR(t *testing.T) {
	e := newMemEnv(t, nil)
	e.connectApp("alice", true)
	id := e.startTask("alice", "octo/widgets", "this is unsolvable")
	run := e.waitCompleted("alice", id)
	if run["solved"] != false || run["prUrl"] != "" {
		t.Fatalf("unsolved run: %v", run)
	}
	st, m, _ := e.api("alice", "POST", "/api/runs/"+id+"/followup", map[string]any{"message": "try again"})
	if st != 409 || m["code"] != "conflict" {
		t.Fatalf("followup without PR: %d %v", st, m)
	}
	// And a "no passing fix" notification instead of pr_opened.
	eventually(t, "failed notification", func() bool {
		for _, n := range e.notes.Notesx() {
			if n.Kind == "failed" && n.RunID == id {
				return true
			}
		}
		return false
	})
	if st, _, _ := e.api("alice", "GET", "/api/runs/"+id+"/pr", nil); st != 409 {
		t.Fatalf("pr info without PR: %d", st)
	}
}

func TestOpenPRWhenAutoPRWasOff(t *testing.T) {
	e := newMemEnv(t, nil)
	e.connectApp("alice", true)
	st, m, _ := e.api("alice", "POST", "/api/tasks", map[string]any{"repo": "octo/widgets", "task": "fix it", "autoPr": false})
	if st != 201 {
		t.Fatalf("task: %d", st)
	}
	id := m["runId"].(string)
	run := e.waitCompleted("alice", id)
	if run["prUrl"] != "" || run["autoPr"] != false {
		t.Fatalf("auto_pr=false opened a PR: %v", run)
	}
	st, m, raw := e.api("alice", "POST", "/api/runs/"+id+"/pr", nil)
	if st != 200 || !strings.HasPrefix(m["url"].(string), "https://github.com/octo/widgets/pull/") {
		t.Fatalf("open pr: %d %s", st, raw)
	}
	run = e.getRun("alice", id)
	if run["prUrl"] != m["url"] || run["prNumber"] == float64(0) || !strings.HasPrefix(run["prBranch"].(string), "patchloop/") {
		t.Fatalf("pr not stored: %v", run)
	}
	// The agent got the token again for this call.
	if strings.Contains(e.logs.String(), e.gh.InstallToken) {
		t.Fatal("token logged")
	}
}

func TestNotificationsAPI(t *testing.T) {
	e := newMemEnv(t, nil)
	e.connectApp("alice", true)
	id := e.startTask("alice", "octo/widgets", "fix it")
	e.waitCompleted("alice", id)
	var list map[string]any
	eventually(t, "notification", func() bool {
		_, list, _ = e.api("alice", "GET", "/api/notifications", nil)
		ns, _ := list["notifications"].([]any)
		return len(ns) > 0
	})
	n := list["notifications"].([]any)[0].(map[string]any)
	if list["unread"] != float64(1) || n["kind"] != "pr_opened" || n["runId"] != id || n["read"] != false {
		t.Fatalf("notification: %v", list)
	}
	if st, _, _ := e.api("bob", "POST", "/api/notifications/"+n["id"].(string)+"/read", nil); st != 404 {
		t.Fatalf("bob marked alice's notification: %d", st)
	}
	if st, _, _ := e.api("alice", "POST", "/api/notifications/"+n["id"].(string)+"/read", nil); st != 200 {
		t.Fatalf("mark read: %d", st)
	}
	_, list, _ = e.api("alice", "GET", "/api/notifications", nil)
	if list["unread"] != float64(0) {
		t.Fatalf("still unread: %v", list)
	}
	_, other, _ := e.api("bob", "GET", "/api/notifications", nil)
	if ns, _ := other["notifications"].([]any); len(ns) != 0 {
		t.Fatalf("bob sees alice's notifications: %v", other)
	}
}

var _ = models.RunKindRepo
