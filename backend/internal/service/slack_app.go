package service

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/url"
	"regexp"
	"strings"
	"sync"
	"time"

	"patchloop-backend/internal/models"
)

const slackHelp = "*PatchLoop commands*\n" +
	"• `/patchloop fix <problem>` (add `repo:owner/name` to pick a repo)\n" +
	"• `/patchloop repo owner/name` sets your default repo\n" +
	"• `/patchloop link <code>` connects Slack to your PatchLoop account (get the code on the Integrations page)\n" +
	"• Or mention `@PatchLoop` with a pasted error. Reply in a run's thread to ask for changes."

const slackLinkHint = "Your Slack user is not linked to a PatchLoop account yet. Open the PatchLoop *Integrations* page, create a link code, then run `/patchloop link <code>`."

var (
	repoTokenPattern = regexp.MustCompile(`(?i)\brepo:([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)`)
	mentionPattern   = regexp.MustCompile(`<@[A-Z0-9]+(\|[^>]*)?>`)
)

type pendingFix struct {
	userID, slackUserID, problem, channel, threadTS string
	expires                                         time.Time
}

// SlackApp is the Slack workspace app: slash command, events, interactive
// buttons, threaded run updates. It uses a single bot token (hackathon scope).
type SlackApp struct {
	SigningSecret string
	api           *SlackAPI
	settings      *SlackSettingsService
	runs          *RunService
	merge         *MergeService
	github        *GitHubService
	dedupe        DedupeStore

	mu      sync.Mutex
	pending map[string]pendingFix
	now     func() time.Time
	// Sync makes handlers run their async work inline (tests).
	Sync bool
}

func NewSlackApp(signingSecret string, api *SlackAPI, settings *SlackSettingsService, runs *RunService, merge *MergeService, github *GitHubService, dedupe DedupeStore) *SlackApp {
	return &SlackApp{SigningSecret: signingSecret, api: api, settings: settings, runs: runs, merge: merge, github: github,
		dedupe: dedupe, pending: map[string]pendingFix{}, now: time.Now}
}

// Enabled reports whether Slack requests can be verified at all.
func (a *SlackApp) Enabled() bool { return a != nil && a.SigningSecret != "" }

func (a *SlackApp) Verify(timestamp, signature string, body []byte) error {
	return VerifySlackSignature(a.SigningSecret, timestamp, signature, body, a.now())
}

func (a *SlackApp) async(f func()) {
	if a.Sync {
		f()
		return
	}
	go f()
}

func bg() (context.Context, context.CancelFunc) {
	return context.WithTimeout(context.Background(), 60*time.Second)
}

// ---- slash command --------------------------------------------------------

type SlackCommand struct {
	Command, Text, UserID, ChannelID string
}

func ephemeral(text string) map[string]any {
	return map[string]any{"response_type": "ephemeral", "text": text}
}

// HandleCommand answers within Slack's 3s budget; real work runs async.
func (a *SlackApp) HandleCommand(ctx context.Context, cmd SlackCommand) map[string]any {
	text := strings.TrimSpace(cmd.Text)
	sub, rest, _ := strings.Cut(text, " ")
	rest = strings.TrimSpace(rest)
	switch strings.ToLower(sub) {
	case "link":
		if rest == "" {
			return ephemeral("Usage: `/patchloop link <code>`")
		}
		if err := a.settings.Link(ctx, cmd.UserID, rest); err != nil {
			if errors.Is(err, ErrBadCode) {
				return ephemeral(err.Error())
			}
			return ephemeral("Could not link your account, please retry.")
		}
		return ephemeral("Linked. You can now use `/patchloop fix <problem>`.")
	case "repo":
		userID := a.settings.UserFor(ctx, cmd.UserID)
		if userID == "" {
			return ephemeral(slackLinkHint)
		}
		if !ValidRepoName(rest) {
			return ephemeral("Usage: `/patchloop repo owner/name`")
		}
		if err := a.settings.SetDefaultRepo(ctx, userID, rest); err != nil {
			return ephemeral("Could not save your default repo.")
		}
		return ephemeral("Default repo set to `" + rest + "`.")
	case "fix":
		userID := a.settings.UserFor(ctx, cmd.UserID)
		if userID == "" {
			return ephemeral(slackLinkHint)
		}
		if rest == "" {
			return ephemeral("Describe the problem: `/patchloop fix pagination returns the wrong last page`")
		}
		if !a.api.Enabled() {
			return ephemeral("The PatchLoop Slack bot token is not configured on this server.")
		}
		a.async(func() {
			c, cancel := bg()
			defer cancel()
			a.startFromSlack(c, userID, cmd.UserID, cmd.ChannelID, "", rest)
		})
		return ephemeral("On it. Follow the thread PatchLoop is about to start in this channel.")
	default:
		return ephemeral(slackHelp)
	}
}

