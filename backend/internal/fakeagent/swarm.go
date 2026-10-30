package fakeagent

import (
	"bytes"
	"fmt"
	"image"
	"image/color"
	"image/png"
	"net/http"
	"regexp"
	"strings"
	"sync"
)

// Fake swarm (CONTRACT-V3): scripted but contract-shaped event streams for
// every task type, so the backend, CLI, Slack flow and the website run without
// the Python agent. Special words in the task text steer the script:
//
//	"vague"      -> needs_input: a clarify event, outcome needs_input
//	"unsolvable" -> hard gates never pass: outcome failed, no PR
//	"partial"    -> hard gates pass but one stated criterion has no verifier: outcome partial
//	"evilart"    -> the artifact store also holds hostile artifacts (html, svg
//	                with script, exe, mislabelled png, oversize) to test the proxy
//	"conflict"   -> the first merge conflicts and is resolved by the integrator
//
// With no hint and task_type auto/bugfix the legacy bug-fix stream is used.

// fakeArtifact is one stored artifact (the agent serves them over HTTP).
type fakeArtifact struct {
	ID, Kind, Label, Phase, Viewport, Mime string
	Data                                   []byte
}

func (a fakeArtifact) index() map[string]any {
	m := map[string]any{"id": a.ID, "kind": a.Kind, "label": a.Label, "phase": a.Phase, "mime": a.Mime, "size": len(a.Data)}
	if a.Viewport != "" {
		m["viewport"] = a.Viewport
	}
	return m
}

var (
	reUI       = regexp.MustCompile(`(?i)\b(ui|ux|css|layout|responsive|styling|navbar|sidebar|dark mode|landing page)\b`)
	reRefactor = regexp.MustCompile(`(?i)\b(refactor|restructure|extract|clean ?up|rename|split)\b`)
	reFeature  = regexp.MustCompile(`(?i)\b(add|implement|support|new feature|feature)\b`)
	reTests    = regexp.MustCompile(`(?i)\b(write tests|add tests|test coverage|coverage)\b`)
	rePerf     = regexp.MustCompile(`(?i)\b(performance|faster|speed up|latency|optimi[sz]e)\b`)
	reDeps     = regexp.MustCompile(`(?i)\b(upgrade|bump|dependenc(y|ies)|update packages)\b`)
	reDocs     = regexp.MustCompile(`(?i)\b(docs?|documentation|readme)\b`)
	reMigrate  = regexp.MustCompile(`(?i)\b(migrate|migration|port to)\b`)
)

// inferType is the fake planner's guess for task_type=auto. Anything it does
// not recognise is a bug fix (the legacy cheap path).
func inferType(task string) string {
	switch {
	case reUI.MatchString(task):
		return "ui"
	case reRefactor.MatchString(task):
		return "refactor"
	case reTests.MatchString(task):
		return "tests"
	case rePerf.MatchString(task):
		return "perf"
	case reDeps.MatchString(task):
		return "deps"
	case reMigrate.MatchString(task):
		return "migration"
	case reDocs.MatchString(task):
		return "docs"
	case reFeature.MatchString(task):
		return "feature"
	}
	return "bugfix"
}

func has(task, word string) bool { return strings.Contains(strings.ToLower(task), word) }

// ---- artifact bytes -------------------------------------------------------------

func tinyPNG(c color.RGBA) []byte {
	img := image.NewRGBA(image.Rect(0, 0, 12, 8))
	for x := 0; x < 12; x++ {
		for y := 0; y < 8; y++ {
			img.Set(x, y, c)
		}
	}
	var b bytes.Buffer
	_ = png.Encode(&b, img)
	return b.Bytes()
}

func tinySVG(label string) []byte {
	return []byte(`<svg xmlns="http://www.w3.org/2000/svg" width="120" height="60"><rect width="120" height="60" fill="#e8eefc"/><text x="8" y="34" font-size="12">` + label + `</text></svg>`)
}

// ---- the script ---------------------------------------------------------------------

