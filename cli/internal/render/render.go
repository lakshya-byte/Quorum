// Package render turns PatchLoop stream events into a live terminal tree.
package render

import (
	"encoding/json"
	"fmt"
	"io"
	"strings"

	"patchloop-cli/internal/sse"
)

const (
	reset  = "\x1b[0m"
	bold   = "\x1b[1m"
	dim    = "\x1b[2m"
	red    = "\x1b[31m"
	green  = "\x1b[32m"
	amber  = "\x1b[33m"
	cyan   = "\x1b[36m"
	purple = "\x1b[35m"
)

// Renderer writes one or more lines per event. It remembers the final
// outcome so the caller can choose an exit code.
type Renderer struct {
	w      io.Writer
	color  bool
	Solved bool // outcome complete (legacy: the run solved the bug)
	Done   bool
	Ended  bool
	Errors []string
	PRURL  string

	// Swarm runs (CONTRACT-V3): outcome is complete|partial|failed|needs_input|blocked
	// ("" until the done event; derived from solved for legacy streams).
	Outcome   string
	TaskType  string
	HardPass  int
	HardTotal int

	live        bool
	width, rows int
	sw          *Swarm
}

func New(w io.Writer, color bool) *Renderer {
	return &Renderer{w: w, color: color}
}

// NewLive is New for a terminal: swarm runs are drawn as one frame that is
// redrawn in place (call Tick every ~100 ms to animate the spinners).
func NewLive(w io.Writer, color bool, width, rows int) *Renderer {
	r := &Renderer{w: w, color: color, live: true, width: width, rows: rows}
	r.sw = NewSwarm(w, color, true, width, rows) // eager: the ticker goroutine reads it
	return r
}

func (r *Renderer) swarm() *Swarm {
	if r.sw == nil {
		r.sw = NewSwarm(r.w, r.color, r.live, r.width, r.rows)
	}
	return r.sw
}

// Tick animates the live swarm frame (no-op otherwise).
func (r *Renderer) Tick() {
	if r.sw != nil {
		r.sw.Tick()
	}
}

// SwarmActive reports whether a swarm plan was rendered.
func (r *Renderer) SwarmActive() bool { return r.sw != nil && r.sw.Active() }

func (r *Renderer) c(code, s string) string {
	if !r.color {
		return s
	}
	return code + s + reset
}

func (r *Renderer) line(depth int, s string) {
	if r.sw != nil && r.live {
		r.sw.Print(strings.Repeat("  ", depth) + s) // above the live frame
		return
	}
	fmt.Fprintf(r.w, "%s%s\n", strings.Repeat("  ", depth), s)
}

type node struct {
	ID        any            `json:"id"`
	Parent    any            `json:"parent"`
	Depth     int            `json:"depth"`
	Idea      string         `json:"idea"`
	Strategy  string         `json:"strategy"`
	Passed    int            `json:"passed"`
	Total     int            `json:"total"`
	Score     float64        `json:"score"`
	Model     string         `json:"model"`
	LatencyMs float64        `json:"latency_ms"`
	Tokens    float64        `json:"tokens"`
	Files     map[string]any `json:"files"`
	Policy    *struct {
		OK      bool     `json:"ok"`
		Reasons []string `json:"reasons"`
	} `json:"policy"`
	Security *struct {
		OK          bool `json:"ok"`
		NewFindings int  `json:"new_findings"`
	} `json:"security"`
}

// colorFor: green = all tests pass, amber = some, red = none.
func (r *Renderer) colorFor(passed, total int) string {
	switch {
	case total > 0 && passed >= total:
		return green
	case passed > 0:
		return amber
	default:
		return red
	}
}

func fmtMs(ms float64) string {
	if ms >= 1000 {
		return fmt.Sprintf("%.1fs", ms/1000)
	}
	return fmt.Sprintf("%.0fms", ms)
}

func idStr(v any) string {
	switch x := v.(type) {
	case nil:
		return "-"
	case float64:
		return fmt.Sprintf("%.0f", x)
	default:
		return fmt.Sprint(x)
	}
}

