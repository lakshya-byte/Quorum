package app_test

import (
	"bufio"
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"

	"patchloop-backend/internal/config"
)

// ssEvent is one parsed relay event plus the exact line the backend sent.
type ssEvent struct {
	Type string
	Data map[string]any
	Raw  string
}

// events reads a run's relayed SSE stream to the end.
func (e *memEnv) events(user, id string) []ssEvent {
	e.t.Helper()
	req, _ := http.NewRequest("GET", e.backend.URL+"/api/runs/"+id+"/events", nil)
	req.Header.Set("Authorization", "Bearer plk_"+user)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		e.t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		e.t.Fatalf("events: %d", resp.StatusCode)
	}
	var out []ssEvent
	sc := bufio.NewScanner(resp.Body)
	sc.Buffer(make([]byte, 1<<20), 8<<20)
	for sc.Scan() {
		line := sc.Text()
		if !strings.HasPrefix(line, "data: ") {
			continue
		}
		var ev struct {
			Type string         `json:"type"`
			Data map[string]any `json:"data"`
		}
		if json.Unmarshal([]byte(strings.TrimPrefix(line, "data: ")), &ev) == nil {
			out = append(out, ssEvent{ev.Type, ev.Data, strings.TrimPrefix(line, "data: ")})
		}
		if ev.Type == "end" {
			break
		}
	}
	return out
}

func typesOf(evs []ssEvent) map[string]int {
	m := map[string]int{}
	for _, ev := range evs {
		m[ev.Type]++
	}
	return m
}