type unitSpec struct {
	id, title string
	scope     []string
	deps      []string
	variants  int
}

type criterion struct {
	id, kind, description, verifier string
	hard                            bool
}

func (c criterion) plan() map[string]any {
	return map[string]any{"id": c.id, "kind": c.kind, "hard": c.hard, "description": c.description, "verifier": c.verifier}
}

func baseCriteria() []criterion {
	return []criterion{
		{"build", "build", "install and build succeed in the sandbox", "npm run build / python -m compileall", true},
		{"no_regression", "no_regression", "every test that passed on the original still passes", "relative test baseline", true},
		{"policy", "policy", "no .github edits, no weakened tests, no path escape, at most 20 files", "path policy", true},
		{"security", "security", "no new high findings", "bandit/semgrep delta", true},
		{"secrets", "secrets", "no secret-looking strings added", "secret scan on the diff", true},
	}
}

func specFor(taskType string) (units []unitSpec, extra []criterion) {
	switch taskType {
	case "ui":
		units = []unitSpec{
			{"u1", "Responsive header and navigation", []string{"src/components/Header.css", "src/components/Header.jsx"}, nil, 2},
			{"u2", "Fluid card grid and spacing tokens", []string{"src/styles/grid.css"}, nil, 1},
			{"u3", "Wire the new layout into the page shell", []string{"src/App.jsx"}, []string{"u1", "u2"}, 1},
		}
		extra = []criterion{
			{"ui_console", "ui_console", "no console errors on load", "headless chromium console capture", true},
			{"ui_overflow", "ui_overflow", "no horizontal overflow at 375, 768 and 1280 px", "scrollWidth <= innerWidth per viewport", true},
			{"ui_axe", "ui_axe", "axe-core violations not increased", "axe-core before/after", true},
			{"ui_smoke", "ui_smoke", "key-flow smoke script passes before and after", "playwright script written by the spec agent", true},
			{"vision_rubric", "vision", "before/after screenshots look clearly better (rubric)", "vision rubric score", false},
		}
	case "refactor":
		units = []unitSpec{
			{"u1", "Extract the pricing rules into pricing.py", []string{"src/pricing.py", "src/cart.py"}, nil, 2},
			{"u2", "Split the oversized checkout module", []string{"src/checkout.py", "src/checkout_steps.py"}, nil, 1},
			{"u3", "Update call sites and imports", []string{"src/app.py"}, []string{"u1", "u2"}, 1},
		}
		extra = []criterion{
			{"characterization", "characterization", "generated characterization tests pass before and after", "spec agent tests run on the original and the result", true},
			{"api_surface", "api_surface", "public API surface unchanged", "exported symbols/signatures diff", true},
			{"lint_no_worse", "lint", "lint and typecheck no worse than the original", "ruff/mypy delta", true},
			{"file_size", "metric", "no module above 300 lines (the task's stated goal)", "line counts", true},
			{"readability", "review", "readability review of the diff", "reviewer rubric", false},
		}
	case "tests":
		units = []unitSpec{
			{"u1", "Add tests for the cart totals", []string{"tests/test_cart.py"}, nil, 1},
			{"u2", "Add tests for coupons", []string{"tests/test_coupons.py"}, nil, 1},
		}
		extra = []criterion{
			{"new_tests_pass", "command", "the new tests pass and fail when the code is mutated", "pytest + mutation probe", true},
			{"coverage_up", "metric", "line coverage of the target module increases", "coverage.py delta", true},
		}
	case "perf":
		units = []unitSpec{{"u1", "Cache repeated price lookups", []string{"src/pricing.py"}, nil, 2}, {"u2", "Batch database reads", []string{"src/store.py"}, nil, 1}}
		extra = []criterion{
			{"benchmark", "benchmark", "benchmark at least 20% faster, within noise bounds", "agent-written benchmark, 5 runs", true},
			{"plan_adherence", "review", "changes stay within the stated scope", "reviewer rubric", false},
		}
	case "deps":
		units = []unitSpec{{"u1", "Bump the dependency and fix call sites", []string{"requirements.txt", "src/http.py"}, nil, 1}}
		extra = []criterion{
			{"audit_clean", "command", "dependency audit shows no new advisories", "pip-audit / npm audit delta", true},
			{"lockfile", "command", "lockfile resolves and installs", "lockfile install", true},
		}
	case "docs":
		units = []unitSpec{{"u1", "Document the public API", []string{"README.md", "docs/api.md"}, nil, 1}}
		extra = []criterion{
			{"link_check", "command", "all links in the changed docs resolve", "link checker", true},
			{"plan_adherence", "review", "docs match the code", "reviewer rubric", false},
		}
	case "migration":
		units = []unitSpec{{"u1", "Port the module to the new API", []string{"src/client.py"}, nil, 2}, {"u2", "Update tests and call sites", []string{"src/app.py"}, []string{"u1"}, 1}}
		extra = []criterion{
			{"migration_smoke", "command", "smoke script passes on the new API", "agent-written smoke command", true},
			{"plan_adherence", "review", "no leftovers of the old API", "reviewer rubric", false},
		}
	case "other":
		units = []unitSpec{{"u1", "Carry out the task", []string{"src/app.py"}, nil, 1}}
		extra = []criterion{{"command_exit", "command", "the synthesized check command exits 0", "planner-written command", true}}
	default: // feature
		units = []unitSpec{
			{"u1", "Percentage coupons in the pricing engine", []string{"src/pricing.py"}, nil, 2},
			{"u2", "Coupon field in the checkout form", []string{"src/checkout.py"}, nil, 1},
			{"u3", "Wire the coupon into the order flow", []string{"src/app.py"}, []string{"u1", "u2"}, 1},
		}
		extra = []criterion{
			{"acceptance", "acceptance", "acceptance tests written FIRST by the spec agent fail on the original and pass now", "spec-test agent tests", true},
			{"plan_adherence", "review", "the diff implements what the task asks, nothing more", "reviewer rubric", false},
		}
	}
	return units, extra
}

