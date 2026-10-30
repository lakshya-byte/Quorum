package render

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"time"
)

// Swarm renders the swarm events of a run (plan, agent, tool, unit, merge,
// verify, artifact, budget, clarify). On a terminal (live) it keeps one frame
// of ~20 lines that is redrawn in place: plan header, the criteria and
// verification-gate table, one lane per unit (variants as sub-entries with a
// spinner and the last tool each), merge status and a budget line. Without a
// terminal (pipes, CI, NO_COLOR) it prints one plain line per event instead.
type Swarm struct {
	w     io.Writer
	color bool
	live  bool
	width int
	rows  int

	mu       sync.Mutex
	drawn    int // lines of the frame currently on screen (live)
	spin     int
	lastDraw time.Time

	taskType, source, summary string
	maxParallel, planned      int
	crit                      []*critView
	critIdx                   map[string]*critView
	units                     []*unitView
	unitIdx                   map[string]*unitView
	agents                    map[string]*agentView
	support                   []string // non-worker agent ids in first-seen order
	merge                     string
	round                     int
	budget                    budgetView
	artifacts                 int
	toolCalls                 int
	finished                  bool
}

type critView struct {
	id, kind, desc string
	hard           bool
	status         string // "", pass, fail, skip, advisory
	score          *float64
	detail         string
}

type unitView struct {
	id, title string
	deps      []string
	status    string
	winner    int
	variants  []string // agent ids in variant order
}

type agentView struct {
	id, role, unit string
	variant        int
	status         string
	tool           string
	summary        string
}

type budgetView struct {
	tokens, tokenLimit, wall, wallLimit, active float64
	seen                                        bool
}

// NewSwarm builds a swarm view. live=true redraws a frame in place using ANSI
// cursor movement and must only be used on a terminal.
func NewSwarm(w io.Writer, color, live bool, width, rows int) *Swarm {
	if width < 40 {
		width = 100
	}
	if rows < 12 {
		rows = 40
	}
	return &Swarm{w: w, color: color, live: live, width: width, rows: rows,
		critIdx: map[string]*critView{}, unitIdx: map[string]*unitView{}, agents: map[string]*agentView{}}
}

// TerminalSize returns the size of the terminal behind f (columns, rows),
// from $COLUMNS/$LINES or `stty size`; zeros when unknown.
func TerminalSize(f *os.File) (cols, rows int) {
	cols, _ = strconv.Atoi(os.Getenv("COLUMNS"))
	rows, _ = strconv.Atoi(os.Getenv("LINES"))
	if cols > 0 && rows > 0 {
		return cols, rows
	}
	cmd := exec.Command("stty", "size")
	cmd.Stdin = f
	if out, err := cmd.Output(); err == nil {
		var r, c int
		if n, _ := fmt.Sscanf(strings.TrimSpace(string(out)), "%d %d", &r, &c); n == 2 {
			if cols == 0 {
				cols = c
			}
			if rows == 0 {
				rows = r
			}
		}
	}
	return cols, rows
}

func (s *Swarm) c(code, text string) string {
	if !s.color {
		return text
	}
	return code + text + reset
}

// ---- event handling ---------------------------------------------------------

// Handle consumes one swarm event. It reports whether the event type belongs
// to the swarm view.
func (s *Swarm) Handle(typ string, data json.RawMessage) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	var d map[string]any
	_ = json.Unmarshal(data, &d)
	switch typ {
	case "plan":
		s.onPlan(d)
	case "agent":
		s.onAgent(d)
	case "tool":
		s.onTool(d)
	case "unit":
		s.onUnit(d)
	case "merge":
		s.onMerge(d)
	case "verify":
		s.onVerify(d)
	case "artifact":
		s.artifacts++
		s.plain(fmt.Sprintf("artifact %s (%s%s)", str(d["id"]), str(d["kind"]), join(" ", ", "+str(d["phase"]), viewport(d))))
	case "budget":
		s.budget = budgetView{tokens: num(d["tokens_used"]), tokenLimit: num(d["tokens_limit"]), wall: num(d["wall_s"]),
			wallLimit: num(d["wall_limit_s"]), active: num(d["workers_active"]), seen: true}
	case "clarify":
		s.onClarify(d)
	default:
		return false
	}
	s.redraw(typ == "tool" || typ == "budget")
	return true
}

