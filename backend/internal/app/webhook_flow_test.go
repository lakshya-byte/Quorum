package app_test

import (
	"net/http"
	"strings"
	"testing"
	"time"

	"patchloop-backend/internal/config"
)

func issuePayload(action, label string, number int) map[string]any {
	return map[string]any{
		"action":       action,
		"installation": map[string]any{"id": 777},
		"sender":       map[string]any{"login": "octo-owner", "type": "User"},
		"repository":   map[string]any{"full_name": "octo/widgets"},
		"label":        map[string]any{"name": label},
		"issue":        map[string]any{"number": number, "title": "Pagination is off by one", "body": "page 3 of 3 is empty"},
	}
}

func commentPayload(body, assoc string, isPR bool, number int) map[string]any {
	issue := map[string]any{"number": number, "title": "Pagination is off by one", "body": "page 3 of 3 is empty"}
	if isPR {
		issue["pull_request"] = map[string]any{"url": "https://api.github.com/repos/octo/widgets/pulls/42"}
	}
	return map[string]any{
		"action":       "created",
		"installation": map[string]any{"id": 777},
		"sender":       map[string]any{"login": "octo-owner", "type": "User"},
		"repository":   map[string]any{"full_name": "octo/widgets"},
		"issue":        issue,
		"comment":      map[string]any{"body": body, "author_association": assoc, "user": map[string]any{"login": "octo-owner", "type": "User"}},
	}
}

func TestGitHubWebhookSignatureAndDedupe(t *testing.T) {
	e := newMemEnv(t, nil)
	e.connectApp("alice", true)
	payload := issuePayload("labeled", "patchloop", 12)

	// Wrong secret / missing signature / tampered body: 401, and nothing happens.
	if st, _ := e.ghWebhook("issues", "d0", payload, "wrong"); st != 401 {
		t.Fatalf("wrong secret: %d", st)
	}
	if st, _ := e.post("/api/github/webhook", http.Header{"X-GitHub-Event": {"issues"}}, []byte(`{}`)); st != 401 {
		t.Fatalf("unsigned: %d", st)
	}
	h := http.Header{"X-GitHub-Event": {"issues"}, "X-Hub-Signature-256": {"sha256=00"}}
	if st, _ := e.post("/api/github/webhook", h, []byte(`{}`)); st != 401 {
		t.Fatalf("bad signature: %d", st)
	}
	time.Sleep(50 * time.Millisecond)
	if len(e.agent.CreatedRuns()) != 0 {
		t.Fatal("unauthenticated webhook started a run")
	}

	// Valid delivery starts exactly one run even when GitHub redelivers.
	st, raw := e.ghWebhook("issues", "delivery-1", payload, ghWebhookKey)
	if st != 202 || !strings.Contains(string(raw), "accepted") {
		t.Fatalf("labeled: %d %s", st, raw)
	}
	st, raw = e.ghWebhook("issues", "delivery-1", payload, ghWebhookKey)
	if st != 202 || !strings.Contains(string(raw), "duplicate") {
		t.Fatalf("redelivery: %d %s", st, raw)
	}
	eventually(t, "issue-triggered run", func() bool { return len(e.agent.CreatedRuns()) == 1 })
	time.Sleep(50 * time.Millisecond)
	if len(e.agent.CreatedRuns()) != 1 {
		t.Fatalf("duplicate delivery started a second run: %d", len(e.agent.CreatedRuns()))
	}
	c := e.agent.CreatedRuns()[0]
	if c["source"] != "github" || c["repo"] != "octo/widgets" || c["issue_ref"] != 12 ||
		!strings.Contains(c["task"].(string), "Pagination is off by one") || !strings.Contains(c["task"].(string), "page 3 of 3 is empty") {
		t.Fatalf("agent request: %v", c)
	}
	// "PatchLoop is on it: <run url>" is commented on the issue, with the installation token.
	eventually(t, "issue comment", func() bool { return len(e.gh.CallsTo("POST /repos/octo/widgets/issues/12/comments")) >= 1 })
	cm := e.gh.CallsTo("POST /repos/octo/widgets/issues/12/comments")[0]
	if cm.Auth != e.gh.InstallToken || !strings.HasPrefix(cm.Body["body"].(string), "PatchLoop is on it: http://app.test/runs/") {
		t.Fatalf("comment: %+v", cm)
	}
	// On completion a second comment links the PR.
	eventually(t, "PR comment", func() bool { return len(e.gh.CallsTo("POST /repos/octo/widgets/issues/12/comments")) == 2 })
	if !strings.Contains(e.gh.CallsTo("POST /repos/octo/widgets/issues/12/comments")[1].Body["body"].(string), "https://github.com/octo/widgets/pull/") {
		t.Fatal("completion comment lacks the PR link")
	}
	_, list := e.apiList("alice", "/api/runs")
	if len(list) != 1 || list[0]["source"] != "github" {
		t.Fatalf("run list: %v", list)
	}
	issue := list[0]["issue"].(map[string]any)
	if issue["number"] != float64(12) {
		t.Fatalf("issue ref: %v", list[0])
	}
}

