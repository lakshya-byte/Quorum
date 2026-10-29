package app_test

import (
	"encoding/json"
	"net/url"
	"strings"
	"testing"
	"time"

	"patchloop-backend/internal/config"
	"patchloop-backend/internal/service"
	"patchloop-backend/internal/slackstub"
)

// linkSlack ties slackUser to a PatchLoop user through the real link-code flow.
func (e *memEnv) linkSlack(user, slackUser string) {
	e.t.Helper()
	st, m, raw := e.api(user, "POST", "/api/slack/link-code", nil)
	if st != 201 || m["code"] == "" {
		e.t.Fatalf("link code: %d %s", st, raw)
	}
	_, resp := e.slackCommand(slackUser, "C1", "link "+m["code"].(string))
	if !strings.Contains(resp["text"].(string), "Linked") {
		e.t.Fatalf("link: %v", resp)
	}
}

func (e *memEnv) inThread(channel, thread string) []slackstub.Message {
	var out []slackstub.Message
	for _, m := range e.slack.Messages() {
		if m.Channel == channel && m.ThreadTS == thread && m.Method == "chat.postMessage" {
			out = append(out, m)
		}
	}
	return out
}

func (e *memEnv) threadText(channel, thread string) string {
	var sb strings.Builder
	for _, m := range e.inThread(channel, thread) {
		sb.WriteString(m.Text + "\n")
	}
	return sb.String()
}

// rootOf finds the top-level "looking into" message in channel.
func (e *memEnv) rootOf(channel string) (slackstub.Message, bool) {
	for _, m := range e.slack.Messages() {
		if m.Channel == channel && m.ThreadTS == "" && strings.Contains(m.Text, "looking into") {
			return m, true
		}
	}
	return slackstub.Message{}, false
}

func actionIDs(m slackstub.Message) map[string]map[string]any {
	out := map[string]map[string]any{}
	for _, b := range m.Blocks {
		blk, _ := b.(map[string]any)
		if blk["type"] != "actions" {
			continue
		}
		for _, el := range blk["elements"].([]any) {
			btn := el.(map[string]any)
			out[btn["action_id"].(string)] = btn
		}
	}
	return out
}

func (e *memEnv) finalMessage(channel, thread string) slackstub.Message {
	e.t.Helper()
	var final slackstub.Message
	eventually(e.t, "final slack message", func() bool {
		for _, m := range e.inThread(channel, thread) {
			if actionIDs(m)["open_run"] != nil {
				final = m
				return true
			}
		}
		return false
	})
	return final
}

func click(user, channel, thread, action, value string) map[string]any {
	return map[string]any{"type": "block_actions", "user": map[string]any{"id": user}, "channel": map[string]any{"id": channel},
		"message": map[string]any{"ts": thread, "thread_ts": thread},
		"actions": []any{map[string]any{"action_id": action, "value": value}}}
}

func TestSlackRequestSignatureVerification(t *testing.T) {
	e := newMemEnv(t, nil)
	body := []byte(url.Values{"command": {"/patchloop"}, "text": {"help"}, "user_id": {"U1"}, "channel_id": {"C1"}}.Encode())

	// Valid signature works.
	if st, _ := e.slackPost("/slack/commands", "application/x-www-form-urlencoded", body); st != 200 {
		t.Fatalf("valid: %d", st)
	}
	for _, path := range []string{"/slack/commands", "/slack/events", "/slack/interactions"} {
		// No signature, wrong signature, stale timestamp, signature of another body.
		if st, _ := e.post(path, nil, body); st != 401 {
			t.Errorf("%s unsigned: %d", path, st)
		}
		ts, sig := service.SignSlackRequest("wrong-secret", body, time.Now())
		h := map[string][]string{"X-Slack-Request-Timestamp": {ts}, "X-Slack-Signature": {sig}}
		if st, _ := e.post(path, h, body); st != 401 {
			t.Errorf("%s wrong secret: %d", path, st)
		}
		ts, sig = service.SignSlackRequest(slackSigning, body, time.Now().Add(-10*time.Minute))
		h = map[string][]string{"X-Slack-Request-Timestamp": {ts}, "X-Slack-Signature": {sig}}
		if st, _ := e.post(path, h, body); st != 401 {
			t.Errorf("%s replayed (stale): %d", path, st)
		}
		ts, sig = service.SignSlackRequest(slackSigning, []byte("other"), time.Now())
		h = map[string][]string{"X-Slack-Request-Timestamp": {ts}, "X-Slack-Signature": {sig}}
		if st, _ := e.post(path, h, body); st != 401 {
			t.Errorf("%s body swapped: %d", path, st)
		}
	}
	// Without a configured signing secret the endpoints are off, never open.
	off := newMemEnv(t, func(c *config.Config) { c.SlackSigningSecret = "" })
	if st, _ := off.post("/slack/commands", nil, body); st != 503 {
		t.Fatalf("unconfigured: %d", st)
	}
	// URL verification challenge.
	st, raw := e.slackPost("/slack/events", "application/json", []byte(`{"type":"url_verification","challenge":"abc123"}`))
	if st != 200 || !strings.Contains(string(raw), `"challenge":"abc123"`) {
		t.Fatalf("challenge: %d %s", st, raw)
	}
}