func str(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	if v == nil {
		return ""
	}
	return fmt.Sprint(v)
}

func num(v any) float64 {
	f, _ := v.(float64)
	return f
}

func viewport(d map[string]any) string {
	if v := str(d["viewport"]); v != "" {
		return ", " + v + "px"
	}
	return ""
}

func join(sep string, parts ...string) string {
	var out []string
	for _, p := range parts {
		if strings.TrimLeft(p, ", ") != "" {
			out = append(out, p)
		}
	}
	return strings.Join(out, "")
}

func (s *Swarm) onPlan(d map[string]any) {
	s.taskType, s.source, s.summary = str(d["task_type"]), str(d["task_type_source"]), str(d["summary"])
	if sw, ok := d["swarm"].(map[string]any); ok {
		s.maxParallel, s.planned = int(num(sw["max_parallel"])), int(num(sw["workers_planned"]))
	}
	s.crit, s.critIdx = nil, map[string]*critView{}
	if cs, ok := d["criteria"].([]any); ok {
		for _, c := range cs {
			m, _ := c.(map[string]any)
			cv := &critView{id: str(m["id"]), kind: str(m["kind"]), desc: str(m["description"]), hard: m["hard"] == true}
			s.crit = append(s.crit, cv)
			s.critIdx[cv.id] = cv
		}
	}
	s.units, s.unitIdx = nil, map[string]*unitView{}
	if us, ok := d["units"].([]any); ok {
		for _, u := range us {
			m, _ := u.(map[string]any)
			uv := &unitView{id: str(m["id"]), title: str(m["title"]), status: "pending"}
			if deps, ok := m["depends_on"].([]any); ok {
				for _, dep := range deps {
					uv.deps = append(uv.deps, str(dep))
				}
			}
			s.units = append(s.units, uv)
			s.unitIdx[uv.id] = uv
		}
	}
	hard, adv := 0, 0
	for _, c := range s.crit {
		if c.hard {
			hard++
		} else {
			adv++
		}
	}
	src := ""
	if s.source != "" {
		src = " (" + s.source + ")"
	}
	s.plain(fmt.Sprintf("plan: %s task%s - %d units, %d hard + %d advisory criteria%s", s.taskType, src, len(s.units), hard, adv, s.parallelText()))
	if s.summary != "" {
		s.plain("  " + s.summary)
	}
	for _, c := range s.crit {
		kind := "hard"
		if !c.hard {
			kind = "advisory"
		}
		s.plain(fmt.Sprintf("  criterion [%s] %s: %s", kind, c.id, c.desc))
	}
	for _, u := range s.units {
		dep := ""
		if len(u.deps) > 0 {
			dep = " (after " + strings.Join(u.deps, ", ") + ")"
		}
		s.plain(fmt.Sprintf("  unit %s: %s%s", u.id, u.title, dep))
	}
}

func (s *Swarm) parallelText() string {
	if s.maxParallel > 0 {
		return fmt.Sprintf(", up to %d agents in parallel", s.maxParallel)
	}
	return ""
}

func (s *Swarm) unit(id string) *unitView {
	if u, ok := s.unitIdx[id]; ok {
		return u
	}
	u := &unitView{id: id, title: id, status: "pending"}
	s.units = append(s.units, u)
	s.unitIdx[id] = u
	return u
}

func (s *Swarm) onAgent(d map[string]any) {
	id := str(d["id"])
	if id == "" {
		return
	}
	a, ok := s.agents[id]
	if !ok {
		a = &agentView{id: id, role: str(d["role"]), unit: str(d["unit_id"]), variant: int(num(d["variant"]))}
		s.agents[id] = a
		if a.unit != "" && a.role == "worker" {
			u := s.unit(a.unit)
			u.variants = append(u.variants, id)
		} else {
			s.support = append(s.support, id)
		}
	}
	a.status = str(d["status"])
	if sm := str(d["summary"]); sm != "" {
		a.summary = sm
	}
	line := fmt.Sprintf("agent %s (%s) %s", id, a.role, a.status)
	if a.summary != "" && (a.status == "done" || a.status == "failed") {
		line += ": " + a.summary
	}
	s.plain(line)
}