// ---- events ---------------------------------------------------------------

// HandleEvent processes an Events API body. For url_verification it returns
// the challenge to echo.
func (a *SlackApp) HandleEvent(ctx context.Context, body []byte) (challenge string, err error) {
	var env struct {
		Type      string `json:"type"`
		Challenge string `json:"challenge"`
		EventID   string `json:"event_id"`
		Event     struct {
			Type     string `json:"type"`
			User     string `json:"user"`
			BotID    string `json:"bot_id"`
			Subtype  string `json:"subtype"`
			Text     string `json:"text"`
			Channel  string `json:"channel"`
			TS       string `json:"ts"`
			ThreadTS string `json:"thread_ts"`
		} `json:"event"`
	}
	if err := json.Unmarshal(body, &env); err != nil {
		return "", errors.New("bad event body")
	}
	if env.Type == "url_verification" {
		return env.Challenge, nil
	}
	ev := env.Event
	if env.Type != "event_callback" || ev.User == "" || ev.BotID != "" || ev.Subtype != "" {
		return "", nil // our own messages, edits, joins ...
	}
	if ev.Type != "app_mention" && ev.Type != "message" {
		return "", nil
	}
	// Slack retries and may send both app_mention and message for one post.
	for _, key := range []string{"slack-event:" + env.EventID, "slack-msg:" + ev.Channel + ":" + ev.TS} {
		if env.EventID == "" && strings.HasPrefix(key, "slack-event:") {
			continue
		}
		if a.dedupe != nil {
			if seen, err := a.dedupe.Seen(ctx, key); err == nil && seen {
				return "", nil
			}
		}
	}
	text := strings.TrimSpace(mentionPattern.ReplaceAllString(ev.Text, ""))
	a.async(func() {
		c, cancel := bg()
		defer cancel()
		a.onMessage(c, ev.Type, ev.User, ev.Channel, ev.TS, ev.ThreadTS, text)
	})
	return "", nil
}

func (a *SlackApp) onMessage(ctx context.Context, evType, slackUser, channel, ts, threadTS, text string) {
	if text == "" {
		return
	}
	userID := a.settings.UserFor(ctx, slackUser)
	// A message inside a thread that PatchLoop owns is a follow-up request.
	if threadTS != "" {
		if run, err := a.runs.FindBySlackThread(ctx, channel, threadTS); err == nil {
			if userID == "" || run.UserID != userID {
				if evType == "app_mention" {
					_ = a.api.PostEphemeral(ctx, channel, slackUser, threadTS, "Only the person who started this run can ask for changes (link your account with `/patchloop link <code>`).")
				}
				return
			}
			if run.Status != models.RunStatusCompleted || run.PRNumber == 0 {
				_ = a.api.PostEphemeral(ctx, channel, slackUser, threadTS, "The run has no pull request yet; changes can be requested once the PR is open.")
				return
			}
			child, err := a.runs.Followup(ctx, run, models.SourceSlack, text, nil)
			if err != nil {
				_, _ = a.api.PostMessage(ctx, channel, threadTS, "Could not start the follow-up: "+slackEscape(err.Error()), nil)
				return
			}
			_ = child
			return
		}
	}
	if evType != "app_mention" {
		return // plain channel chatter that is not for us
	}
	if userID == "" {
		_ = a.api.PostEphemeral(ctx, channel, slackUser, threadTS, slackLinkHint)
		return
	}
	thread := threadTS
	if thread == "" {
		thread = ts
	}
	a.startFromSlack(ctx, userID, slackUser, channel, thread, text)
}