// swarmRun drives one scripted swarm run.
type swarmRun struct {
	a                *Agent
	rr               *repoRun
	emit             func(typ string, data map[string]any)
	fast             func(typ string, data map[string]any) // no pause (tool chatter)
	taskType         string
	maxWorkers       int
	tokenLimit       int
	wallLimit        int
	mu               sync.Mutex
	active, peak     int
	spawned          int
	tokens           int
	crit             []criterion
	units            []unitSpec
	artifacts        []fakeArtifact
	files            map[string]any
	diff             string
	advisory         []any
	hardPass, hardTt int
}

func (s *swarmRun) track(delta int) {
	s.mu.Lock()
	s.active += delta
	if s.active > s.peak {
		s.peak = s.active
	}
	s.mu.Unlock()
}

func (s *swarmRun) agent(id, role, unit string, variant int, status, summary string) {
	d := map[string]any{"id": id, "role": role, "status": status, "model": "fake-nano", "isolation": "local"}
	if role == "planner" || role == "integrator" || role == "critic" {
		d["model"] = "fake-super"
	}
	if role == "mapper" || role == "verifier" {
		d["model"] = ""
	}
	if unit != "" {
		d["unit_id"] = unit
	} else {
		d["unit_id"] = nil
	}
	if variant > 0 {
		d["variant"] = variant
	} else {
		d["variant"] = nil
	}
	if summary != "" {
		d["summary"] = summary
	}
	if status == "spawned" {
		s.mu.Lock()
		s.spawned++
		s.mu.Unlock()
	}
	if status == "done" || status == "failed" || status == "cancelled" {
		d["tokens"] = 900 + len(id)*13
		d["steps"] = 4
		s.mu.Lock()
		s.tokens += 900 + len(id)*13
		s.mu.Unlock()
	}
	s.emit("agent", d)
}

func (s *swarmRun) tool(agentID, name, target string, ok bool, note string) {
	d := map[string]any{"agent_id": agentID, "name": name, "ok": ok, "ms": 12 + len(target)}
	if target != "" {
		d["target"] = target
	}
	if note != "" {
		d["note"] = note
	}
	s.fast("tool", d)
}

