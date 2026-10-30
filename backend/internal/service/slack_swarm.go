package service

import (
	"context"
	"fmt"
	"log/slog"
	"net/url"
	"regexp"
	"strings"
	"time"

	"patchloop-backend/internal/models"
)

// ---- RunObserver ----------------------------------------------------------

func (a *SlackApp) RunStarted(run *models.Run) {
	if !a.api.Enabled() || run.Slack == nil {
		return
	}
	cp := *run
	a.async(func() { a.watch(&cp) })
}

// roundView is the single thread message of one verification round; it is
// created when the round's first unit starts and edited (never re-posted) on
// every unit/merge/verify event.
type roundView struct {
	n       int
	ts      string
	units   map[string]string
	order   []string
	spawned int
	running map[string]bool
	merge   string
	verify  string
}

func (r *roundView) text(label string) string {
	var rows []string
	if len(r.order) > 0 {
		parts := make([]string, 0, len(r.order))
		for _, id := range r.order {
			parts = append(parts, fmt.Sprintf("%s %s", id, r.units[id]))
		}
		rows = append(rows, "• Units: "+strings.Join(parts, ", "))
	}
	rows = append(rows, fmt.Sprintf("• Agents: %d spawned, %d running", r.spawned, len(r.running)))
	if r.merge != "" {
		rows = append(rows, "• Merge: "+r.merge)
	}
	if r.verify != "" {
		rows = append(rows, "• Verify: "+r.verify)
	}
	return fmt.Sprintf("*%s %d*\n%s", label, r.n, strings.Join(rows, "\n"))
}