func (s *Swarm) onTool(d map[string]any) {
	s.toolCalls++
	if a, ok := s.agents[str(d["agent_id"])]; ok {
		a.tool = strings.TrimSpace(str(d["name"]) + " " + str(d["target"]))
		if d["ok"] == false {
			a.tool += " (failed)"
		}
	}
}

func (s *Swarm) onUnit(d map[string]any) {
	u := s.unit(str(d["id"]))
	u.status = str(d["status"])
	if w := int(num(d["winner_variant"])); w > 0 {
		u.winner = w
	}
	line := fmt.Sprintf("unit %s %s", u.id, u.status)
	if u.winner > 0 && (u.status == "passed" || u.status == "merged") {
		line += fmt.Sprintf(" (variant %d won)", u.winner)
	}
	if fs, ok := d["files"].([]any); ok && len(fs) > 0 && u.status == "passed" {
		line += fmt.Sprintf(", %d files", len(fs))
	}
	s.plain(line)
}

func (s *Swarm) onMerge(d map[string]any) {
	status := str(d["status"])
	line := status
	if us, ok := d["units"].([]any); ok && len(us) > 0 {
		ids := make([]string, 0, len(us))
		for _, u := range us {
			ids = append(ids, str(u))
		}
		line += " (" + strings.Join(ids, ", ") + ")"
	}
	if cs, ok := d["conflicts"].([]any); ok && len(cs) > 0 {
		paths := make([]string, 0, len(cs))
		for _, c := range cs {
			paths = append(paths, str(c))
		}
		line += ", conflicts: " + strings.Join(paths, ", ")
	}
	s.merge = line
	s.plain("merge " + line)
}

func (s *Swarm) onVerify(d map[string]any) {
	s.round = int(num(d["round"]))
	pass, total := 0, 0
	rs, _ := d["results"].([]any)
	var lines []string
	for _, r := range rs {
		m, _ := r.(map[string]any)
		id := str(m["criterion_id"])
		cv, ok := s.critIdx[id]
		if !ok {
			cv = &critView{id: id, kind: str(m["kind"]), hard: m["hard"] == true}
			s.crit = append(s.crit, cv)
			s.critIdx[id] = cv
		}
		cv.status, cv.detail = str(m["status"]), str(m["detail"])
		cv.score = nil
		if sc, ok := m["score"].(float64); ok {
			v := sc
			cv.score = &v
		}
		if cv.hard {
			total++
			if cv.status == "pass" {
				pass++
			}
		}
		lines = append(lines, fmt.Sprintf("  %-8s %s%s: %s", cv.status, id, scoreText(cv.score), truncRunes(cv.detail, 120)))
	}
	s.plain(fmt.Sprintf("verify round %d: %d/%d hard gates pass", s.round, pass, total))
	for _, l := range lines {
		s.plain(l)
	}
}

func scoreText(sc *float64) string {
	if sc == nil {
		return ""
	}
	return fmt.Sprintf(" %.2f", *sc)
}

func (s *Swarm) onClarify(d map[string]any) {
	qs, _ := d["questions"].([]any)
	s.plain("clarify: the planner needs more information")
	for i, q := range qs {
		m, _ := q.(map[string]any)
		s.plain(fmt.Sprintf("  %d. [%s] %s", i+1, str(m["id"]), str(m["text"])))
	}
}

// ---- drawing -------------------------------------------------------------------

// plain prints a line in non-live mode (live mode shows state in the frame).
func (s *Swarm) plain(line string) {
	if s.live {
		return
	}
	fmt.Fprintln(s.w, line)
}

func truncRunes(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return string(r[:n-1]) + "…"
}