func (s *swarmRun) budget(workers int) {
	s.mu.Lock()
	used := s.tokens
	s.mu.Unlock()
	s.fast("budget", map[string]any{"tokens_used": used, "tokens_limit": s.tokenLimit, "wall_s": 3 + used/1000, "wall_limit_s": s.wallLimit, "workers_active": workers})
}

func (s *swarmRun) addArtifact(a fakeArtifact) {
	s.artifacts = append(s.artifacts, a)
	s.rr.mu.Lock()
	s.rr.artifacts = append(s.rr.artifacts, a)
	s.rr.mu.Unlock()
	d := map[string]any{"id": a.ID, "kind": a.Kind, "label": a.Label, "phase": a.Phase, "mime": a.Mime}
	if a.Viewport != "" {
		d["viewport"] = a.Viewport
	}
	s.emit("artifact", d)
}

func (s *swarmRun) variantsFor(u unitSpec) int {
	v := u.variants
	if s.maxWorkers <= 1 {
		return 1
	}
	if v > s.maxWorkers-1 {
		v = s.maxWorkers - 1
	}
	if v < 1 {
		v = 1
	}
	return v
}

// runUnit runs one unit's worker variants; the first variant wins and the
// others are cancelled.
func (s *swarmRun) runUnit(u unitSpec, repair bool, wg *sync.WaitGroup) {
	defer wg.Done()
	n := s.variantsFor(u)
	s.emit("unit", map[string]any{"id": u.id, "status": "running", "files": u.scope})
	var ids []string
	for v := 1; v <= n; v++ {
		id := fmt.Sprintf("%s-v%d", u.id, v)
		ids = append(ids, id)
		s.agent(id, "worker", u.id, v, "spawned", "")
		s.track(1)
		s.agent(id, "worker", u.id, v, "running", "")
	}
	s.budget(s.activeNow())
	for _, id := range ids {
		s.tool(id, "read_file", u.scope[0], true, "")
		s.tool(id, "search", "symbols", true, "3 matches")
	}
	winner := ids[0]
	for i, id := range ids {
		s.tool(id, "write_file", u.scope[0], true, "")
		s.tool(id, "run", "unit checks", true, "exit 0")
		if i == 0 {
			s.agent(id, "worker", u.id, 1, "done", "unit checks pass")
		} else {
			s.agent(id, "worker", u.id, i+1, "cancelled", "another variant won")
		}
		s.track(-1)
	}
	diff := fmt.Sprintf("--- a/%[1]s\n+++ b/%[1]s\n@@ -1,2 +1,3 @@\n+# %[2]s\n", u.scope[0], u.title)
	if repair {
		diff += "+# repair after verification feedback\n"
	}
	s.mu.Lock()
	for _, f := range u.scope {
		s.files[f] = "# " + u.title + "\n"
	}
	s.diff += diff
	s.mu.Unlock()
	s.emit("unit", map[string]any{"id": u.id, "status": "passed", "winner_variant": 1, "files": u.scope, "diff": diff, "checks": map[string]any{"passed": 3, "total": 3}})
	_ = winner
}

func (s *swarmRun) activeNow() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.active
}

// runUnits executes units honouring depends_on; independent units run in
// parallel goroutines (unless the worker cap is 1).
func (s *swarmRun) runUnits(units []unitSpec, repair bool) {
	done := map[string]bool{}
	remaining := append([]unitSpec(nil), units...)
	for len(remaining) > 0 {
		var ready, rest []unitSpec
		for _, u := range remaining {
			ok := true
			for _, d := range u.deps {
				if !done[d] {
					ok = false
				}
			}
			if ok {
				ready = append(ready, u)
			} else {
				rest = append(rest, u)
			}
		}
		if len(ready) == 0 { // malformed deps: run the rest sequentially
			ready, rest = rest, nil
		}
		var wg sync.WaitGroup
		if s.maxWorkers <= 1 {
			for _, u := range ready {
				wg.Add(1)
				s.runUnit(u, repair, &wg)
			}
		} else {
			for _, u := range ready {
				wg.Add(1)
				go s.runUnit(u, repair, &wg)
			}
			wg.Wait()
		}
		for _, u := range ready {
			done[u.id] = true
		}
		remaining = rest
	}
}