func TestSlackLinkHelpAndUnlinked(t *testing.T) {
	e := newMemEnv(t, nil)
	_, r := e.slackCommand("U1", "C1", "")
	if !strings.Contains(r["text"].(string), "/patchloop fix") || r["response_type"] != "ephemeral" {
		t.Fatalf("help: %v", r)
	}
	_, r = e.slackCommand("U1", "C1", "bogus")
	if !strings.Contains(r["text"].(string), "/patchloop link") {
		t.Fatalf("unknown subcommand should show help: %v", r)
	}
	_, r = e.slackCommand("U1", "C1", "fix something is broken")
	if !strings.Contains(r["text"].(string), "not linked") {
		t.Fatalf("unlinked: %v", r)
	}
	if len(e.slack.Messages()) != 0 || len(e.agent.CreatedRuns()) != 0 {
		t.Fatal("unlinked user caused side effects")
	}
	_, r = e.slackCommand("U1", "C1", "link NOPE1234")
	if !strings.Contains(r["text"].(string), "invalid or expired") {
		t.Fatalf("bad code: %v", r)
	}
	// A code works once.
	_, m, _ := e.api("alice", "POST", "/api/slack/link-code", nil)
	code := m["code"].(string)
	_, r = e.slackCommand("U1", "C1", "link "+code)
	if !strings.Contains(r["text"].(string), "Linked") {
		t.Fatalf("link: %v", r)
	}
	_, r = e.slackCommand("U2", "C1", "link "+code)
	if !strings.Contains(r["text"].(string), "invalid or expired") {
		t.Fatalf("code reused: %v", r)
	}
	_, s, _ := e.api("alice", "GET", "/api/settings/slack", nil)
	if s["linked"] != true {
		t.Fatalf("settings linked: %v", s)
	}
}