// ---- starting a run from Slack --------------------------------------------

// startFromSlack resolves the repo and starts the run. threadTS == "" means
// "create a top-level root message" (slash command); otherwise the root is a
// reply in that thread (mention).
func (a *SlackApp) startFromSlack(ctx context.Context, userID, slackUser, channel, threadTS, problem string) {
	repo := ""
	if m := repoTokenPattern.FindStringSubmatch(problem); m != nil {
		repo = m[1]
		problem = strings.TrimSpace(repoTokenPattern.ReplaceAllString(problem, ""))
	}
	if problem == "" {
		_ = a.api.PostEphemeral(ctx, channel, slackUser, threadTS, "Tell me what is wrong, e.g. `/patchloop fix pagination returns the wrong last page`.")
		return
	}
	// Root message: the thread everything else hangs off.
	rootText := "PatchLoop is looking into: " + slackEscape(truncate(problem, 200))
	rootTS, err := a.api.PostMessage(ctx, channel, threadTS, rootText, nil)
	if err != nil {
		slog.Error("slack root message failed", "error", err.Error())
		return
	}
	if threadTS == "" {
		threadTS = rootTS
	}

	if repo == "" {
		repo = a.settings.DefaultRepo(ctx, userID)
	}
	if repo == "" {
		repos, err := a.github.Repos(ctx, userID, "")
		if err != nil {
			a.say(ctx, channel, threadTS, "Could not list your repositories: "+slackEscape(errMsg(err)))
			return
		}
		switch len(repos) {
		case 0:
			a.say(ctx, channel, threadTS, "PatchLoop has no repositories yet. Install the GitHub App on a repo, then retry.")
			return
		case 1:
			repo = repos[0].FullName
		default:
			a.askRepo(ctx, userID, slackUser, channel, threadTS, problem, repos)
			return
		}
	}
	a.launch(ctx, userID, channel, threadTS, rootTS, repo, problem)
}

func errMsg(err error) string {
	var ae *AgentError
	if errors.As(err, &ae) {
		return ae.Message
	}
	return err.Error()
}

func (a *SlackApp) say(ctx context.Context, channel, threadTS, text string) {
	if _, err := a.api.PostMessage(ctx, channel, threadTS, text, nil); err != nil {
		slog.Error("slack post failed", "error", err.Error())
	}
}

func (a *SlackApp) launch(ctx context.Context, userID, channel, threadTS, rootTS, repo, problem string) {
	_, err := a.runs.StartRepoRun(ctx, RepoRunInput{
		UserID: userID, Repo: repo, Task: problem, Source: models.SourceSlack, AutoPR: true,
		Slack: &models.SlackRef{Channel: channel, ThreadTS: threadTS, RootTS: rootTS},
	})
	if err != nil {
		a.say(ctx, channel, threadTS, "Could not start the run: "+slackEscape(errMsg(err)))
	}
}