// watch turns the agent's event stream into threaded Slack updates.
func (a *SlackApp) watch(run *models.Run) {
	ctx, cancel := context.WithTimeout(context.Background(), 45*time.Minute)
	defer cancel()
	ref := run.Slack
	say := func(text string) { a.say(ctx, ref.Channel, ref.ThreadTS, text) }

	switch {
	case run.Answered:
		say("Thanks, continuing with your answers.")
	case run.ParentRunID != "":
		say("Working on your requested changes. I will push one new commit to the same pull request.")
	default:
		say(fmt.Sprintf("Started on `%s` (%s). Live view: %s", run.Repo, run.Branch, a.runs.RunURL(run)))
	}

	var (
		roundTS   string
		roundN    int
		roundRows []string
		cause     string

		swarm  bool       // unit/worker events seen: render swarm rounds, not legacy candidate rounds
		rounds int        // swarm rounds started
		cur    *roundView // the open swarm round, nil between rounds
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
	flushSwarm := func() {
		if cur == nil || cur.ts == "" {
			return
		}
		if err := a.api.UpdateMessage(ctx, ref.Channel, cur.ts, cur.text("Round"), nil); err != nil {
			slog.Warn("slack round update failed", "error", err.Error())
		}
	}
	// ensureRound opens the round's message on the round's first unit/worker event.
	ensureRound := func() {
		if cur != nil {
			return
		}
		rounds++
		cur = &roundView{n: rounds, units: map[string]string{}, running: map[string]bool{}}
		ts, err := a.api.PostMessage(ctx, ref.Channel, ref.ThreadTS, fmt.Sprintf("*Round %d*\nstarting workers…", rounds), nil)
		if err == nil {
			cur.ts = ts
		}
	}
	// Only agents spawned inside a round are counted in its message; the
	// planner/mapper/spec agents belong to no round.
	agentsSeen := map[string]bool{}

	err := a.runs.Agent().StreamEvents(ctx, run.AgentRunID, func(typ string, d map[string]any) bool {
		switch typ {
		case "repo":
			say(fmt.Sprintf("Repo scanned: %v files, language %v, tests: `%v`", d["files"], d["language"], d["test_command"]))
		case "plan":
			say(a.planLine(d))
			a.updateRoot(ctx, run, d)
		case "clarify":
			say(clarifyText(d))
		case "agent":
			id, _ := d["id"].(string)
			role, _ := d["role"].(string)
			status, _ := d["status"].(string)
			if (role == "worker" || role == "integrator") && (status == "spawned" || status == "running") {
				swarm = true
				ensureRound()
			}
			if status == "spawned" && id != "" && !agentsSeen[id] {
				agentsSeen[id] = true
				if cur != nil {
					cur.spawned++
				}
			}
			if cur != nil && id != "" && (role == "worker" || role == "integrator") {
				switch status {
				case "running", "spawned":
					cur.running[id] = true
				default:
					delete(cur.running, id)
				}
			}
		case "unit":
			swarm = true
			ensureRound()
			id, _ := d["id"].(string)
			status, _ := d["status"].(string)
			if id != "" {
				if _, ok := cur.units[id]; !ok {
					cur.order = append(cur.order, id)
				}
				label := status
				if w, ok := toInt(d["winner_variant"]); ok && status == "passed" {
					label = fmt.Sprintf("passed (variant %d won)", w)
				}
				cur.units[id] = label
			}
			flushSwarm()
		case "merge":
			if cur != nil {
				cur.merge = mergeLine(d)
				flushSwarm()
			}
		case "verify":
			if cur != nil {
				cur.verify = verifyLine(d)
				flushSwarm()
				cur = nil // the next unit event starts the next round
			}
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
			if swarm {
				break
			}
			flushRound()
			n, _ := toInt(d["depth"])
			roundN, roundRows = n+1, nil
			ts, err := a.api.PostMessage(ctx, ref.Channel, ref.ThreadTS, fmt.Sprintf("*Round %d*\ntrying candidates…", roundN), nil)
			if err == nil {
				roundTS = ts
			}
		case "node":
			if swarm {
				break
			}
			p, _ := toInt(d["passed"])
			t, _ := toInt(d["total"])
			idea, _ := d["idea"].(string)
			roundRows = append(roundRows, fmt.Sprintf("• #%v %s: %d/%d tests", d["id"], slackEscape(truncate(idea, 80)), p, t))
			flushRound()
		case "done":
			flushRound()
			flushSwarm()
			outcome, _ := d["outcome"].(string)
			switch {
			case outcome == models.OutcomeNeedsInput:
				// the questions were posted when clarify arrived
			case swarm:
				say(doneLine(d))
			case d["solved"] == true:
				say("Winner found: a candidate passes the reproducer and the full existing suite.")
			default:
				say("No candidate passed all tests.")
			}
		case "pr":
			u, _ := d["url"].(string)
			commits := ""
			if n, ok := toInt(d["commits"]); ok && n > 1 {
				commits = fmt.Sprintf(" (%d commits, one per unit)", n)
			}
			if d["updated"] == true {
				say("Pull request updated with a new commit: " + u)
			} else {
				say("Pull request opened" + commits + ": " + u)
			}
		case "error":
			say("The run hit an error: " + slackEscape(fmt.Sprint(d["message"])))
		}
		return true
	})
	flushRound()
	flushSwarm()
	if err != nil && ctx.Err() == nil {
		slog.Warn("slack watcher ended", "error", err.Error())
	}
}

// planLine summarises the plan event for the thread.
func (a *SlackApp) planLine(d map[string]any) string {
	hard, adv := countCriteria(d)
	units := 0
	if us, ok := d["units"].([]any); ok {
		units = len(us)
	}
	t := fmt.Sprintf("Plan: %s task, %d units, %d hard gates", orStr(d["task_type"], "task"), units, hard)
	if adv > 0 {
		t += fmt.Sprintf(" and %d advisory checks", adv)
	}
	if sw, ok := d["swarm"].(map[string]any); ok {
		if n, ok := toInt(sw["workers_planned"]); ok && n > 0 {
			t += fmt.Sprintf("; %d workers planned", n)
		}
		if n, ok := toInt(sw["max_parallel"]); ok && n > 0 {
			t += fmt.Sprintf(", up to %d in parallel", n)
		}
	}
	if s, ok := d["summary"].(string); ok && s != "" {
		t += "\n>" + slackEscape(truncate(s, 280))
	}
	return t
}

func orStr(v any, def string) string {
	if s, ok := v.(string); ok && s != "" {
		return s
	}
	return def
}

func countCriteria(plan map[string]any) (hard, advisory int) {
	cs, _ := plan["criteria"].([]any)
	for _, c := range cs {
		if m, ok := c.(map[string]any); ok {
			if m["hard"] == true {
				hard++
			} else {
				advisory++
			}
		}
	}
	return hard, advisory
}

// updateRoot edits the thread's root message to show the task type and
// criteria counts as soon as the plan is known.
func (a *SlackApp) updateRoot(ctx context.Context, run *models.Run, plan map[string]any) {
	if run.Slack == nil || run.Slack.RootTS == "" || (run.ParentRunID != "" && !run.Answered) {
		return // follow-ups keep the original root message
	}
	hard, adv := countCriteria(plan)
	src := "auto-detected"
	if plan["task_type_source"] == "user" {
		src = "chosen by you"
	}
	units := 0
	if us, ok := plan["units"].([]any); ok {
		units = len(us)
	}
	text := fmt.Sprintf("PatchLoop is looking into: %s\nType: *%s* (%s) · Criteria: %d hard, %d advisory · %d units",
		slackEscape(truncate(run.Task, 200)), orStr(plan["task_type"], "task"), src, hard, adv, units)
	if err := a.api.UpdateMessage(ctx, run.Slack.Channel, run.Slack.RootTS, text, nil); err != nil {
		slog.Warn("slack root update failed", "error", err.Error())
	}
}

func clarifyText(d map[string]any) string {
	qs, _ := d["questions"].([]any)
	var sb strings.Builder
	sb.WriteString("*I need a bit more information before I start:*\n")
	for i, q := range qs {
		if m, ok := q.(map[string]any); ok {
			fmt.Fprintf(&sb, "%d. %s\n", i+1, slackEscape(truncate(fmt.Sprint(m["text"]), 300)))
		}
	}
	sb.WriteString("Reply in this thread with your answers (one per line, e.g. `1: ...`) and I will continue.")
	return sb.String()
}

func mergeLine(d map[string]any) string {
	status, _ := d["status"].(string)
	var units []string
	if us, ok := d["units"].([]any); ok {
		for _, u := range us {
			units = append(units, fmt.Sprint(u))
		}
	}
	line := status
	if len(units) > 0 {
		line += " (" + strings.Join(units, ", ") + ")"
	}
	if cs, ok := d["conflicts"].([]any); ok && len(cs) > 0 {
		var paths []string
		for _, c := range cs {
			paths = append(paths, "`"+slackEscape(fmt.Sprint(c))+"`")
		}
		line += ", conflicts: " + strings.Join(paths, ", ")
	}
	return line
}

func verifyLine(d map[string]any) string {
	rs, _ := d["results"].([]any)
	hardPass, hardTotal, adv := 0, 0, 0
	var failing []string
	for _, r := range rs {
		m, ok := r.(map[string]any)
		if !ok {
			continue
		}
		status, _ := m["status"].(string)
		if m["hard"] == true {
			hardTotal++
			if status == "pass" {
				hardPass++
			} else if status == "fail" {
				failing = append(failing, fmt.Sprint(m["criterion_id"]))
			}
		} else if status == "advisory" {
			adv++
		}
	}
	line := fmt.Sprintf("%d/%d hard gates pass", hardPass, hardTotal)
	if len(failing) > 0 {
		line += ", failing: " + strings.Join(failing, ", ")
	}
	if adv > 0 {
		line += fmt.Sprintf(", %d advisory", adv)
	}
	if d["hard_pass"] == false {
		line += " (repair round next unless the budget is spent)"
	}
	return line
}

func doneLine(d map[string]any) string {
	outcome, _ := d["outcome"].(string)
	line := "Finished: " + OutcomeLabel(outcome)
	if c, ok := d["criteria"].(map[string]any); ok {
		hp, _ := toInt(c["hard_pass"])
		ht, _ := toInt(c["hard_total"])
		line += fmt.Sprintf(", hard gates %d/%d", hp, ht)
	}
	return line
}

// OutcomeLabel is the human chip text of an outcome.
func OutcomeLabel(outcome string) string {
	switch outcome {
	case models.OutcomeComplete:
		return "Complete"
	case models.OutcomePartial:
		return "Partial"
	case models.OutcomeNeedsInput:
		return "Needs input"
	case models.OutcomeBlocked:
		return "Blocked"
	}
	return "Failed"
}

// runOutcome is the run's outcome, derived from solved for legacy runs.
func runOutcome(run *models.Run) string {
	if run.Outcome != "" {
		return run.Outcome
	}
	if run.Solved {
		return models.OutcomeComplete
	}
	return models.OutcomeFailed
}

// ---- final card -------------------------------------------------------------------

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
		blocks, text := a.finalBlocks(&cp)
		if _, err := a.api.PostMessage(c, cp.Slack.Channel, cp.Slack.ThreadTS, text, blocks); err != nil {
			slog.Error("slack final message failed", "error", err.Error())
			return
		}
		_ = a.runs.runs.SetSlackSent(c, cp.ID.Hex())
	})
}