func TestSlackFixThreadedUpdatesAndButtons(t *testing.T) {
	e := newMemEnv(t, nil)
	e.connectApp("alice", true)
	e.connectApp("bob", true) // second installation for bob is irrelevant; he just needs an account
	e.linkSlack("alice", "U1")
	e.linkSlack("bob", "U2")

	_, ack := e.slackCommand("U1", "C1", "fix pagination returns the wrong last page repo:octo/widgets")
	if !strings.Contains(ack["text"].(string), "On it") {
		t.Fatalf("ack: %v", ack)
	}
	var root slackstub.Message
	eventually(t, "root message", func() bool { var ok bool; root, ok = e.rootOf("C1"); return ok })
	thread := root.TS
	if !strings.Contains(root.Text, "pagination returns the wrong last page") || strings.Contains(root.Text, "repo:") {
		t.Fatalf("root text: %q", root.Text)
	}

	final := e.finalMessage("C1", thread)
	text := e.threadText("C1", thread)
	for _, want := range []string{"Started on `octo/widgets`", "Repo scanned", "Cause located in `src/app.py`", "offset", "Reproducer written", "Winner found", "Pull request opened: https://github.com/octo/widgets/pull/"} {
		if !strings.Contains(text, want) {
			t.Errorf("thread lacks %q:\n%s", want, text)
		}
	}
	// One message per round, edited in place: exactly 3 rounds, with candidate rows.
	rounds := 0
	for _, m := range e.inThread("C1", thread) {
		if strings.HasPrefix(m.Text, "*Round ") {
			rounds++
			if strings.Contains(m.Text, "trying candidates") {
				t.Errorf("round message never updated: %q", m.Text)
			}
		}
	}
	if rounds != 3 {
		t.Errorf("want 3 round messages, got %d", rounds)
	}
	round2 := e.slack.Find("*Round 2*")
	if len(round2) != 1 || strings.Count(round2[0].Text, "• #") != 3 {
		t.Errorf("round 2 should list 3 candidates in one message: %+v", round2)
	}

	btns := actionIDs(final)
	if btns["open_run"] == nil || btns["pl_merge"] == nil || btns["pl_changes"] == nil || btns["open_run"]["url"] == "" {
		t.Fatalf("final buttons: %v", btns)
	}
	runID := btns["pl_merge"]["value"].(string)
	run := e.waitCompleted("alice", runID)
	sl := run["slack"].(map[string]any)
	if run["source"] != "slack" || sl["channel"] != "C1" || sl["threadTs"] != thread || sl["rootTs"] != thread {
		t.Fatalf("slack ref: %v", run)
	}
	if !strings.Contains(final.Text, "PR opened") {
		t.Fatalf("final text: %q", final.Text)
	}
	eventually(t, "slackSent", func() bool { return e.getRun("alice", runID)["slackSent"] == true })

	// Ask for changes: a prompt in the thread.
	before := len(e.inThread("C1", thread))
	if st := e.slackInteraction(click("U1", "C1", thread, "pl_changes", runID)); st != 200 {
		t.Fatalf("interaction: %d", st)
	}
	eventually(t, "changes prompt", func() bool { return len(e.inThread("C1", thread)) > before })
	if !strings.Contains(e.threadText("C1", thread), "Reply in this thread") {
		t.Fatal("no prompt for changes")
	}

	// A reply from the owner in the thread asks for changes -> follow-up child run.
	reply := map[string]any{"type": "event_callback", "event_id": "Ev1", "event": map[string]any{
		"type": "message", "user": "U1", "text": "also handle page zero", "channel": "C1", "ts": "1700000500.000100", "thread_ts": thread}}
	if st := e.slackEvent(reply); st != 200 {
		t.Fatalf("event: %d", st)
	}
	eventually(t, "followup agent run", func() bool { return len(e.agent.CreatedRuns()) == 2 })
	fu := e.agent.CreatedRuns()[1]
	if fu["source"] != "slack" || fu["followup"].(map[string]any)["message"] != "also handle page zero" {
		t.Fatalf("followup request: %v", fu)
	}
	eventually(t, "pr updated message", func() bool {
		return strings.Contains(e.threadText("C1", thread), "Pull request updated with a new commit")
	})
	if !strings.Contains(e.threadText("C1", thread), "Working on your requested changes") {
		t.Fatal("no followup start message")
	}

	// Duplicate delivery, bot echo, another user's reply, plain edit: all ignored.
	e.slackEvent(reply)
	e.slackEvent(map[string]any{"type": "event_callback", "event_id": "Ev2", "event": map[string]any{
		"type": "message", "user": "U1", "bot_id": "B1", "text": "echo", "channel": "C1", "ts": "1700000500.000200", "thread_ts": thread}})
	e.slackEvent(map[string]any{"type": "event_callback", "event_id": "Ev3", "event": map[string]any{
		"type": "message", "user": "U2", "text": "bob chimes in", "channel": "C1", "ts": "1700000500.000300", "thread_ts": thread}})
	e.slackEvent(map[string]any{"type": "event_callback", "event_id": "Ev4", "event": map[string]any{
		"type": "message", "subtype": "message_changed", "user": "U1", "text": "edit", "channel": "C1", "ts": "1700000500.000400", "thread_ts": thread}})
	e.slackEvent(map[string]any{"type": "event_callback", "event_id": "Ev5", "event": map[string]any{
		"type": "message", "user": "U1", "text": "chatter elsewhere", "channel": "C1", "ts": "1700000500.000500"}})
	time.Sleep(150 * time.Millisecond)
	if n := len(e.agent.CreatedRuns()); n != 2 {
		t.Fatalf("ignored events started runs: %d agent runs", n)
	}

	// Merge button: unlinked user, non-owner, then the owner.
	e.slack.Messages()
	n := len(e.slack.Messages())
	e.slackInteraction(click("U9", "C1", thread, "pl_merge", runID))
	eventually(t, "unlinked hint", func() bool {
		for _, m := range e.slack.Messages()[n:] {
			if m.Method == "chat.postEphemeral" && m.User == "U9" && strings.Contains(m.Text, "not linked") {
				return true
			}
		}
		return false
	})
	n = len(e.slack.Messages())
	e.slackInteraction(click("U2", "C1", thread, "pl_merge", runID))
	eventually(t, "no access", func() bool {
		for _, m := range e.slack.Messages()[n:] {
			if m.Method == "chat.postEphemeral" && m.User == "U2" && strings.Contains(m.Text, "do not have access") {
				return true
			}
		}
		return false
	})
	if len(e.gh.CallsTo("PUT ")) != 0 || e.getRun("alice", runID)["merged"] != nil {
		t.Fatal("merge happened for a non-owner")
	}

	e.slackInteraction(click("U1", "C1", thread, "pl_merge", runID))
	eventually(t, "merged message", func() bool { return strings.Contains(e.threadText("C1", thread), "Merged by octo-owner") })
	puts := e.gh.CallsTo("PUT /repos/octo/widgets/pulls/")
	if len(puts) != 1 || puts[0].Auth != e.gh.UserToken {
		t.Fatalf("slack merge must use the owner's token: %+v", puts)
	}
	if e.getRun("alice", runID)["merged"] == nil {
		t.Fatal("merge not recorded")
	}
	// Clicking again is refused with the reason, in the thread.
	e.slackInteraction(click("U1", "C1", thread, "pl_merge", runID))
	eventually(t, "merge refusal", func() bool {
		return strings.Contains(e.threadText("C1", thread), "Merge refused: pull request is already merged")
	})

	// No token ever reaches Slack or the logs.
	b, _ := json.Marshal(e.slack.Messages())
	if strings.Contains(string(b), "SECRET_TOKEN") || strings.Contains(e.logs.String(), "SECRET_TOKEN") {
		t.Fatal("token leaked to Slack or logs")
	}
	for _, m := range e.slack.Messages() {
		if m.AuthToken != slackBot {
			t.Fatalf("slack call without bot token: %+v", m)
		}
	}
}