func (a *SlackApp) askRepo(ctx context.Context, userID, slackUser, channel, threadTS, problem string, repos []GitHubRepo) {
	idb := make([]byte, 6)
	_, _ = rand.Read(idb)
	id := hex.EncodeToString(idb)
	a.mu.Lock()
	for k, p := range a.pending {
		if a.now().After(p.expires) {
			delete(a.pending, k)
		}
	}
	a.pending[id] = pendingFix{userID: userID, slackUserID: slackUser, problem: problem, channel: channel, threadTS: threadTS, expires: a.now().Add(15 * time.Minute)}
	a.mu.Unlock()

	if len(repos) > 100 {
		repos = repos[:100]
	}
	opts := make([]map[string]any, 0, len(repos))
	for _, r := range repos {
		opts = append(opts, map[string]any{"text": map[string]any{"type": "plain_text", "text": truncate(r.FullName, 70)}, "value": r.FullName})
	}
	blocks := []map[string]any{
		{"type": "section", "block_id": id, "text": map[string]any{"type": "mrkdwn", "text": "Which repository should I look at?"},
			"accessory": map[string]any{"type": "static_select", "action_id": "pl_pick_repo",
				"placeholder": map[string]any{"type": "plain_text", "text": "Choose a repo"}, "options": opts}},
	}
	if _, err := a.api.PostMessage(ctx, channel, threadTS, "Which repository should I look at?", blocks); err != nil {
		slog.Error("slack repo picker failed", "error", err.Error())
	}
}

// ---- interactions ---------------------------------------------------------

// HandleInteraction processes a block_actions payload (form field `payload`).
func (a *SlackApp) HandleInteraction(ctx context.Context, payload []byte) error {
	var p struct {
		Type string `json:"type"`
		User struct {
			ID string `json:"id"`
		} `json:"user"`
		Channel struct {
			ID string `json:"id"`
		} `json:"channel"`
		Message struct {
			TS       string `json:"ts"`
			ThreadTS string `json:"thread_ts"`
		} `json:"message"`
		Actions []struct {
			ActionID       string `json:"action_id"`
			BlockID        string `json:"block_id"`
			Value          string `json:"value"`
			SelectedOption struct {
				Value string `json:"value"`
			} `json:"selected_option"`
		} `json:"actions"`
	}
	if err := json.Unmarshal(payload, &p); err != nil {
		return errors.New("bad interaction payload")
	}
	if p.Type != "block_actions" || len(p.Actions) == 0 {
		return nil
	}
	act := p.Actions[0]
	thread := p.Message.ThreadTS
	if thread == "" {
		thread = p.Message.TS
	}
	a.async(func() {
		c, cancel := bg()
		defer cancel()
		switch act.ActionID {
		case "pl_merge":
			a.onMerge(c, p.User.ID, p.Channel.ID, thread, act.Value)
		case "pl_changes":
			a.say(c, p.Channel.ID, thread, "Reply in this thread with what you would like changed, and PatchLoop will push a new commit to the same pull request.")
		case "pl_pick_repo":
			a.onPickRepo(c, p.User.ID, p.Channel.ID, p.Message.TS, act.BlockID, act.SelectedOption.Value)
		}
	})
	return nil
}

func (a *SlackApp) onMerge(ctx context.Context, slackUser, channel, thread, runID string) {
	userID := a.settings.UserFor(ctx, slackUser)
	if userID == "" {
		_ = a.api.PostEphemeral(ctx, channel, slackUser, thread, slackLinkHint)
		return
	}
	// GetOwned: the clicking user must own the run.
	run, err := a.runs.GetOwned(ctx, runID, userID)
	if err != nil {
		_ = a.api.PostEphemeral(ctx, channel, slackUser, thread, "You do not have access to that run.")
		return
	}
	res, err := a.merge.Merge(ctx, run, userID, "squash")
	if err != nil {
		var mr *MergeRefusedError
		if errors.As(err, &mr) {
			a.say(ctx, channel, thread, "Merge refused: "+slackEscape(mr.Reason))
		} else {
			a.say(ctx, channel, thread, "Merge failed: "+slackEscape(errMsg(err)))
		}
		return
	}
	msg := fmt.Sprintf("Merged by %s (squash): %s", slackEscape(res.By), run.PRURL)
	if res.Warning != "" {
		msg += " (note: " + res.Warning + ")"
	}
	a.say(ctx, channel, thread, msg)
}