type verifyOutcome struct {
	results  []map[string]any
	hardPass bool
	counts   map[string]int
}

// verify emits a verify event. failing names criteria that fail in this round.
func (s *swarmRun) verify(round int, failing map[string]bool, skipped map[string]string, artifactsFor map[string][]string) verifyOutcome {
	var results []map[string]any
	counts := map[string]int{"pass": 0, "fail": 0, "skip": 0, "advisory": 0}
	hardAll := true
	hardPass, hardTotal := 0, 0
	for _, c := range s.crit {
		status, detail := "pass", c.description+": ok"
		var score any
		switch {
		case !c.hard:
			status, detail, score = "advisory", c.description+": reviewed, no blocking concerns", 0.82
		case failing[c.id]:
			status, detail = "fail", c.description+": FAILED in round "+fmt.Sprint(round)
		}
		if why, ok := skipped[c.id]; ok {
			status, detail = "skip", why
		}
		if c.hard {
			hardTotal++
			if status == "pass" {
				hardPass++
			} else if status == "fail" {
				hardAll = false
			}
		}
		counts[status]++
		r := map[string]any{"criterion_id": c.id, "kind": c.kind, "hard": c.hard, "status": status, "detail": detail, "artifacts": artifactsFor[c.id]}
		if score != nil {
			r["score"] = score
		}
		results = append(results, r)
	}
	// A partial run carries a user-stated criterion without an executable verifier.
	for id, why := range skipped {
		found := false
		for _, c := range s.crit {
			if c.id == id {
				found = true
			}
		}
		if !found {
			counts["skip"]++
			results = append(results, map[string]any{"criterion_id": id, "kind": "user_stated", "hard": false, "status": "skip", "detail": why, "artifacts": []string{}})
		}
	}
	s.hardPass, s.hardTt = hardPass, hardTotal
	s.emit("verify", map[string]any{"round": round, "results": results, "hard_pass": hardAll,
		"summary": map[string]any{"pass": counts["pass"], "fail": counts["fail"], "skip": counts["skip"], "advisory": counts["advisory"]}})
	return verifyOutcome{results: results, hardPass: hardAll, counts: counts}
}

func (s *swarmRun) planEvent(taskType, source string) map[string]any {
	crit := make([]any, 0, len(s.crit))
	for _, c := range s.crit {
		crit = append(crit, c.plan())
	}
	units := make([]any, 0, len(s.units))
	workers := 0
	for _, u := range s.units {
		workers += s.variantsFor(u)
		deps := u.deps
		if deps == nil {
			deps = []string{}
		}
		units = append(units, map[string]any{"id": u.id, "title": u.title, "scope_files": u.scope, "depends_on": deps, "variants": s.variantsFor(u), "role": "worker"})
	}
	par := 3
	if s.maxWorkers < par {
		par = s.maxWorkers
	}
	return map[string]any{"task_type": taskType, "task_type_source": source,
		"summary":  fmt.Sprintf("%s task: %d units, %d hard gates", taskType, len(s.units), s.countHard()),
		"criteria": crit, "units": units,
		"swarm": map[string]any{"max_parallel": par, "workers_planned": workers,
			"limits": map[string]any{"max_workers": s.maxWorkers, "max_tokens": s.tokenLimit, "max_wall_s": s.wallLimit}}}
}

func (s *swarmRun) countHard() int {
	n := 0
	for _, c := range s.crit {
		if c.hard {
			n++
		}
	}
	return n
}

// ---- the whole run -------------------------------------------------------------------

func intFromAny(v any) int {
	switch x := v.(type) {
	case float64:
		return int(x)
	case int:
		return x
	}
	return 0
}