func TestSlackMentionDefaultRepoAndPicker(t *testing.T) {
	e := newMemEnv(t, nil)
	e.connectApp("alice", true) // grants octo/widgets and octo/gadgets
	e.linkSlack("alice", "U1")

	// No default repo and two granted: a picker, no run yet.
	mention := func(id, ts, text string) {
		e.slackEvent(map[string]any{"type": "event_callback", "event_id": id, "event": map[string]any{
			"type": "app_mention", "user": "U1", "text": text, "channel": "C2", "ts": ts}})
	}
	mention("EvA", "1700001000.000100", "<@UBOT> TypeError: cannot read 'len' of None in the widget parser")
	var picker slackstub.Message
	eventually(t, "repo picker", func() bool {
		for _, m := range e.inThread("C2", "1700001000.000100") {
			for _, b := range m.Blocks {
				if blk, _ := b.(map[string]any); blk != nil && blk["accessory"] != nil {
					picker = m
					return true
				}
			}
		}
		return false
	})
	if len(e.agent.CreatedRuns()) != 0 {
		t.Fatal("run started before a repo was chosen")
	}
	blk := picker.Blocks[0].(map[string]any)
	opts := blk["accessory"].(map[string]any)["options"].([]any)
	if len(opts) != 2 {
		t.Fatalf("picker options: %v", opts)
	}
	pick := map[string]any{"type": "block_actions", "user": map[string]any{"id": "U1"}, "channel": map[string]any{"id": "C2"},
		"message": map[string]any{"ts": picker.TS, "thread_ts": "1700001000.000100"},
		"actions": []any{map[string]any{"action_id": "pl_pick_repo", "block_id": blk["block_id"], "selected_option": map[string]any{"value": "octo/gadgets"}}}}

	// Someone else's click on the picker does nothing.
	other := map[string]any{"type": "block_actions", "user": map[string]any{"id": "U7"}, "channel": map[string]any{"id": "C2"},
		"message": pick["message"], "actions": pick["actions"]}
	e.slackInteraction(other)
	time.Sleep(100 * time.Millisecond)
	if len(e.agent.CreatedRuns()) != 0 {
		t.Fatal("a stranger picked the repo")
	}
	e.slackInteraction(pick)
	eventually(t, "run from picker", func() bool { return len(e.agent.CreatedRuns()) == 1 })
	c := e.agent.CreatedRuns()[0]
	if c["repo"] != "octo/gadgets" || c["branch"] != "trunk" || !strings.Contains(c["task"].(string), "TypeError") || strings.Contains(c["task"].(string), "<@") {
		t.Fatalf("picker run: %v", c)
	}
	e.finalMessage("C2", "1700001000.000100")
	// The picker is single-use.
	e.slackInteraction(pick)
	time.Sleep(100 * time.Millisecond)
	if len(e.agent.CreatedRuns()) != 1 {
		t.Fatal("picker reused")
	}

	// A duplicate delivery of the same mention is ignored.
	mention("EvA", "1700001000.000100", "<@UBOT> again")
	// Default repo: `/patchloop repo` then a fix without repo: uses it.
	_, r := e.slackCommand("U1", "C3", "repo octo/widgets")
	if !strings.Contains(r["text"].(string), "octo/widgets") {
		t.Fatalf("set repo: %v", r)
	}
	_, r = e.slackCommand("U1", "C3", "repo not-a-repo")
	if !strings.Contains(r["text"].(string), "Usage") {
		t.Fatalf("bad repo: %v", r)
	}
	e.slackCommand("U1", "C3", "fix the build is red")
	eventually(t, "default repo run", func() bool { return len(e.agent.CreatedRuns()) == 2 })
	if e.agent.CreatedRuns()[1]["repo"] != "octo/widgets" {
		t.Fatalf("default repo ignored: %v", e.agent.CreatedRuns()[1])
	}
	// A bogus explicit repo is reported in the thread, not silently dropped.
	e.slackCommand("U1", "C3", "fix thing repo:evil/hax")
	eventually(t, "not granted notice", func() bool {
		for _, m := range e.slack.Messages() {
			if strings.Contains(m.Text, "not granted to the PatchLoop GitHub App") {
				return true
			}
		}
		return false
	})
	if len(e.agent.CreatedRuns()) != 2 {
		t.Fatal("run started on an ungranted repo")
	}
}