func TestGitHubWebhookNotConfiguredIsOff(t *testing.T) {
	e := newMemEnv(t, func(c *config.Config) { c.GitHubWebhookSecret = "" })
	st, _ := e.ghWebhook("issues", "d1", issuePayload("labeled", "patchloop", 1), "")
	if st != 503 {
		t.Fatalf("unconfigured webhook accepted a delivery: %d", st)
	}
}

func TestGitHubWebhookIgnoresWhatItShould(t *testing.T) {
	e := newMemEnv(t, nil)
	e.connectApp("alice", true)
	n := 0
	send := func(event string, p map[string]any) (int, string) {
		n++
		st, raw := e.ghWebhook(event, "d-"+string(rune('a'+n)), p, ghWebhookKey)
		return st, string(raw)
	}
	cases := []struct {
		name  string
		event string
		p     map[string]any
	}{
		{"other label", "issues", issuePayload("labeled", "bug", 1)},
		{"opened not labeled", "issues", issuePayload("opened", "patchloop", 1)},
		{"bot sender", "issues", func() map[string]any {
			p := issuePayload("labeled", "patchloop", 1)
			p["sender"] = map[string]any{"login": "dependabot[bot]", "type": "Bot"}
			return p
		}()},
		{"unknown installation", "issues", func() map[string]any {
			p := issuePayload("labeled", "patchloop", 1)
			p["installation"] = map[string]any{"id": 999}
			return p
		}()},
		{"comment from stranger", "issue_comment", commentPayload("@patchloop fix", "NONE", false, 3)},
		{"comment from first timer", "issue_comment", commentPayload("@patchloop fix", "FIRST_TIME_CONTRIBUTOR", false, 3)},
		{"comment without mention", "issue_comment", commentPayload("looks bad", "OWNER", false, 3)},
		{"mention without fix on an issue", "issue_comment", commentPayload("@patchloop what do you think", "OWNER", false, 3)},
		{"comment on a PatchLoop-less PR", "issue_comment", commentPayload("@patchloop change x", "OWNER", true, 99)},
		{"bot comment (our own)", "issue_comment", func() map[string]any {
			p := commentPayload("@patchloop fix", "OWNER", false, 3)
			p["comment"].(map[string]any)["user"] = map[string]any{"login": "patchloop[bot]", "type": "Bot"}
			return p
		}()},
		{"pull_request event", "pull_request", map[string]any{"action": "opened", "installation": map[string]any{"id": 777}}},
		{"check_suite event", "check_suite", map[string]any{"action": "completed", "installation": map[string]any{"id": 777}}},
	}
	for _, tc := range cases {
		st, body := send(tc.event, tc.p)
		if st != 202 || !strings.Contains(body, "ignored") {
			t.Errorf("%s: %d %s", tc.name, st, body)
		}
	}
	time.Sleep(100 * time.Millisecond)
	if len(e.agent.CreatedRuns()) != 0 {
		t.Fatalf("ignored deliveries started runs: %v", e.agent.CreatedRuns())
	}
}