func (a *SlackApp) finalBlocks(cp *models.Run) ([]map[string]any, string) {
	outcome := runOutcome(cp)
	label := OutcomeLabel(outcome)
	buttons := []map[string]any{{
		"type": "button", "action_id": "open_run", "text": map[string]any{"type": "plain_text", "text": "Review"}, "url": a.runs.RunURL(cp)}}
	if cp.PRURL != "" && cp.HasPatch() {
		buttons[0]["url"] = cp.PRURL
		confirm := "Merges with your GitHub permissions once checks are green."
		if outcome == models.OutcomePartial {
			confirm = ":warning: " + PartialWarning + "\n" + confirm
		}
		buttons = append(buttons,
			map[string]any{"type": "button", "style": "primary", "action_id": "pl_merge", "value": cp.ID.Hex(),
				"text":    map[string]any{"type": "plain_text", "text": "Merge"},
				"confirm": map[string]any{"title": map[string]any{"type": "plain_text", "text": "Merge this PR?"}, "text": map[string]any{"type": "mrkdwn", "text": confirm}, "confirm": map[string]any{"type": "plain_text", "text": "Merge"}, "deny": map[string]any{"type": "plain_text", "text": "Cancel"}}},
			map[string]any{"type": "button", "action_id": "pl_changes", "value": cp.ID.Hex(),
				"text": map[string]any{"type": "plain_text", "text": "Ask for changes"}})
	}

	fields := []map[string]any{{"type": "mrkdwn", "text": "*Repo*\n" + slackEscape(cp.Repo)}}
	if cp.TaskType != "" {
		fields = append(fields, map[string]any{"type": "mrkdwn", "text": "*Type*\n" + slackEscape(cp.TaskType)})
	}
	if cs := cp.CriteriaSummary; cs != nil {
		fields = append(fields, map[string]any{"type": "mrkdwn", "text": fmt.Sprintf("*Hard gates*\n%d/%d passed", cs.HardPass, cs.HardTotal)})
	} else {
		tests := "n/a"
		if p, t, ok := TestsPassed(cp); ok {
			tests = fmt.Sprintf("%d/%d passed", p, t)
		}
		fields = append(fields, map[string]any{"type": "mrkdwn", "text": "*Proof*\n" + tests + " over " + fmt.Sprint(len(cp.Nodes)) + " attempts"})
	}
	if cp.AgentsSpawned > 0 {
		fields = append(fields, map[string]any{"type": "mrkdwn", "text": fmt.Sprintf("*Agents*\n%d spawned, %d at peak", cp.AgentsSpawned, cp.PeakParallel)})
	}

	blocks := []map[string]any{
		{"type": "section", "text": map[string]any{"type": "mrkdwn", "text": "*" + label + "*: " + RepoResultText(cp) + "\n>" + slackEscape(truncate(cp.Task, 280))}},
		{"type": "section", "fields": fields},
	}
	if notes := advisoryNotes(cp); notes != "" {
		blocks = append(blocks, map[string]any{"type": "section", "text": map[string]any{"type": "mrkdwn", "text": notes}})
	}
	ctxLine := "Agents cannot merge. A human reviews and merges."
	switch outcome {
	case models.OutcomePartial:
		ctxLine = ":warning: " + PartialWarning
	case models.OutcomeNeedsInput:
		ctxLine = "Waiting for your answers: reply in this thread."
	}
	if n := len(cp.Artifacts); n > 0 {
		ctxLine += fmt.Sprintf(" %d artifacts (screenshots, logs) are on the run page.", n)
	}
	blocks = append(blocks,
		map[string]any{"type": "context", "elements": []map[string]any{{"type": "mrkdwn", "text": ctxLine}}},
		map[string]any{"type": "actions", "elements": buttons})
	return blocks, "PatchLoop: " + label + " - " + RepoResultText(cp)
}