func TestSlackSingleRepoNeedsNoPicker(t *testing.T) {
	e := newMemEnv(t, nil)
	e.api("alice", "POST", "/api/github/demo", nil)
	e.gh.Repos = e.gh.Repos[:1]
	e.connectApp("alice", true) // switches the account to the App with one repo
	e.linkSlack("alice", "U1")
	e.slackCommand("U1", "C1", "fix it is broken")
	eventually(t, "run", func() bool { return len(e.agent.CreatedRuns()) == 1 })
	if e.agent.CreatedRuns()[0]["repo"] != "octo/widgets" {
		t.Fatalf("single repo not auto-selected: %v", e.agent.CreatedRuns()[0])
	}
}

func TestSlackSettingsWebhook(t *testing.T) {
	e := newMemEnv(t, nil)
	st, m, _ := e.api("alice", "GET", "/api/settings/slack", nil)
	if st != 200 || m["configured"] != false || m["webhookUrlMasked"] != "" {
		t.Fatalf("initial: %v", m)
	}
	for _, bad := range []string{
		"https://evil.example.com/services/T000/B000/XXXXXXXX",
		"https://hooks.slack.com.evil.com/services/T000/B000/XXXXXXXX",
		"https://hooks.slack.com@evil.com/services/T000/B000/XXXXXXXX",
		"https://hooks.slack.com/services/T000/B000/X?next=http://evil",
		"http://hooks.slack.com/services/T000/B000/XXXXXXXX",
		"http://169.254.169.254/latest/meta-data/",
		"http://localhost:8080/../../admin",
		"file:///etc/passwd",
		"",
	} {
		st, m, _ := e.api("alice", "PUT", "/api/settings/slack", map[string]any{"webhookUrl": bad})
		if st != 400 || m["code"] != "bad_request" {
			t.Errorf("%q accepted: %d %v", bad, st, m)
		}
	}
	good := "https://hooks.slack.com/services/T000/B000/ABCDEFGH1234"
	st, m, _ = e.api("alice", "PUT", "/api/settings/slack", map[string]any{"webhookUrl": good})
	if st != 200 || m["configured"] != true || m["webhookUrlMasked"] != "https://hooks.slack.com/…1234" {
		t.Fatalf("put: %d %v", st, m)
	}
	// Never returned in full, never stored in plaintext.
	_, _, raw := e.api("alice", "GET", "/api/settings/slack", nil)
	if strings.Contains(string(raw), "ABCDEFGH") {
		t.Fatalf("webhook leaked: %s", raw)
	}
	set, _ := e.store.GetSettings(nil, "u-alice")
	if strings.Contains(set.EncWebhook, "hooks.slack.com") || set.EncWebhook == "" {
		t.Fatalf("webhook not encrypted: %q", set.EncWebhook)
	}
	// Loopback is accepted in DEV_MODE only (e2e capture server), then used by /test.
	if st, _, _ := e.api("alice", "PUT", "/api/settings/slack", map[string]any{"webhookUrl": e.hookURL}); st != 200 {
		t.Fatalf("dev loopback webhook: %d", st)
	}
	st, m, _ = e.api("alice", "POST", "/api/settings/slack/test", nil)
	if st != 200 || m["ok"] != true {
		t.Fatalf("test: %d %v", st, m)
	}
	eventually(t, "test card", func() bool { return len(e.hook.get()) == 1 })
	card, _ := json.Marshal(e.hook.get()[0])
	if !strings.Contains(string(card), "PatchLoop") || !strings.Contains(string(card), "blocks") {
		t.Fatalf("test card: %s", card)
	}
	// Delete clears it; test then reports the missing webhook.
	st, m, _ = e.api("alice", "DELETE", "/api/settings/slack", nil)
	if st != 200 || m["configured"] != false {
		t.Fatalf("delete: %d %v", st, m)
	}
	if st, m, _ := e.api("alice", "POST", "/api/settings/slack/test", nil); st != 409 {
		t.Fatalf("test without webhook: %d %v", st, m)
	}
	// Auth is required and settings are per user.
	if st, _, _ := e.api("", "PUT", "/api/settings/slack", map[string]any{"webhookUrl": good}); st != 401 {
		t.Fatalf("anonymous put: %d", st)
	}
	_, m, _ = e.api("bob", "GET", "/api/settings/slack", nil)
	if m["configured"] != false {
		t.Fatalf("bob sees alice's webhook: %v", m)
	}
}