// rawGet fetches path as user ("" = anonymous) and returns status, headers and body.
func (e *memEnv) rawGet(user, path string) (int, http.Header, []byte) {
	e.t.Helper()
	req, _ := http.NewRequest("GET", e.backend.URL+path, nil)
	if user != "" {
		req.Header.Set("Authorization", "Bearer plk_"+user)
	}
	resp, err := e.noRedir.Do(req)
	if err != nil {
		e.t.Fatal(err)
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	return resp.StatusCode, resp.Header, b
}

func (e *memEnv) task(user string, body map[string]any) (int, map[string]any) {
	e.t.Helper()
	st, m, _ := e.api(user, "POST", "/api/tasks", body)
	return st, m
}

func TestSwarmTaskOptionsValidatedAndClamped(t *testing.T) {
	e := newMemEnv(t, func(c *config.Config) {
		c.SwarmMaxWorkersCap, c.SwarmMaxTokensCap, c.SwarmMaxWallSCap = 4, 100000, 600
	})
	e.connectApp("alice", true)

	bad := []map[string]any{
		{"taskType": "wizardry"},
		{"taskType": "UI; drop table"},
		{"strict": []string{"ok", "has space"}},
		{"strict": []string{"a\nb"}},
		{"limits": map[string]any{"maxWorkers": -1}},
		{"limits": map[string]any{"maxTokens": -5}},
		{"limits": map[string]any{"maxWallS": -5}},
	}
	for _, extra := range bad {
		body := map[string]any{"repo": "octo/widgets", "task": "do a thing"}
		for k, v := range extra {
			body[k] = v
		}
		if st, m := e.task("alice", body); st != 400 {
			t.Errorf("%v should be rejected, got %d %v", extra, st, m)
		}
	}
	tooMany := make([]string, 21)
	for i := range tooMany {
		tooMany[i] = "c"
	}
	if st, _ := e.task("alice", map[string]any{"repo": "octo/widgets", "task": "x", "strict": tooMany}); st != 400 {
		t.Errorf("21 strict ids accepted: %d", st)
	}
	if n := len(e.agent.CreatedRuns()); n != 0 {
		t.Fatalf("invalid requests reached the agent: %d", n)
	}

	// Valid: default type is auto; limits are clamped to the configured caps and sent to the agent.
	st, m := e.task("alice", map[string]any{"repo": "octo/widgets", "task": "make the header responsive", "taskType": "ui",
		"strict": []string{"vision_rubric", "vision_rubric"}, "limits": map[string]any{"maxWorkers": 99, "maxTokens": 99999999999, "maxWallS": 30}})
	if st != 201 || m["taskType"] != "ui" || m["limitsClamped"] != true {
		t.Fatalf("task: %d %v", st, m)
	}
	lim := m["limits"].(map[string]any)
	if lim["maxWorkers"] != float64(4) || lim["maxTokens"] != float64(100000) || lim["maxWallS"] != float64(30) {
		t.Fatalf("limits not clamped: %v", lim)
	}
	c := e.agent.CreatedRuns()[0]
	al := c["limits"].(map[string]any)
	if c["task_type"] != "ui" || al["max_workers"] != float64(4) || al["max_tokens"] != float64(100000) || al["max_wall_s"] != float64(30) {
		t.Fatalf("agent request: %v", c)
	}
	if s := c["strict"].([]string); len(s) != 1 || s[0] != "vision_rubric" {
		t.Fatalf("strict not deduped: %v", c["strict"])
	}
	run := e.waitCompleted("alice", m["runId"].(string))
	if run["taskType"] != "ui" || run["taskTypeSource"] != "user" {
		t.Fatalf("stored type: %v %v", run["taskType"], run["taskTypeSource"])
	}

	// Defaults: no type = auto; no limits = none sent.
	st, m = e.task("alice", map[string]any{"repo": "octo/widgets", "task": "fix it"})
	if st != 201 || m["taskType"] != "auto" {
		t.Fatalf("default: %d %v", st, m)
	}
	c = e.agent.CreatedRuns()[1]
	if c["task_type"] != "auto" || len(c["limits"].(map[string]any)) != 0 {
		t.Fatalf("default agent request: %v", c)
	}
}

func TestUISwarmEndToEnd(t *testing.T) {
	e := newMemEnv(t, nil)
	e.connectApp("alice", true)
	st, m := e.task("alice", map[string]any{"repo": "octo/widgets", "task": "improve the UI of the landing page for phones",
		"strict": []string{"vision_rubric"}})
	if st != 201 {
		t.Fatalf("task: %d %v", st, m)
	}
	id := m["runId"].(string)
	run := e.waitCompleted("alice", id)

	if run["taskType"] != "ui" || run["taskTypeSource"] != "auto" || run["outcome"] != "complete" || run["solved"] != true {
		t.Fatalf("run: type=%v source=%v outcome=%v solved=%v", run["taskType"], run["taskTypeSource"], run["outcome"], run["solved"])
	}
	cs := run["criteriaSummary"].(map[string]any)
	if cs["hardTotal"] != float64(10) || cs["hardPass"] != float64(10) { // 9 gates + vision_rubric promoted by strict
		t.Fatalf("criteria summary: %v", cs)
	}
	if run["agentsSpawned"].(float64) < 8 || run["peakParallel"] != float64(3) {
		t.Fatalf("agents: %v/%v", run["agentsSpawned"], run["peakParallel"])
	}
	plan := run["plan"].(map[string]any)
	if plan["task_type"] != "ui" || len(plan["criteria"].([]any)) != 10 || len(plan["units"].([]any)) != 3 {
		t.Fatalf("plan: %v", plan)
	}
	arts := run["artifacts"].([]any)
	if len(arts) < 8 {
		t.Fatalf("artifact index: %d", len(arts))
	}
	if !strings.HasPrefix(run["prUrl"].(string), "https://github.com/octo/widgets/pull/") {
		t.Fatalf("pr: %v", run["prUrl"])
	}

	// The relay passes every new event type through, byte for byte.
	evs := e.events("alice", id)
	counts := typesOf(evs)
	for _, typ := range []string{"plan", "agent", "tool", "unit", "merge", "verify", "artifact", "budget", "done", "pr", "end"} {
		if counts[typ] == 0 {
			t.Errorf("event %q missing from the relay (%v)", typ, counts)
		}
	}
	direct := directEvents(t, e, id)
	if len(direct) != len(evs) {
		t.Fatalf("relay changed the stream: %d vs %d events", len(evs), len(direct))
	}
	for i := range evs {
		if evs[i].Raw != direct[i] {
			t.Fatalf("event %d altered by the relay:\n%s\n%s", i, evs[i].Raw, direct[i])
		}
	}
	for _, ev := range evs {
		switch ev.Type {
		case "done":
			if ev.Data["outcome"] != "complete" || ev.Data["solved"] != true || ev.Data["agents"].(map[string]any)["peak_parallel"] != float64(3) {
				t.Errorf("done: %v", ev.Data)
			}
		case "pr":
			if ev.Data["commits"] != float64(3) {
				t.Errorf("pr should carry one commit per unit: %v", ev.Data)
			}
		}
	}

	// Secrets: the installation token is in no event, no run document, no log.
	all, _ := json.Marshal(evs)
	rb, _ := json.Marshal(run)
	if strings.Contains(string(all)+string(rb)+e.logs.String(), e.gh.InstallToken) {
		t.Fatal("token leaked into swarm events, the run document or logs")
	}
}

// directEvents reads the agent's own stream for the run (bypassing the relay).
func directEvents(t *testing.T, e *memEnv, backendRunID string) []string {
	t.Helper()
	run := e.getRun("alice", backendRunID)
	req, _ := http.NewRequest("GET", e.cfg.AgentURL+"/runs/"+run["agentRunId"].(string)+"/events", nil)
	req.Header.Set("X-Agent-Secret", testSecret)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	var out []string
	sc := bufio.NewScanner(resp.Body)
	sc.Buffer(make([]byte, 1<<20), 8<<20)
	for sc.Scan() {
		if strings.HasPrefix(sc.Text(), "data: ") {
			line := strings.TrimPrefix(sc.Text(), "data: ")
			out = append(out, line)
			if strings.Contains(line, `"type":"end"`) {
				break
			}
		}
	}
	return out
}

func TestSwarmLimitsReachTheAgentAndAreHonoured(t *testing.T) {
	e := newMemEnv(t, nil)
	e.connectApp("alice", true)
	st, m := e.task("alice", map[string]any{"repo": "octo/widgets", "task": "add percentage coupons to the cart", "taskType": "feature",
		"limits": map[string]any{"maxWorkers": 1, "maxTokens": 50000}})
	if st != 201 {
		t.Fatalf("task: %d %v", st, m)
	}
	run := e.waitCompleted("alice", m["runId"].(string))
	if run["peakParallel"] != float64(1) || run["outcome"] != "complete" {
		t.Fatalf("worker cap ignored: %v / %v", run["peakParallel"], run["outcome"])
	}
	for _, ev := range e.events("alice", m["runId"].(string)) {
		if ev.Type == "budget" && ev.Data["tokens_limit"] != float64(50000) {
			t.Fatalf("budget: %v", ev.Data)
		}
	}
}

func TestRefactorRepairRoundAndFailureOutcome(t *testing.T) {
	e := newMemEnv(t, nil)
	e.connectApp("alice", true)
	id := e.startTask("alice", "octo/widgets", "refactor the checkout module, it is too big")
	run := e.waitCompleted("alice", id)
	if run["taskType"] != "refactor" || run["outcome"] != "complete" {
		t.Fatalf("refactor: %v %v", run["taskType"], run["outcome"])
	}
	verifies := 0
	for _, ev := range e.events("alice", id) {
		if ev.Type == "verify" {
			verifies++
			if verifies == 1 && ev.Data["hard_pass"] != false {
				t.Errorf("round 1 should fail a hard gate: %v", ev.Data)
			}
			if verifies == 2 && ev.Data["hard_pass"] != true {
				t.Errorf("round 2 should pass: %v", ev.Data)
			}
		}
	}
	if verifies != 2 {
		t.Fatalf("want a repair round, got %d verify events", verifies)
	}

	// An unsolvable task fails honestly: outcome failed, no PR, nothing mergeable.
	fid := e.startTask("alice", "octo/widgets", "add a feature that is unsolvable")
	fr := e.waitCompleted("alice", fid)
	cs := fr["criteriaSummary"].(map[string]any)
	if fr["outcome"] != "failed" || fr["solved"] != false || fr["prUrl"] != "" || cs["hardPass"].(float64) >= cs["hardTotal"].(float64) {
		t.Fatalf("failed run: %v %v %v", fr["outcome"], fr["prUrl"], cs)
	}
	if st, _, _ := e.api("alice", "GET", "/api/runs/"+fid+"/pr", nil); st != 409 {
		t.Fatalf("pr of a failed run: %d", st)
	}
	eventually(t, "failed notification", func() bool {
		for _, n := range e.notes.Notesx() {
			if n.Kind == "failed" && n.RunID == fid {
				return true
			}
		}
		return false
	})
}

func TestPartialOutcomeMergeWarningAndFollowup(t *testing.T) {
	e := newMemEnv(t, nil)
	e.api("alice", "POST", "/api/github/demo", nil)
	id := e.startTask("alice", "demo/shop-api", "speed up pricing so it feels faster, partial")
	run := e.waitCompleted("alice", id)
	if run["outcome"] != "partial" || run["solved"] != false || run["taskType"] != "perf" {
		t.Fatalf("partial run: %v %v %v", run["outcome"], run["solved"], run["taskType"])
	}
	if run["prUrl"] == "" {
		t.Fatal("a partial run still opens a PR")
	}
	adv := run["criteriaSummary"].(map[string]any)["advisory"].([]any)
	if len(adv) < 2 {
		t.Fatalf("advisory notes (incl. the unverifiable criterion): %v", adv)
	}
	st, m, _ := e.api("alice", "GET", "/api/runs/"+id+"/pr", nil)
	if st != 200 || m["mergeAllowed"] != true || !strings.Contains(m["warning"].(string), "partial") {
		t.Fatalf("pr info: %d %v", st, m)
	}
	// Follow-up works on partial runs.
	st, fm, raw := e.api("alice", "POST", "/api/runs/"+id+"/followup", map[string]any{"message": "also cover the discount path"})
	if st != 201 {
		t.Fatalf("followup on partial: %d %s", st, raw)
	}
	e.waitCompleted("alice", fm["runId"].(string))
	st, m, _ = e.api("alice", "POST", "/api/runs/"+id+"/merge", map[string]any{})
	if st != 200 || m["merged"] != true || !strings.Contains(m["warning"].(string), "partial") {
		t.Fatalf("merge partial: %d %v", st, m)
	}
}

func TestNeedsInputAnswersFlow(t *testing.T) {
	e := newMemEnv(t, nil)
	e.connectApp("alice", true)
	e.connectApp("bob", true)
	id := e.startTask("alice", "octo/widgets", "make the app better, it is vague")
	run := e.waitCompleted("alice", id)
	if run["outcome"] != "needs_input" || run["solved"] != false || run["prUrl"] != "" {
		t.Fatalf("needs_input run: %v", run)
	}
	qs := run["questions"].([]any)
	if len(qs) != 2 || qs[0].(map[string]any)["id"] != "q1" {
		t.Fatalf("questions: %v", qs)
	}
	evs := e.events("alice", id)
	if typesOf(evs)["clarify"] != 1 {
		t.Fatalf("no clarify event relayed: %v", typesOf(evs))
	}
	eventually(t, "needs_input notification", func() bool {
		for _, n := range e.notes.Notesx() {
			if n.Kind == "needs_input" && n.RunID == id {
				return true
			}
		}
		return false
	})

	ans := map[string]any{"answers": map[string]any{"q1": "the cart module", "q2": "totals include shipping"}}
	if st, _, _ := e.api("", "POST", "/api/runs/"+id+"/answers", ans); st != 401 {
		t.Fatalf("anonymous answers: %d", st)
	}
	if st, _, _ := e.api("bob", "POST", "/api/runs/"+id+"/answers", ans); st != 404 {
		t.Fatalf("non-owner answers: %d", st)
	}
	for _, bad := range []map[string]any{
		{}, {"answers": map[string]any{}}, {"answers": map[string]any{"zzz": "unknown question"}},
		{"answers": map[string]any{"q1": ""}}, {"answers": map[string]any{"q1": strings.Repeat("a", 2001)}},
		{"answers": map[string]any{"bad id": "x"}},
	} {
		if st, _, _ := e.api("alice", "POST", "/api/runs/"+id+"/answers", bad); st != 400 {
			t.Errorf("bad answers %v accepted: %d", bad, st)
		}
	}
	if n := len(e.agent.CreatedRuns()); n != 1 {
		t.Fatalf("rejected answers reached the agent: %d runs", n)
	}

	st, m, raw := e.api("alice", "POST", "/api/runs/"+id+"/answers", ans)
	if st != 201 || m["parentRunId"] != id {
		t.Fatalf("answers: %d %s", st, raw)
	}
	child := e.waitCompleted("alice", m["runId"].(string))
	cr := e.agent.CreatedRuns()[1]
	got := cr["answers"].(map[string]any)
	if got["q1"] != "the cart module" || cr["repo"] != "octo/widgets" || cr["branch"] != "main" || cr["task"] != run["task"] {
		t.Fatalf("agent re-run request: %v", cr)
	}
	if child["parentRunId"] != id || child["outcome"] != "complete" || child["answered"] != true || child["branch"] != run["branch"] {
		t.Fatalf("child run: %v", child)
	}
	// Answering a run that is not waiting for input is refused.
	if st, _, _ := e.api("alice", "POST", "/api/runs/"+m["runId"].(string)+"/answers", map[string]any{"answers": map[string]any{"q1": "x"}}); st != 409 {
		t.Fatalf("answers on a complete run: %d", st)
	}
}

func TestSwarmRateLimitCoversAnswersAndFollowups(t *testing.T) {
	e := newMemEnv(t, func(c *config.Config) { c.TasksPerUserPerHour = 3 })
	e.connectApp("alice", true)
	id := e.startTask("alice", "octo/widgets", "it is vague") // 1
	e.waitCompleted("alice", id)
	st, m, raw := e.api("alice", "POST", "/api/runs/"+id+"/answers", map[string]any{"answers": map[string]any{"q1": "a"}}) // 2
	if st != 201 {
		t.Fatalf("answers: %d %s", st, raw)
	}
	e.waitCompleted("alice", m["runId"].(string))
	st, m, _ = e.api("alice", "POST", "/api/runs/"+m["runId"].(string)+"/followup", map[string]any{"message": "more"}) // 3
	if st != 201 {
		t.Fatalf("followup: %d %v", st, m)
	}
	e.waitCompleted("alice", m["runId"].(string))
	if st, m := e.task("alice", map[string]any{"repo": "octo/widgets", "task": "one more"}); st != 429 {
		t.Fatalf("fourth swarm start should be rate limited: %d %v", st, m)
	}
}

func TestArtifactsProxyAuthAndSafety(t *testing.T) {
	e := newMemEnv(t, nil)
	e.connectApp("alice", true)
	e.connectApp("bob", true)
	id := e.startTask("alice", "octo/widgets", "make the layout responsive")
	e.waitCompleted("alice", id)

	st, list := e.apiList("alice", "/api/runs/"+id+"/artifacts")
	if st != 200 || len(list) < 8 {
		t.Fatalf("list: %d %d", st, len(list))
	}
	var png, svg, logID string
	for _, a := range list {
		switch a["mime"] {
		case "image/png":
			if png == "" {
				png = a["id"].(string)
			}
		case "text/plain":
			logID = a["id"].(string)
		}
		if a["size"] == nil || a["kind"] == nil {
			t.Errorf("index entry incomplete: %v", a)
		}
	}
	if png == "" || logID == "" {
		t.Fatalf("no png/log in %v", list)
	}

	// Auth: anonymous 401, other user 404 for both list and bytes.
	for _, p := range []string{"/api/runs/" + id + "/artifacts", "/api/runs/" + id + "/artifacts/" + png} {
		if st, _, _ := e.rawGet("", p); st != 401 {
			t.Errorf("anonymous %s: %d", p, st)
		}
		if st, _, _ := e.rawGet("bob", p); st != 404 {
			t.Errorf("bob %s: %d", p, st)
		}
	}

	st, h, body := e.rawGet("alice", "/api/runs/"+id+"/artifacts/"+png)
	if st != 200 || h.Get("Content-Type") != "image/png" || h.Get("X-Content-Type-Options") != "nosniff" ||
		!strings.Contains(h.Get("Content-Security-Policy"), "sandbox") || !bytes.HasPrefix(body, []byte("\x89PNG")) {
		t.Fatalf("png: %d %v", st, h)
	}
	if strings.Contains(string(body)+h.Get("X-Agent-Secret"), testSecret) || h.Get("X-Agent-Secret") != "" {
		t.Fatal("agent secret exposed")
	}
	st, h, body = e.rawGet("alice", "/api/runs/"+id+"/artifacts/"+logID)
	if st != 200 || !strings.HasPrefix(h.Get("Content-Type"), "text/plain") || h.Get("X-Content-Type-Options") != "nosniff" || !strings.Contains(string(body), "build: ok") {
		t.Fatalf("log: %d %v", st, h)
	}
	_ = svg

	// Hostile ids never reach the agent; unknown ids are 404.
	for _, bad := range []string{"..", ".hidden", "a%2Fb", "..%2F..%2Fetc%2Fpasswd", "a%00b", "a%20b", strings.Repeat("a", 65), "a.png", "a;b"} {
		st, _, _ := e.rawGet("alice", "/api/runs/"+id+"/artifacts/"+bad)
		if st != 400 && st != 404 {
			t.Errorf("artifact id %q gave %d", bad, st)
		}
	}
	if st, _, _ := e.rawGet("alice", "/api/runs/"+id+"/artifacts/does-not-exist"); st != 404 {
		t.Errorf("unknown artifact: %d", st)
	}
}

func TestArtifactsHostileAgentContentIsContained(t *testing.T) {
	e := newMemEnv(t, nil)
	e.connectApp("alice", true)
	id := e.startTask("alice", "octo/widgets", "make the layout responsive evilart")
	e.waitCompleted("alice", id)

	_, list := e.apiList("alice", "/api/runs/"+id+"/artifacts")
	ids := map[string]string{}
	for _, a := range list {
		ids[a["id"].(string)] = a["mime"].(string)
		if strings.Contains(a["id"].(string), "/") || strings.Contains(a["id"].(string), "..") {
			t.Errorf("traversal id survived the index: %v", a)
		}
	}
	if _, ok := ids["evil-exe"]; ok {
		t.Error("a disallowed media type was listed")
	}
	if ids["evil-html"] != "text/plain" {
		t.Errorf("html must be downgraded to text/plain in the index: %q", ids["evil-html"])
	}

	st, h, body := e.rawGet("alice", "/api/runs/"+id+"/artifacts/evil-html")
	if st != 200 || !strings.HasPrefix(h.Get("Content-Type"), "text/plain") || h.Get("X-Content-Type-Options") != "nosniff" || !strings.Contains(string(body), "<script>") {
		t.Errorf("html artifact: %d %v", st, h)
	}
	st, h, _ = e.rawGet("alice", "/api/runs/"+id+"/artifacts/evil-svg")
	if st != 200 || h.Get("Content-Type") != "image/svg+xml" || !strings.HasPrefix(h.Get("Content-Disposition"), "attachment") ||
		!strings.Contains(h.Get("Content-Security-Policy"), "sandbox") || !strings.Contains(h.Get("Content-Security-Policy"), "default-src 'none'") {
		t.Errorf("svg artifact must be an attachment under a sandbox CSP: %d %v", st, h)
	}
	for _, bad := range []string{"evil-exe", "evil-png", "big-log"} { // disallowed type, mislabelled bytes, > 5 MB
		if st, _, _ := e.rawGet("alice", "/api/runs/"+id+"/artifacts/"+bad); st != 502 {
			t.Errorf("%s should be refused with 502, got %d", bad, st)
		}
	}
}

func TestSlackSwarmUIRunMessages(t *testing.T) {
	e := newMemEnv(t, nil)
	e.connectApp("alice", true)
	e.linkSlack("alice", "U1")

	_, ack := e.slackCommand("U1", "C1", "do type:ui make the header responsive repo:octo/widgets")
	if !strings.Contains(ack["text"].(string), "On it") {
		t.Fatalf("ack: %v", ack)
	}
	var root = struct{ TS string }{}
	eventually(t, "root", func() bool { m, ok := e.rootOf("C1"); root.TS = m.TS; return ok })
	thread := root.TS
	final := e.finalMessage("C1", thread)

	c := e.agent.CreatedRuns()[0]
	if c["task_type"] != "ui" || c["task"] != "make the header responsive" || c["source"] != "slack" {
		t.Fatalf("agent request: %v", c)
	}
	// The root message was edited to show the type and the criteria counts.
	var rootText string
	for _, m := range e.slack.Messages() {
		if m.TS == thread {
			rootText = m.Text
		}
	}
	if !strings.Contains(rootText, "looking into: make the header responsive") || !strings.Contains(rootText, "Type: *ui*") || !strings.Contains(rootText, "9 hard, 1 advisory") {
		t.Fatalf("root: %q", rootText)
	}
	text := e.threadText("C1", thread)
	for _, want := range []string{"Plan: ui task, 3 units, 9 hard gates and 1 advisory", "Pull request opened (3 commits, one per unit)"} {
		if !strings.Contains(text, want) {
			t.Errorf("thread lacks %q:\n%s", want, text)
		}
	}
	// One edited message for the one round, mentioning units, agents, merge and the verify result.
	rounds := e.slack.Find("*Round ")
	if len(rounds) != 1 {
		t.Fatalf("want 1 round message, got %d", len(rounds))
	}
	for _, want := range []string{"u1 merged (variant 1 won)", "u3 merged", "Agents: ", "Merge: ok", "Verify: 9/9 hard gates pass, 1 advisory"} {
		if !strings.Contains(rounds[0].Text, want) {
			t.Errorf("round message lacks %q: %q", want, rounds[0].Text)
		}
	}

	// Final card: outcome chip, hard gates, advisory notes, buttons.
	if !strings.Contains(final.Text, "Complete") {
		t.Errorf("final text: %q", final.Text)
	}
	fb, _ := json.Marshal(final.Blocks)
	for _, want := range []string{"*Complete*", "Hard gates", "9/9 passed", "Advisory notes", "vision_rubric", "ui"} {
		if !strings.Contains(string(fb), want) {
			t.Errorf("final blocks lack %q: %s", want, fb)
		}
	}
	btns := actionIDs(final)
	if btns["open_run"] == nil || btns["pl_merge"] == nil || btns["pl_changes"] == nil {
		t.Fatalf("buttons: %v", btns)
	}
	if strings.Contains(string(fb), "partial result") {
		t.Error("a complete run must not show the partial warning")
	}
	// No token or agent secret in Slack, the run record or the logs of a swarm run.
	msgs, _ := json.Marshal(e.slack.Messages())
	run := e.getRun("alice", btns["pl_merge"]["value"].(string))
	rj, _ := json.Marshal(run)
	for _, secret := range []string{e.gh.InstallToken, e.gh.UserToken, testSecret} {
		if strings.Contains(string(msgs)+string(rj)+e.logs.String(), secret) {
			t.Fatalf("secret %q leaked (slack, run or logs)", secret)
		}
	}
}

func TestSlackRefactorRepairRoundsAndInvalidType(t *testing.T) {
	e := newMemEnv(t, nil)
	e.connectApp("alice", true)
	e.linkSlack("alice", "U1")

	_, r := e.slackCommand("U1", "C1", "do type:wizardry bake a cake repo:octo/widgets")
	if !strings.Contains(r["text"].(string), "unknown task type") {
		t.Fatalf("invalid type: %v", r)
	}
	time.Sleep(100 * time.Millisecond)
	if len(e.agent.CreatedRuns()) != 0 {
		t.Fatal("invalid type started a run")
	}

	e.slackCommand("U1", "C1", "do refactor the checkout module repo:octo/widgets")
	var rootTS string
	eventually(t, "root", func() bool { m, ok := e.rootOf("C1"); rootTS = m.TS; return ok })
	e.finalMessage("C1", rootTS)
	rounds := e.slack.Find("*Round ")
	if len(rounds) != 2 {
		t.Fatalf("want 2 round messages (repair round), got %d", len(rounds))
	}
	if !strings.Contains(rounds[0].Text, "failing: api_surface") || !strings.Contains(rounds[1].Text, "u3 merged") && !strings.Contains(rounds[1].Text, "r1 ") {
		t.Errorf("rounds: %q / %q", rounds[0].Text, rounds[1].Text)
	}
	if e.agent.CreatedRuns()[0]["task_type"] != "auto" {
		t.Errorf("no type token means auto: %v", e.agent.CreatedRuns()[0])
	}
}

func TestSlackNeedsInputReplyAnswersQuestions(t *testing.T) {
	e := newMemEnv(t, nil)
	e.connectApp("alice", true)
	e.connectApp("bob", true)
	e.linkSlack("alice", "U1")
	e.linkSlack("bob", "U2")

	e.slackCommand("U1", "C1", "do make it better, vague repo:octo/widgets")
	var rootTS string
	eventually(t, "root", func() bool { m, ok := e.rootOf("C1"); rootTS = m.TS; return ok })
	final := e.finalMessage("C1", rootTS)
	text := e.threadText("C1", rootTS)
	if !strings.Contains(text, "I need a bit more information") || !strings.Contains(text, "1. Which part of the app") || !strings.Contains(text, "2. How will you know") {
		t.Fatalf("questions not posted:\n%s", text)
	}
	fb, _ := json.Marshal(final.Blocks)
	if !strings.Contains(string(fb), "*Needs input*") || actionIDs(final)["pl_merge"] != nil {
		t.Fatalf("needs_input card: %s", fb)
	}

	reply := func(id, user, txt string) {
		e.slackEvent(map[string]any{"type": "event_callback", "event_id": id, "event": map[string]any{
			"type": "message", "user": user, "text": txt, "channel": "C1", "ts": "1700000900." + id, "thread_ts": rootTS}})
	}
	reply("000001", "U2", "1: bob answers for alice") // not the owner
	time.Sleep(150 * time.Millisecond)
	if len(e.agent.CreatedRuns()) != 1 {
		t.Fatal("a stranger answered the questions")
	}
	reply("000002", "U1", "1: the cart module\n2: totals include shipping\nand tax")
	eventually(t, "re-run with answers", func() bool { return len(e.agent.CreatedRuns()) == 2 })
	got := e.agent.CreatedRuns()[1]["answers"].(map[string]any)
	if got["q1"] != "the cart module" || got["q2"] != "totals include shipping\nand tax" {
		t.Fatalf("answers: %v", got)
	}
	eventually(t, "continuing message", func() bool {
		return strings.Contains(e.threadText("C1", rootTS), "Thanks, continuing with your answers")
	})
	eventually(t, "second final card", func() bool {
		n := 0
		for _, m := range e.inThread("C1", rootTS) {
			if actionIDs(m)["open_run"] != nil {
				n++
			}
		}
		return n == 2
	})
}

func TestSlackPartialCardWarnsOnMerge(t *testing.T) {
	e := newMemEnv(t, nil)
	e.connectApp("alice", true)
	e.linkSlack("alice", "U1")
	e.slackCommand("U1", "C1", "do type:perf make pricing feel faster partial repo:octo/widgets")
	var rootTS string
	eventually(t, "root", func() bool { m, ok := e.rootOf("C1"); rootTS = m.TS; return ok })
	final := e.finalMessage("C1", rootTS)
	fb, _ := json.Marshal(final.Blocks)
	for _, want := range []string{"*Partial*", "partial result", "Advisory notes", "stated_feels_faster"} {
		if !strings.Contains(string(fb), want) {
			t.Errorf("partial card lacks %q: %s", want, fb)
		}
	}
	btns := actionIDs(final)
	if btns["pl_merge"] == nil || !strings.Contains(btns["pl_merge"]["confirm"].(map[string]any)["text"].(map[string]any)["text"].(string), "partial result") {
		t.Fatalf("merge confirm must carry the warning: %v", btns["pl_merge"])
	}
}

func TestGitHubLabelAndCommentSetTaskType(t *testing.T) {
	e := newMemEnv(t, nil)
	e.connectApp("alice", true)

	withLabels := func(p map[string]any, names ...string) map[string]any {
		var ls []any
		for _, n := range names {
			ls = append(ls, map[string]any{"name": n})
		}
		p["issue"].(map[string]any)["labels"] = ls
		return p
	}
	// `patchloop` + `patchloop:feature` -> type feature.
	if st, _ := e.ghWebhook("issues", "d-feat", withLabels(issuePayload("labeled", "patchloop", 21), "patchloop:feature", "patchloop"), ghWebhookKey); st != 200 && st != 202 {
		t.Fatalf("webhook: %d", st)
	}
	eventually(t, "labelled run", func() bool { return len(e.agent.CreatedRuns()) == 1 })
	if e.agent.CreatedRuns()[0]["task_type"] != "feature" {
		t.Fatalf("label type: %v", e.agent.CreatedRuns()[0])
	}
	// Plain `patchloop` label -> auto.
	e.ghWebhook("issues", "d-auto", withLabels(issuePayload("labeled", "patchloop", 22), "patchloop"), ghWebhookKey)
	eventually(t, "plain run", func() bool { return len(e.agent.CreatedRuns()) == 2 })
	if e.agent.CreatedRuns()[1]["task_type"] != "auto" {
		t.Fatalf("plain label: %v", e.agent.CreatedRuns()[1])
	}
	// A type label alone starts nothing.
	e.ghWebhook("issues", "d-typeonly", withLabels(issuePayload("labeled", "patchloop:ui", 23), "patchloop:ui"), ghWebhookKey)
	// `@patchloop do type:refactor <text>` on an issue.
	e.ghWebhook("issue_comment", "d-do", commentPayload("@patchloop do type:refactor split the checkout module", "OWNER", false, 24), ghWebhookKey)
	eventually(t, "comment run", func() bool { return len(e.agent.CreatedRuns()) == 3 })
	c := e.agent.CreatedRuns()[2]
	if c["task_type"] != "refactor" || !strings.HasPrefix(c["task"].(string), "split the checkout module") || strings.Contains(c["task"].(string), "type:") {
		t.Fatalf("do comment: %v", c)
	}
	// An unknown type or an untrusted commenter is ignored.
	e.ghWebhook("issue_comment", "d-bad", commentPayload("@patchloop do type:wizardry x", "OWNER", false, 25), ghWebhookKey)
	e.ghWebhook("issue_comment", "d-rando", commentPayload("@patchloop do type:ui x", "NONE", false, 26), ghWebhookKey)
	// The legacy `@patchloop fix` still works and picks the type from the issue labels.
	p := withLabels(commentPayload("@patchloop fix", "MEMBER", false, 27), "patchloop:tests")
	e.ghWebhook("issue_comment", "d-fix", p, ghWebhookKey)
	eventually(t, "fix comment run", func() bool { return len(e.agent.CreatedRuns()) == 4 })
	if e.agent.CreatedRuns()[3]["task_type"] != "tests" {
		t.Fatalf("fix comment: %v", e.agent.CreatedRuns()[3])
	}
	time.Sleep(100 * time.Millisecond)
	if n := len(e.agent.CreatedRuns()); n != 4 {
		t.Fatalf("ignored deliveries started runs: %d", n)
	}
}