// fit cuts s to at most width visible cells (ANSI sequences are free).
func fit(s string, width int) string {
	var b strings.Builder
	vis := 0
	runes := []rune(s)
	for i := 0; i < len(runes); i++ {
		if runes[i] == 0x1b && i+1 < len(runes) && runes[i+1] == '[' {
			j := i + 2
			for j < len(runes) && !(runes[j] >= '@' && runes[j] <= '~') {
				j++
			}
			if j < len(runes) {
				j++
			}
			b.WriteString(string(runes[i:j]))
			i = j - 1
			continue
		}
		if vis >= width {
			if strings.Contains(b.String(), "\x1b[") {
				b.WriteString(reset)
			}
			return b.String()
		}
		b.WriteRune(runes[i])
		vis++
	}
	return b.String()
}

var spinFrames = []string{"⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"}

func (s *Swarm) glyph(status string) string {
	switch status {
	case "running", "spawned":
		return s.c(cyan, spinFrames[s.spin%len(spinFrames)])
	case "done", "passed", "merged", "pass", "ok", "resolved":
		return s.c(green, "✓")
	case "failed", "fail", "conflict":
		return s.c(red, "✗")
	case "cancelled":
		return s.c(dim, "⊘")
	case "skip":
		return s.c(amber, "-")
	case "advisory":
		return s.c(purple, "◇")
	}
	return s.c(dim, "·")
}

// Frame returns the lines of the live frame.
func (s *Swarm) Frame() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.frame()
}

func (s *Swarm) frame() []string {
	if s.taskType == "" && len(s.crit) == 0 && len(s.units) == 0 {
		return nil
	}
	var out []string
	hard, adv := 0, 0
	for _, c := range s.crit {
		if c.hard {
			hard++
		} else {
			adv++
		}
	}
	head := s.c(bold, "━ "+orDash(s.taskType)+" task")
	if s.source != "" {
		head += s.c(dim, " ("+s.source+")")
	}
	head += s.c(dim, fmt.Sprintf(" · %d units · %d hard + %d advisory criteria%s", len(s.units), hard, adv, s.parallelText()))
	out = append(out, head)
	if s.summary != "" {
		out = append(out, "  "+s.c(dim, truncRunes(s.summary, s.width-4)))
	}

	// Criteria and verification gates in one table (hard gates first).
	title := "Criteria"
	if s.round > 0 {
		title = fmt.Sprintf("Criteria and gates (verification round %d)", s.round)
	}
	out = append(out, s.c(bold, title))
	budgetRows := s.rows - 12 - len(s.units)*2
	if budgetRows < 6 {
		budgetRows = 6
	}
	shown := 0
	ordered := make([]*critView, 0, len(s.crit))
	for _, c := range s.crit {
		if c.hard {
			ordered = append(ordered, c)
		}
	}
	for _, c := range s.crit {
		if !c.hard {
			ordered = append(ordered, c)
		}
	}
	for _, c := range ordered {
		if shown >= budgetRows {
			out = append(out, s.c(dim, fmt.Sprintf("  … %d more", len(ordered)-shown)))
			break
		}
		kind := "hard    "
		if !c.hard {
			kind = "advisory"
		}
		detail := c.detail
		if detail == "" {
			detail = c.desc
		}
		line := fmt.Sprintf("  %s %s %-18s %s", s.glyph(c.status), s.c(dim, kind), c.id, s.c(dim, truncRunes(detail+scoreText(c.score), s.width-34)))
		if c.status == "fail" {
			line = fmt.Sprintf("  %s %s %-18s %s", s.glyph(c.status), kind, s.c(red, c.id), s.c(red, truncRunes(detail, s.width-34)))
		}
		out = append(out, line)
		shown++
	}

	// Agent lanes: one per unit, variants inline.
	if len(s.units) > 0 {
		out = append(out, s.c(bold, "Agents"))
	}
	for _, u := range s.units {
		line := fmt.Sprintf("  %s %-3s %s", s.glyph(u.status), u.id, truncRunes(u.title, 34))
		for i, id := range u.variants {
			a := s.agents[id]
			v := a.variant
			if v == 0 {
				v = i + 1
			}
			cell := fmt.Sprintf("v%d %s", v, s.glyph(a.status))
			if a.status == "running" || a.status == "spawned" {
				if a.tool != "" {
					cell += " " + truncRunes(a.tool, 22)
				}
			} else if a.status == "cancelled" {
				cell += s.c(dim, " cancelled")
			}
			line += s.c(dim, "  [") + cell + s.c(dim, "]")
		}
		out = append(out, line)
	}
	if len(s.support) > 0 {
		parts := make([]string, 0, len(s.support))
		for _, id := range s.support {
			a := s.agents[id]
			parts = append(parts, fmt.Sprintf("%s %s", a.role, s.glyph(a.status)))
		}
		out = append(out, "  "+s.c(dim, "support: ")+strings.Join(parts, s.c(dim, " · ")))
	}
	if s.merge != "" {
		out = append(out, s.c(bold, "Merge")+" "+s.c(dim, s.merge))
	}
	if s.budget.seen {
		b := s.budget
		out = append(out, s.c(dim, fmt.Sprintf("budget: tokens %s / %s · %.0fs / %.0fs · %.0f agents active · %d tool calls · %d artifacts",
			commas(b.tokens), commas(b.tokenLimit), b.wall, b.wallLimit, b.active, s.toolCalls, s.artifacts)))
	}
	return out
}