func TestSlackWebhookStrictOutsideDevMode(t *testing.T) {
	e := newMemEnv(t, func(c *config.Config) { c.DevMode = false })
	if st, _, _ := e.api("alice", "PUT", "/api/settings/slack", map[string]any{"webhookUrl": e.hookURL}); st != 400 {
		t.Fatalf("loopback accepted outside DEV_MODE: %d", st)
	}
	if st, _, _ := e.api("alice", "PUT", "/api/settings/slack", map[string]any{"webhookUrl": "https://hooks.slack.com/services/T000/B000/ABCDEFGH1234"}); st != 200 {
		t.Fatalf("real webhook rejected: %d", st)
	}
}

func TestWebhookDestinationUserThenGlobalThenNone(t *testing.T) {
	// Global webhook only: used for users without their own.
	e := newMemEnv(t, func(c *config.Config) { c.SlackWebhookURL = "USE_HOOK" })
	e.connectApp("alice", true)
	e.waitCompleted("alice", e.startTask("alice", "octo/widgets", "fix it"))
	eventually(t, "global webhook card", func() bool { return len(e.hook.get()) == 1 })

	// No webhook at all: completes quietly and a failing Slack never fails the run.
	n := newMemEnv(t, nil)
	n.connectApp("alice", true)
	run := n.waitCompleted("alice", n.startTask("alice", "octo/widgets", "fix it"))
	time.Sleep(50 * time.Millisecond)
	if len(n.hook.get()) != 0 || run["solved"] != true {
		t.Fatalf("unexpected: %v %v", n.hook.get(), run)
	}

	// A user webhook that errors does not fail the run.
	b := newMemEnv(t, nil)
	b.connectApp("alice", true)
	b.api("alice", "PUT", "/api/settings/slack", map[string]any{"webhookUrl": "http://127.0.0.1:1/dead"})
	run = b.waitCompleted("alice", b.startTask("alice", "octo/widgets", "fix it"))
	if run["solved"] != true || run["prUrl"] == "" {
		t.Fatalf("run affected by dead webhook: %v", run)
	}
	time.Sleep(100 * time.Millisecond)
	if b.getRun("alice", run["id"].(string))["slackSent"] != false {
		t.Fatal("slackSent set although the post failed")
	}
}