// advisoryNotes renders up to three advisory criteria (score + rationale).
func advisoryNotes(cp *models.Run) string {
	if cp.CriteriaSummary == nil || len(cp.CriteriaSummary.Advisory) == 0 {
		return ""
	}
	var sb strings.Builder
	sb.WriteString("*Advisory notes* (never block a merge)\n")
	for i, a := range cp.CriteriaSummary.Advisory {
		if i >= 3 {
			fmt.Fprintf(&sb, "…and %d more on the run page\n", len(cp.CriteriaSummary.Advisory)-3)
			break
		}
		m, ok := a.(map[string]any)
		if !ok {
			continue
		}
		line := fmt.Sprintf("• %v", m["criterion_id"])
		if m["criterion_id"] == nil {
			line = fmt.Sprintf("• %v", m["id"])
		}
		if s, ok := m["score"].(float64); ok {
			line += fmt.Sprintf(" %.2f", s)
		}
		if d, _ := m["detail"].(string); d != "" {
			line += ": " + slackEscape(truncate(d, 140))
		} else if d, _ := m["rationale"].(string); d != "" {
			line += ": " + slackEscape(truncate(d, 140))
		}
		sb.WriteString(line + "\n")
	}
	return strings.TrimSpace(sb.String())
}

// BotConfigured reports whether threaded updates are possible.
func (a *SlackApp) BotConfigured() bool { return a.api.Enabled() }