func TestGitHubWebhookCommentTriggersAndPRFollowup(t *testing.T) {
	e := newMemEnv(t, nil)
	e.connectApp("alice", true)

	// "@patchloop fix" on a plain issue, from a collaborator.
	st, raw := e.ghWebhook("issue_comment", "c-1", commentPayload("@PatchLoop fix this please", "COLLABORATOR", false, 7), ghWebhookKey)
	if st != 202 || !strings.Contains(string(raw), "accepted") {
		t.Fatalf("comment trigger: %d %s", st, raw)
	}
	eventually(t, "run from comment", func() bool { return len(e.agent.CreatedRuns()) == 1 })
	if c := e.agent.CreatedRuns()[0]; c["source"] != "github" || c["issue_ref"] != 7 {
		t.Fatalf("comment run: %v", c)
	}
	_, list := e.apiList("alice", "/api/runs")
	id := list[0]["id"].(string)
	run := e.waitCompleted("alice", id)
	if run["prNumber"] == float64(0) {
		t.Fatalf("no PR: %v", run)
	}

	// A comment on that PR (branch patchloop/*) asks for changes: a follow-up on the same PR.
	pr := commentPayload("@patchloop use a 1-based page index", "MEMBER", true, int(run["prNumber"].(float64)))
	pr["repository"] = map[string]any{"full_name": "octo/widgets"}
	st, raw = e.ghWebhook("issue_comment", "c-2", pr, ghWebhookKey)
	if st != 202 || !strings.Contains(string(raw), "accepted") {
		t.Fatalf("pr comment: %d %s", st, raw)
	}
	eventually(t, "followup run", func() bool { return len(e.agent.CreatedRuns()) == 2 })
	fu := e.agent.CreatedRuns()[1]["followup"].(map[string]any)
	if fu["pr_branch"] != run["prBranch"] || fu["message"] != "use a 1-based page index" {
		t.Fatalf("followup: %v", fu)
	}
	if e.agent.CreatedRuns()[1]["source"] != "github" {
		t.Fatalf("source: %v", e.agent.CreatedRuns()[1])
	}
}

func TestGitHubWebhookInstallationLifecycle(t *testing.T) {
	e := newMemEnv(t, nil)
	e.connectApp("alice", true) // login octo-owner, installation 777

	// Deleting the installation unlinks it: no more repos, no more runs.
	st, _ := e.ghWebhook("installation", "i-1", map[string]any{"action": "deleted", "installation": map[string]any{"id": 777},
		"sender": map[string]any{"login": "octo-owner", "type": "User"}}, ghWebhookKey)
	if st != 202 {
		t.Fatalf("deleted: %d", st)
	}
	_, m, _ := e.api("alice", "GET", "/api/github/status", nil)
	if m["connected"] != false {
		t.Fatalf("still connected after uninstall: %v", m)
	}
	if st, m, _ := e.api("alice", "POST", "/api/tasks", map[string]any{"repo": "octo/widgets", "task": "x"}); st != 409 {
		t.Fatalf("task after uninstall: %d %v", st, m)
	}
	// Reinstalling (webhook arrives before/without the browser callback) re-links by GitHub login.
	st, _ = e.ghWebhook("installation", "i-2", map[string]any{"action": "created", "installation": map[string]any{"id": 888},
		"sender": map[string]any{"login": "octo-owner", "type": "User"}}, ghWebhookKey)
	if st != 202 {
		t.Fatalf("created: %d", st)
	}
	_, m, _ = e.api("alice", "GET", "/api/github/status", nil)
	if m["connected"] != true || m["installationId"] != float64(888) {
		t.Fatalf("not re-linked: %v", m)
	}
}