func (a *SlackApp) onPickRepo(ctx context.Context, slackUser, channel, messageTS, pendingID, repo string) {
	a.mu.Lock()
	p, ok := a.pending[pendingID]
	if ok && a.now().After(p.expires) {
		ok = false
	}
	if ok && p.slackUserID == slackUser {
		delete(a.pending, pendingID)
	} else if ok {
		ok = false // someone else clicked
	}
	a.mu.Unlock()
	if !ok {
		_ = a.api.PostEphemeral(ctx, channel, slackUser, "", "That repo picker expired or belongs to someone else. Start again with `/patchloop fix`.")
		return
	}
	if !ValidRepoName(repo) {
		return
	}
	_ = a.api.UpdateMessage(ctx, p.channel, messageTS, "Using `"+repo+"`.", nil)
	a.launch(ctx, p.userID, p.channel, p.threadTS, p.threadTS, repo, p.problem)
}

// ---- RunObserver ----------------------------------------------------------

func (a *SlackApp) RunStarted(run *models.Run) {
	if !a.api.Enabled() || run.Slack == nil {
		return
	}
	cp := *run
	a.async(func() { a.watch(&cp) })
}

// watch turns the agent's event stream into threaded Slack updates.
func (a *SlackApp) watch(run *models.Run) {
	ctx, cancel := context.WithTimeout(context.Background(), 45*time.Minute)
	defer cancel()
	ref := run.Slack
	say := func(text string) { a.say(ctx, ref.Channel, ref.ThreadTS, text) }

	if run.ParentRunID != "" {
		say("Working on your requested changes. I will push one new commit to the same pull request.")
	} else {
		say(fmt.Sprintf("Started on `%s` (%s). Live view: %s", run.Repo, run.Branch, a.runs.RunURL(run)))
	}

	var (
		roundTS   string
		roundN    int
		roundRows []string
		cause     string
	)
	flushRound := func() {
		if roundTS == "" {
			return
		}
		text := fmt.Sprintf("*Round %d*\n%s", roundN, strings.Join(roundRows, "\n"))
		if err := a.api.UpdateMessage(ctx, ref.Channel, roundTS, text, nil); err != nil {
			slog.Warn("slack round update failed", "error", err.Error())
		}
	}
	err := a.runs.Agent().StreamEvents(ctx, run.AgentRunID, func(typ string, d map[string]any) bool {
		switch typ {
		case "repo":
			say(fmt.Sprintf("Repo scanned: %v files, language %v, tests: `%v`", d["files"], d["language"], d["test_command"]))
		case "triage":
			if c, ok := d["cause"].(string); ok {
				cause = c
			}
		case "locate":
			files := []string{}
			if fs, ok := d["files"].([]any); ok {
				for _, f := range fs {
					if m, ok := f.(map[string]any); ok {
						files = append(files, fmt.Sprintf("`%v`", m["path"]))
					}
				}
			}
			t := "Cause located in " + strings.Join(files, ", ")
			if cause != "" {
				t += ": " + slackEscape(truncate(cause, 300))
			}
			say(t)
		case "repro":
			if d["failed_on_original"] == true {
				say(fmt.Sprintf("Reproducer written: `%v` (fails on the original code)", d["test_name"]))
			} else {
				say("Could not write a reproducer that fails on the original code; using the existing tests.")
			}
		case "round":
			flushRound()
			n, _ := toInt(d["depth"])
			roundN, roundRows = n+1, nil
			ts, err := a.api.PostMessage(ctx, ref.Channel, ref.ThreadTS, fmt.Sprintf("*Round %d*\ntrying candidates…", roundN), nil)
			if err == nil {
				roundTS = ts
			}
		case "node":
			p, _ := toInt(d["passed"])
			t, _ := toInt(d["total"])
			idea, _ := d["idea"].(string)
			roundRows = append(roundRows, fmt.Sprintf("• #%v %s: %d/%d tests", d["id"], slackEscape(truncate(idea, 80)), p, t))
			flushRound()
		case "done":
			flushRound()
			if d["solved"] == true {
				say("Winner found: a candidate passes the reproducer and the full existing suite.")
			} else {
				say("No candidate passed all tests.")
			}
		case "pr":
			u, _ := d["url"].(string)
			if d["updated"] == true {
				say("Pull request updated with a new commit: " + u)
			} else {
				say("Pull request opened: " + u)
			}
		case "error":
			say("The run hit an error: " + slackEscape(fmt.Sprint(d["message"])))
		}
		return true
	})
	flushRound()
	if err != nil && ctx.Err() == nil {
		slog.Warn("slack watcher ended", "error", err.Error())
	}
}