// LinkEscape is exported for tests that build Slack form bodies.
func LinkEscape(s string) string { return url.QueryEscape(s) }

// ---- answers in a thread --------------------------------------------------------------

var answerLinePattern = regexp.MustCompile(`^\s*(?:q?(\d{1,2})|([A-Za-z][A-Za-z0-9_.-]{0,63}))\s*[:.)\-]\s*(.+)$`)

// ParseSlackAnswers maps a thread reply onto the run's question ids: lines
// "1: text", "q2: text" or "<id>: text" answer the matching question; a reply
// without such lines answers the first question (and a single-question run
// takes the whole text).
func ParseSlackAnswers(run *models.Run, text string) map[string]string {
	ids, _ := QuestionTexts(run)
	if len(ids) == 0 {
		ids = []string{"q1"}
	}
	byLower := map[string]string{}
	for _, id := range ids {
		byLower[strings.ToLower(id)] = id
	}
	out := map[string]string{}
	last := ""
	for _, line := range strings.Split(text, "\n") {
		if m := answerLinePattern.FindStringSubmatch(line); m != nil {
			id := ""
			if m[1] != "" {
				n := 0
				fmt.Sscanf(m[1], "%d", &n)
				if n >= 1 && n <= len(ids) {
					id = ids[n-1]
				}
			} else if v, ok := byLower[strings.ToLower(m[2])]; ok {
				id = v
			}
			if id != "" {
				out[id] = strings.TrimSpace(m[3])
				last = id
				continue
			}
		}
		if last != "" && strings.TrimSpace(line) != "" {
			out[last] += "\n" + strings.TrimSpace(line)
		}
	}
	if len(out) == 0 {
		out[ids[0]] = strings.TrimSpace(text)
	}
	return out
}