// execute runs the swarm script and returns the callback pieces.
func (a *Agent) executeSwarm(rr *repoRun, taskType, source, engine string, emit func(string, map[string]any), fast func(string, map[string]any)) swarmResult {
	maxWorkers := 8
	if w := intFromAny(rr.limits["max_workers"]); w > 0 && w < maxWorkers {
		maxWorkers = w
	}
	tokenLimit, wallLimit := 2000000, 3600
	if t := intFromAny(rr.limits["max_tokens"]); t > 0 && t < tokenLimit {
		tokenLimit = t
	}
	if w := intFromAny(rr.limits["max_wall_s"]); w > 0 && w < wallLimit {
		wallLimit = w
	}
	units, extra := specFor(taskType)
	s := &swarmRun{a: a, rr: rr, emit: emit, fast: fast, taskType: taskType, maxWorkers: maxWorkers, tokenLimit: tokenLimit, wallLimit: wallLimit,
		crit: append(baseCriteria(), extra...), units: units, files: map[string]any{}}
	// strict promotes named advisory criteria to hard.
	for i := range s.crit {
		for _, id := range rr.strict {
			if s.crit[i].id == id {
				s.crit[i].hard = true
			}
		}
	}
	unsolvable := has(rr.task, "unsolvable")
	partial := has(rr.task, "partial")
	followup := rr.followup != nil

	emit("run_started", map[string]any{"run_id": rr.id, "bug_id": rr.repo, "mode": "fake", "engine": engine, "kind": "repo"})
	emit("repo", map[string]any{"full_name": rr.repo, "branch": rr.branch, "files": 14, "language": "python", "test_command": "python -m unittest", "truncated": false})
	emit("guard", map[string]any{"stage": "input", "verdict": "pass", "reasons": []string{}, "latency_ms": 12})

	if followup {
		s.units = s.units[:1]
	}
	s.agent("planner", "planner", "", 0, "spawned", "")
	s.agent("planner", "planner", "", 0, "running", "")
	emit("plan", s.planEvent(taskType, source))
	s.agent("planner", "planner", "", 0, "done", "plan ready")
	s.agent("mapper", "mapper", "", 0, "spawned", "")
	s.agent("mapper", "mapper", "", 0, "done", "repo map built")
	s.agent("spec", "spec", "", 0, "spawned", "")
	s.agent("spec", "spec", "", 0, "running", "")
	s.tool("spec", "write_file", "tests/test_acceptance.py", true, "")
	s.tool("spec", "run", "validate the tests on the original", true, "fails on original as required")
	s.agent("spec", "spec", "", 0, "done", "verifiers written and validated")

	artifactsFor := map[string][]string{}
	if taskType == "ui" && !followup {
		for _, vp := range []string{"375", "768", "1280"} {
			s.addArtifact(fakeArtifact{ID: "shot-before-" + vp, Kind: "screenshot", Label: "Home page before (" + vp + " px)", Phase: "before", Viewport: vp, Mime: "image/png", Data: tinyPNG(color.RGBA{200, 90, 90, 255})})
		}
	}

	rounds := 1
	failRound1 := map[string]bool{}
	if taskType == "refactor" && !unsolvable {
		failRound1["api_surface"] = true
		rounds = 2
	}
	if unsolvable {
		for _, c := range s.crit {
			if c.hard && c.kind != "build" && c.kind != "secrets" && c.kind != "policy" && c.kind != "security" {
				failRound1[c.id] = true
				break
			}
		}
		if len(failRound1) == 0 {
			failRound1["no_regression"] = true
		}
		rounds = 2
	}

	var final verifyOutcome
	for round := 1; round <= rounds; round++ {
		units := s.units
		repair := false
		if round > 1 {
			repair = true
			s.agent("critic", "critic", "", 0, "spawned", "")
			s.agent("critic", "critic", "", 0, "done", "repair guidance for the failing criteria")
			units = []unitSpec{{"r1", "Repair: restore the public API surface", []string{"src/pricing.py"}, nil, 1}}
		}
		s.runUnits(units, repair)

		if round == 1 && has(rr.task, "conflict") && len(units) > 1 {
			s.agent("integrator", "integrator", "", 0, "spawned", "")
			s.emit("merge", map[string]any{"status": "conflict", "units": unitIDs(units), "conflicts": []string{units[0].scope[0]}})
			s.agent("integrator", "integrator", "", 0, "running", "")
			s.tool("integrator", "apply_patch", units[0].scope[0], true, "conflict resolved")
			s.agent("integrator", "integrator", "", 0, "done", "resolved 1 conflict")
			s.emit("merge", map[string]any{"status": "resolved", "units": unitIDs(units), "conflicts": []string{}})
		} else {
			s.emit("merge", map[string]any{"status": "ok", "units": unitIDs(units), "conflicts": []string{}})
		}
		for _, u := range units {
			s.emit("unit", map[string]any{"id": u.id, "status": "merged", "files": u.scope})
		}
		s.budget(0)

		failing := map[string]bool{}
		if round == 1 {
			failing = failRound1
		} else if unsolvable {
			failing = failRound1
		}
		skipped := map[string]string{}
		if partial {
			skipped["stated_feels_faster"] = "no executable verifier exists for: \"feels noticeably faster\""
		}
		s.agent("verifier", "verifier", "", 0, "spawned", "")
		if taskType == "ui" && round == rounds && !followup {
			for _, vp := range []string{"375", "768", "1280"} {
				s.addArtifact(fakeArtifact{ID: "shot-after-" + vp, Kind: "screenshot", Label: "Home page after (" + vp + " px)", Phase: "after", Viewport: vp, Mime: "image/png", Data: tinyPNG(color.RGBA{70, 150, 90, 255})})
			}
			s.addArtifact(fakeArtifact{ID: "axe-report", Kind: "report", Label: "axe-core violations before/after", Phase: "n/a", Mime: "application/json", Data: []byte(`{"before":4,"after":1}`)})
			artifactsFor["ui_overflow"] = []string{"shot-after-375", "shot-after-768", "shot-after-1280"}
			artifactsFor["ui_axe"] = []string{"axe-report"}
		}
		s.addArtifact(fakeArtifact{ID: fmt.Sprintf("verify-log-%d", round), Kind: "log", Label: fmt.Sprintf("Verifier output, round %d", round), Phase: "n/a", Mime: "text/plain", Data: []byte(fmt.Sprintf("round %d\nbuild: ok\ntests: 42 passed\n", round))})
		artifactsFor["build"] = []string{fmt.Sprintf("verify-log-%d", round)}
		final = s.verify(round, failing, skipped, artifactsFor)
		s.agent("verifier", "verifier", "", 0, "done", "")
		s.budget(0)
		if final.hardPass {
			break
		}
	}

	if has(rr.task, "evilart") {
		rr.mu.Lock()
		rr.artifacts = append(rr.artifacts, evilArtifacts()...) // served, never announced as events
		rr.mu.Unlock()
	}

	outcome := "complete"
	switch {
	case !final.hardPass:
		outcome = "failed"
	case partial:
		outcome = "partial"
	}

	advisory := []any{}
	for _, r := range final.results {
		if st, _ := r["status"].(string); st == "advisory" || (st == "skip" && r["hard"] == false) {
			adv := map[string]any{"criterion_id": r["criterion_id"], "status": st, "detail": r["detail"]}
			if sc, ok := r["score"]; ok {
				adv["score"] = sc
			}
			advisory = append(advisory, adv)
		}
	}
	s.mu.Lock()
	peak, spawned := s.peak, s.spawned
	s.mu.Unlock()
	return swarmResult{
		outcome: outcome, taskType: taskType, hardPass: s.hardPass, hardTotal: s.hardTt, advisory: advisory,
		spawned: spawned, peak: peak, plan: s.planEvent(taskType, source), units: unitCount(s.units),
		files: s.files, diff: s.diff, artifacts: s.artifacts, tokens: s.tokens,
	}
}