func orDash(s string) string {
	if s == "" {
		return "-"
	}
	return s
}

func commas(f float64) string {
	n := int64(f)
	s := strconv.FormatInt(n, 10)
	for i := len(s) - 3; i > 0; i -= 3 {
		s = s[:i] + "," + s[i:]
	}
	return s
}

// redraw repaints the frame in place (live mode). cheap=true events are
// throttled so tool chatter does not flood the terminal.
func (s *Swarm) redraw(cheap bool) {
	if !s.live || s.finished {
		return
	}
	now := time.Now()
	if cheap && now.Sub(s.lastDraw) < 40*time.Millisecond {
		return
	}
	s.lastDraw = now
	s.draw()
}

func (s *Swarm) draw() {
	lines := s.frame()
	var b strings.Builder
	if s.drawn > 0 {
		fmt.Fprintf(&b, "\x1b[%dA", s.drawn)
	}
	for _, l := range lines {
		b.WriteString("\r\x1b[K" + fit(l, s.width-1) + "\n")
	}
	// Erase leftover lines of a taller previous frame.
	for i := len(lines); i < s.drawn; i++ {
		b.WriteString("\r\x1b[K\n")
	}
	if extra := s.drawn - len(lines); extra > 0 {
		fmt.Fprintf(&b, "\x1b[%dA", extra)
	}
	s.drawn = len(lines)
	_, _ = io.WriteString(s.w, b.String())
}

// Tick advances the spinners and redraws (call every ~100 ms while live).
func (s *Swarm) Tick() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.spin++
	if s.live && !s.finished && s.drawn > 0 {
		s.lastDraw = time.Now()
		s.draw()
	}
}

// Print writes a static line above the frame (live) or just prints it.
func (s *Swarm) Print(line string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if !s.live || s.drawn == 0 {
		fmt.Fprintln(s.w, line)
		return
	}
	var b strings.Builder
	fmt.Fprintf(&b, "\x1b[%dA", s.drawn)
	b.WriteString("\r\x1b[K" + line + "\n")
	_, _ = io.WriteString(s.w, b.String())
	s.drawn = 0
	s.draw()
}

// Finish freezes the frame: the last state stays in the scrollback.
func (s *Swarm) Finish() {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.live && !s.finished {
		s.finished = true
		for _, a := range s.agents { // nothing animates any more
			if a.status == "running" || a.status == "spawned" {
				a.status = "done"
			}
		}
		s.draw()
		s.drawn = 0
	}
	s.finished = true
}

// Active reports whether a swarm plan has been seen (so the swarm summary
// replaces the legacy one).
func (s *Swarm) Active() bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.taskType != "" || len(s.crit) > 0 || len(s.units) > 0
}

// Budget returns the last budget numbers (tokens used, wall seconds).
func (s *Swarm) Budget() (tokens, wall float64, ok bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.budget.tokens, s.budget.wall, s.budget.seen
}