// RunCompleted posts the final Block Kit message with Review / Merge / Ask
// for changes buttons.
func (a *SlackApp) RunCompleted(ctx context.Context, run *models.Run) {
	if !a.api.Enabled() || run.Slack == nil {
		return
	}
	cp := *run
	a.async(func() {
		c, cancel := bg()
		defer cancel()
		tests := "n/a"
		if p, t, ok := TestsPassed(&cp); ok {
			tests = fmt.Sprintf("%d/%d passed", p, t)
		}
		buttons := []map[string]any{{
			"type": "button", "action_id": "open_run", "text": map[string]any{"type": "plain_text", "text": "Review"}, "url": a.runs.RunURL(&cp)}}
		if cp.PRURL != "" && cp.Solved {
			buttons[0]["url"] = cp.PRURL
			buttons = append(buttons,
				map[string]any{"type": "button", "style": "primary", "action_id": "pl_merge", "value": cp.ID.Hex(),
					"text":    map[string]any{"type": "plain_text", "text": "Merge"},
					"confirm": map[string]any{"title": map[string]any{"type": "plain_text", "text": "Merge this PR?"}, "text": map[string]any{"type": "mrkdwn", "text": "Merges with your GitHub permissions once checks are green."}, "confirm": map[string]any{"type": "plain_text", "text": "Merge"}, "deny": map[string]any{"type": "plain_text", "text": "Cancel"}}},
				map[string]any{"type": "button", "action_id": "pl_changes", "value": cp.ID.Hex(),
					"text": map[string]any{"type": "plain_text", "text": "Ask for changes"}})
		}
		blocks := []map[string]any{
			{"type": "section", "text": map[string]any{"type": "mrkdwn", "text": "*" + RepoResultText(&cp) + "*\n>" + slackEscape(truncate(cp.Task, 280))}},
			{"type": "section", "fields": []map[string]any{
				{"type": "mrkdwn", "text": "*Repo*\n" + slackEscape(cp.Repo)},
				{"type": "mrkdwn", "text": "*Proof*\n" + tests + " over " + fmt.Sprint(len(cp.Nodes)) + " attempts"},
			}},
			{"type": "context", "elements": []map[string]any{{"type": "mrkdwn", "text": "Agents cannot merge. A human reviews and merges."}}},
			{"type": "actions", "elements": buttons},
		}
		text := "PatchLoop: " + RepoResultText(&cp)
		if _, err := a.api.PostMessage(c, cp.Slack.Channel, cp.Slack.ThreadTS, text, blocks); err != nil {
			slog.Error("slack final message failed", "error", err.Error())
			return
		}
		_ = a.runs.runs.SetSlackSent(c, cp.ID.Hex())
	})
}

// BotConfigured reports whether threaded updates are possible.
func (a *SlackApp) BotConfigured() bool { return a.api.Enabled() }

// LinkEscape is exported for tests that build Slack form bodies.
func LinkEscape(s string) string { return url.QueryEscape(s) }