func unitIDs(us []unitSpec) []string {
	out := make([]string, 0, len(us))
	for _, u := range us {
		out = append(out, u.id)
	}
	return out
}

func unitCount(us []unitSpec) int { return len(us) }

// swarmResult is what the run reports at the end.
type swarmResult struct {
	outcome, taskType   string
	hardPass, hardTotal int
	advisory            []any
	spawned, peak       int
	plan                map[string]any
	units               int
	files               map[string]any
	diff                string
	artifacts           []fakeArtifact
	tokens              int
}

func (r swarmResult) criteria() map[string]any {
	return map[string]any{"hard_pass": r.hardPass, "hard_total": r.hardTotal, "advisory": r.advisory}
}

func (r swarmResult) agents() map[string]any {
	return map[string]any{"spawned": r.spawned, "peak_parallel": r.peak}
}

func (r swarmResult) node() map[string]any {
	return map[string]any{
		"id": 0, "parent": -1, "depth": 0, "idea": "swarm result", "strategy": "swarm",
		"code": "", "output": fmt.Sprintf("%d/%d hard gates pass", r.hardPass, r.hardTotal),
		"passed": r.hardPass, "total": r.hardTotal, "score": ratio(r.hardPass, r.hardTotal),
		"model": "fake-nano", "latency_ms": 1200, "tokens": r.tokens,
		"files": r.files, "diff": r.diff,
		"policy":   map[string]any{"ok": true, "reasons": []string{}},
		"security": map[string]any{"ok": true, "new_findings": 0},
	}
}