// Event renders one event.
func (r *Renderer) Event(ev sse.Event) {
	switch ev.Type {
	case "run_started":
		var d struct{ RunID, BugID, Mode, Engine string }
		var raw map[string]any
		_ = json.Unmarshal(ev.Data, &raw)
		d.RunID, _ = raw["run_id"].(string)
		d.BugID, _ = raw["bug_id"].(string)
		d.Mode, _ = raw["mode"].(string)
		d.Engine, _ = raw["engine"].(string)
		r.line(0, r.c(bold, fmt.Sprintf("PatchLoop run %s", d.RunID))+r.c(dim, fmt.Sprintf("  bug=%s mode=%s engine=%s", d.BugID, d.Mode, d.Engine)))
	case "guard":
		var d struct {
			Stage     string   `json:"stage"`
			Verdict   string   `json:"verdict"`
			Reasons   []string `json:"reasons"`
			LatencyMs float64  `json:"latency_ms"`
		}
		_ = json.Unmarshal(ev.Data, &d)
		col, mark := green, "pass"
		if d.Verdict != "pass" {
			col, mark = red, "BLOCK"
		}
		s := fmt.Sprintf("%s guard %-6s %s", r.c(cyan, "◆"), d.Stage, r.c(col, mark))
		if len(d.Reasons) > 0 {
			s += ": " + strings.Join(d.Reasons, "; ")
		}
		r.line(0, s+r.c(dim, " ("+fmtMs(d.LatencyMs)+")"))
	case "triage":
		var d struct {
			Cause      string   `json:"cause"`
			Strategies []string `json:"strategies"`
		}
		_ = json.Unmarshal(ev.Data, &d)
		r.line(0, r.c(purple, "◇ triage")+": "+d.Cause)
		if len(d.Strategies) > 0 {
			r.line(1, r.c(dim, "strategies: "+strings.Join(d.Strategies, " | ")))
		}
	case "round":
		var d struct {
			Depth int `json:"depth"`
		}
		_ = json.Unmarshal(ev.Data, &d)
		r.line(0, r.c(dim, fmt.Sprintf("── round %d ──", d.Depth)))
	case "node":
		var n node
		_ = json.Unmarshal(ev.Data, &n)
		col := r.colorFor(n.Passed, n.Total)
		idea := n.Idea
		if idea == "" {
			idea = n.Strategy
		}
		s := fmt.Sprintf("├─ #%s %s %s", idStr(n.ID), r.c(col, fmt.Sprintf("[%d/%d]", n.Passed, n.Total)), idea)
		meta := []string{}
		if n.Model != "" {
			meta = append(meta, n.Model)
		}
		if n.LatencyMs > 0 {
			meta = append(meta, fmtMs(n.LatencyMs))
		}
		if n.Tokens > 0 {
			meta = append(meta, fmt.Sprintf("%.0f tok", n.Tokens))
		}
		if len(n.Files) > 1 {
			meta = append(meta, fmt.Sprintf("%d files", len(n.Files)))
		}
		if n.Policy != nil && !n.Policy.OK {
			meta = append(meta, r.c(red, "policy: "+strings.Join(n.Policy.Reasons, "; ")))
		}
		if n.Security != nil && !n.Security.OK {
			meta = append(meta, r.c(red, fmt.Sprintf("security: %d new findings", n.Security.NewFindings)))
		}
		if len(meta) > 0 {
			s += r.c(dim, "  ("+strings.Join(meta, ", ")+")")
		}
		r.line(n.Depth+1, s)
	case "critic":
		var d struct {
			NodeID any    `json:"node_id"`
			Lesson string `json:"lesson"`
		}
		_ = json.Unmarshal(ev.Data, &d)
		r.line(1, r.c(amber, "✎ critic")+fmt.Sprintf(" on #%s: %s", idStr(d.NodeID), d.Lesson))
	case "plan", "agent", "tool", "unit", "merge", "verify", "artifact", "budget", "clarify":
		r.swarm().Handle(ev.Type, ev.Data)
		if ev.Type == "plan" {
			var p struct {
				TaskType string `json:"task_type"`
			}
			_ = json.Unmarshal(ev.Data, &p)
			r.TaskType = p.TaskType
		}
	case "done":
		var d struct {
			Solved   bool   `json:"solved"`
			Outcome  string `json:"outcome"`
			TaskType string `json:"task_type"`
			Best     *node  `json:"best"`
			Criteria *struct {
				HardPass  int              `json:"hard_pass"`
				HardTotal int              `json:"hard_total"`
				Advisory  []map[string]any `json:"advisory"`
			} `json:"criteria"`
			Agents *struct {
				Spawned      int `json:"spawned"`
				PeakParallel int `json:"peak_parallel"`
			} `json:"agents"`
			Usage struct {
				Prompt     float64 `json:"prompt_tokens"`
				Completion float64 `json:"completion_tokens"`
			} `json:"usage"`
			LatencyMs float64 `json:"latency_ms"`
			TTFN      float64 `json:"time_to_first_node_ms"`
			TTFE      float64 `json:"time_to_first_event_ms"`
		}
		_ = json.Unmarshal(ev.Data, &d)
		outcome := d.Outcome
		switch outcome {
		case "complete", "partial", "failed", "needs_input", "blocked":
		default:
			outcome = "failed"
			if d.Solved {
				outcome = "complete"
			}
		}
		r.Done, r.Outcome, r.Solved = true, outcome, outcome == "complete"
		if d.TaskType != "" {
			r.TaskType = d.TaskType
		}
		if d.Criteria != nil {
			r.HardPass, r.HardTotal = d.Criteria.HardPass, d.Criteria.HardTotal
		}
		swarm := r.SwarmActive()
		if r.sw != nil {
			r.sw.Finish()
		}
		tokens := d.Usage.Prompt + d.Usage.Completion
		if swarm {
			r.line(0, r.outcomeHead(outcome, true)+r.gatesText(d.Criteria != nil))
			if d.Criteria != nil {
				for i, a := range d.Criteria.Advisory {
					if i >= 5 {
						r.line(1, r.c(dim, fmt.Sprintf("… %d more advisory notes", len(d.Criteria.Advisory)-5)))
						break
					}
					r.line(1, r.c(purple, "◇ advisory ")+advisoryText(a))
				}
			}
			meta := []string{}
			if d.Agents != nil {
				meta = append(meta, fmt.Sprintf("%d agents (peak %d in parallel)", d.Agents.Spawned, d.Agents.PeakParallel))
			}
			meta = append(meta, fmt.Sprintf("tokens %.0f", tokens), "latency "+fmtMs(d.LatencyMs))
			r.line(1, strings.Join(meta, " · "))
			break
		}
		head := r.outcomeHead(outcome, false)
		if d.Best != nil {
			head += fmt.Sprintf("  best #%s %d/%d tests", idStr(d.Best.ID), d.Best.Passed, d.Best.Total)
		}
		r.line(0, head)
		r.line(1, fmt.Sprintf("tokens %.0f (prompt %.0f + completion %.0f) · latency %s · first node %s",
			tokens, d.Usage.Prompt, d.Usage.Completion, fmtMs(d.LatencyMs), fmtMs(d.TTFN)))
	case "repo":
		var d struct {
			FullName    string `json:"full_name"`
			Branch      string `json:"branch"`
			Files       any    `json:"files"`
			Language    string `json:"language"`
			TestCommand string `json:"test_command"`
			Truncated   bool   `json:"truncated"`
		}
		_ = json.Unmarshal(ev.Data, &d)
		s := fmt.Sprintf("%s repo %s@%s", r.c(cyan, "⎇"), r.c(bold, d.FullName), d.Branch)
		s += r.c(dim, fmt.Sprintf("  %v files · %s · tests: %s", d.Files, d.Language, d.TestCommand))
		if d.Truncated {
			s += r.c(amber, "  (repo truncated: size cap)")
		}
		r.line(0, s)
	case "locate":
		var d struct {
			Files []struct {
				Path   string `json:"path"`
				Reason string `json:"reason"`
			} `json:"files"`
		}
		_ = json.Unmarshal(ev.Data, &d)
		r.line(0, r.c(purple, "⌖ locate"))
		for _, f := range d.Files {
			r.line(1, fmt.Sprintf("%s %s", f.Path, r.c(dim, f.Reason)))
		}
	case "repro":
		var d struct {
			Path             string `json:"path"`
			TestName         string `json:"test_name"`
			FailedOnOriginal bool   `json:"failed_on_original"`
			OutputTail       string `json:"output_tail"`
		}
		_ = json.Unmarshal(ev.Data, &d)
		if d.FailedOnOriginal {
			r.line(0, r.c(green, "✔ reproducer ")+fmt.Sprintf("%s (%s) fails on the original code", d.TestName, d.Path))
		} else {
			r.line(0, r.c(amber, "! no reproducer that fails on the original code; using the existing tests"))
		}
	case "pr":
		var d struct {
			URL     string `json:"url"`
			Number  int    `json:"number"`
			Branch  string `json:"branch"`
			Fake    bool   `json:"fake"`
			Updated bool   `json:"updated"`
			Commits int    `json:"commits"`
		}
		_ = json.Unmarshal(ev.Data, &d)
		r.PRURL = d.URL
		verb := "opened"
		if d.Updated {
			verb = "updated (new commit)"
		} else if d.Commits > 1 {
			verb = fmt.Sprintf("opened (%d commits, one per unit)", d.Commits)
		}
		label := "PR"
		if d.Number > 0 {
			label = fmt.Sprintf("PR #%d", d.Number)
		}
		s := r.c(green, fmt.Sprintf("⇪ %s %s: ", label, verb)) + d.URL
		if d.Branch != "" {
			s += r.c(dim, "  branch "+d.Branch)
		}
		if d.Fake {
			s += r.c(amber, "  [fake mode]")
		}
		r.line(0, s)
	case "error":
		var d struct {
			Stage   string `json:"stage"`
			Message string `json:"message"`
		}
		_ = json.Unmarshal(ev.Data, &d)
		msg := d.Message
		if d.Stage != "" {
			msg = d.Stage + ": " + msg
		}
		r.Errors = append(r.Errors, msg)
		r.line(0, r.c(red, "✗ error "+msg))
	case "end":
		r.Ended = true
	case "":
		// Unparseable fragment (e.g. agent died mid-message): skip.
	default:
		r.line(0, r.c(dim, ev.Type+" "+string(ev.Data)))
	}
}