func ratio(a, b int) float64 {
	if b == 0 {
		return 0
	}
	return float64(a) / float64(b)
}

// evilArtifacts are hostile artifacts for testing the backend proxy.
func evilArtifacts() []fakeArtifact {
	return []fakeArtifact{
		{ID: "evil-html", Kind: "report", Label: "html report", Phase: "n/a", Mime: "text/html", Data: []byte("<script>alert(1)</script>")},
		{ID: "evil-svg", Kind: "screenshot", Label: "svg with script", Phase: "n/a", Mime: "image/svg+xml", Data: []byte(`<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>`)},
		{ID: "evil-exe", Kind: "report", Label: "binary", Phase: "n/a", Mime: "application/x-msdownload", Data: []byte("MZ\x90\x00")},
		{ID: "evil-png", Kind: "screenshot", Label: "html pretending to be png", Phase: "n/a", Mime: "image/png", Data: []byte("<html><script>alert(1)</script></html>")},
		{ID: "big-log", Kind: "log", Label: "oversize log", Phase: "n/a", Mime: "text/plain", Data: bytes.Repeat([]byte("x"), 6<<20)},
	}
}

// ---- HTTP: artifacts ------------------------------------------------------------------

func (a *Agent) listArtifacts(w http.ResponseWriter, rr *repoRun) {
	rr.mu.Lock()
	arts := append([]fakeArtifact(nil), rr.artifacts...)
	rr.mu.Unlock()
	out := make([]map[string]any, 0, len(arts)+1)
	for _, f := range arts {
		out = append(out, f.index())
	}
	if has(rr.task, "evilart") {
		// A hostile index entry: the backend must drop ids that are not plain names.
		out = append(out, map[string]any{"id": "../../etc/passwd", "kind": "log", "label": "traversal", "phase": "n/a", "mime": "text/plain", "size": 1})
	}
	writeJSON(w, 200, out)
}

func (a *Agent) getArtifact(w http.ResponseWriter, rr *repoRun, id string) {
	rr.mu.Lock()
	var found *fakeArtifact
	for i := range rr.artifacts {
		if rr.artifacts[i].ID == id {
			found = &rr.artifacts[i]
		}
	}
	rr.mu.Unlock()
	if found == nil {
		writeJSON(w, 404, map[string]any{"detail": "artifact not found"})
		return
	}
	w.Header().Set("Content-Type", found.Mime+"; charset=utf-8")
	w.WriteHeader(200)
	_, _ = w.Write(found.Data)
}
