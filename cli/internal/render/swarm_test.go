package render

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"

	"patchloop-cli/internal/sse"
)

func ev(typ, data string) sse.Event {
	return sse.Event{Type: typ, Data: json.RawMessage(data), Raw: `{"type":"` + typ + `"}`}
}

const testPlan = `{"task_type":"ui","task_type_source":"user","summary":"s","criteria":[
{"id":"build","kind":"build","hard":true,"description":"builds"},
{"id":"overflow","kind":"ui_overflow","hard":true,"description":"no overflow"},
{"id":"vision","kind":"vision","hard":false,"description":"looks better"}],
"units":[{"id":"u1","title":"Header","depends_on":[]},{"id":"u2","title":"Grid","depends_on":["u1"]}],
"swarm":{"max_parallel":3,"workers_planned":3}}`

func feedAll(r *Renderer, evs ...sse.Event) {
	for _, e := range evs {
		r.Event(e)
	}
}

func TestLiveFrameShowsPlanLanesGatesAndRedrawsInPlace(t *testing.T) {
	var buf bytes.Buffer
	r := NewLive(&buf, false, 100, 40)
	feedAll(r,
		ev("plan", testPlan),
		ev("agent", `{"id":"u1-v1","role":"worker","unit_id":"u1","variant":1,"status":"running"}`),
		ev("agent", `{"id":"u1-v2","role":"worker","unit_id":"u1","variant":2,"status":"running"}`),
		ev("agent", `{"id":"planner","role":"planner","unit_id":null,"variant":null,"status":"done"}`),
		ev("unit", `{"id":"u1","status":"running"}`),
		ev("tool", `{"agent_id":"u1-v1","name":"write_file","target":"Header.css","ok":true,"ms":9}`),
		ev("budget", `{"tokens_used":3100,"tokens_limit":2000000,"wall_s":12,"wall_limit_s":3600,"workers_active":2}`),
	)
	r.Tick()
	frame := strings.Join(r.sw.Frame(), "\n")
	for _, want := range []string{
		"ui task", "(user)", "2 units", "2 hard + 1 advisory", "up to 3 agents in parallel",
		"Criteria", "hard     build", "advisory vision",
		"Agents", "u1  Header", "v1 ", "write_file Header.css", "v2 ", "u2  Grid",
		"support: planner ✓", "budget: tokens 3,100 / 2,000,000 · 12s / 3600s · 2 agents active",
	} {
		if !strings.Contains(frame, want) {
			t.Errorf("frame lacks %q:\n%s", want, frame)
		}
	}
	// A running agent shows a spinner glyph that moves with Tick.
	f1 := r.sw.Frame()
	r.Tick()
	f2 := r.sw.Frame()
	if strings.Join(f1, "") == strings.Join(f2, "") {
		t.Error("spinner did not advance")
	}
	// Redrawing moves the cursor up over the previous frame (in place), never scrolls it.
	out := buf.String()
	if !strings.Contains(out, "\x1b[") || !strings.Contains(out, "A\r\x1b[K") {
		t.Errorf("no in-place redraw sequences:\n%q", out)
	}

	// Verification results update the gate rows in place.
	feedAll(r,
		ev("agent", `{"id":"u1-v1","role":"worker","unit_id":"u1","variant":1,"status":"done"}`),
		ev("agent", `{"id":"u1-v2","role":"worker","unit_id":"u1","variant":2,"status":"cancelled"}`),
		ev("unit", `{"id":"u1","status":"passed","winner_variant":1}`),
		ev("merge", `{"status":"conflict","units":["u1"],"conflicts":["Header.css"]}`),
		ev("verify", `{"round":1,"results":[{"criterion_id":"build","kind":"build","hard":true,"status":"pass","detail":"build ok"},
{"criterion_id":"overflow","kind":"ui_overflow","hard":true,"status":"fail","detail":"overflow at 375px"},
{"criterion_id":"vision","kind":"vision","hard":false,"status":"advisory","score":0.82,"detail":"nice"}],"hard_pass":false}`),
	)
	frame = strings.Join(r.sw.Frame(), "\n")
	for _, want := range []string{"Criteria and gates (verification round 1)", "✓ hard     build", "✗ hard     overflow", "overflow at 375px", "◇ advisory vision", "0.82", "cancelled", "Merge conflict (u1), conflicts: Header.css"} {
		if !strings.Contains(frame, want) {
			t.Errorf("frame lacks %q:\n%s", want, frame)
		}
	}
	for _, l := range r.sw.Frame() {
		if len([]rune(l)) > 100 {
			t.Errorf("frame line wider than the terminal: %q", l)
		}
	}
}

func TestLiveFrameStaticLinesPrintAboveAndFinishFreezes(t *testing.T) {
	var buf bytes.Buffer
	r := NewLive(&buf, false, 100, 40)
	feedAll(r, ev("plan", testPlan), ev("agent", `{"id":"u1-v1","role":"worker","unit_id":"u1","variant":1,"status":"running"}`))
	buf.Reset()
	feedAll(r, ev("guard", `{"stage":"output","verdict":"pass","reasons":[],"latency_ms":9}`))
	out := buf.String()
	if !strings.Contains(out, "guard output") || !strings.Contains(out, "\x1b[") {
		t.Errorf("a static line must be printed above the frame and the frame redrawn: %q", out)
	}
	buf.Reset()
	feedAll(r, ev("done", `{"solved":true,"outcome":"complete","task_type":"ui","criteria":{"hard_pass":2,"hard_total":2,"advisory":[{"criterion_id":"vision","score":0.8}]},"agents":{"spawned":4,"peak_parallel":2},"usage":{"prompt_tokens":30,"completion_tokens":10},"latency_ms":1500}`))
	out = buf.String()
	if !strings.Contains(out, "✓ COMPLETE  2/2 hard gates pass") || !strings.Contains(out, "4 agents (peak 2 in parallel)") || !strings.Contains(out, "◇ advisory vision 0.80") {
		t.Errorf("final summary:\n%s", out)
	}
	if !r.Done || !r.Solved || r.Outcome != "complete" || r.HardPass != 2 {
		t.Errorf("state: %+v", r)
	}
	// After Finish nothing animates or redraws any more.
	buf.Reset()
	r.Tick()
	if buf.Len() != 0 {
		t.Errorf("ticked after finish: %q", buf.String())
	}
}

func TestOutcomeHeadsForLegacyAndSwarm(t *testing.T) {
	cases := []struct {
		done, want string
		solved     bool
	}{
		{`{"solved":true}`, "✓ SOLVED", true},
		{`{"solved":false}`, "✗ NOT SOLVED", false},
		{`{"solved":false,"outcome":"partial"}`, "◐ PARTIAL", false},
		{`{"solved":false,"outcome":"needs_input"}`, "? NEEDS INPUT", false},
		{`{"solved":false,"outcome":"blocked"}`, "⊘ BLOCKED", false},
		{`{"solved":true,"outcome":"complete"}`, "✓ SOLVED", true},
	}
	for _, tc := range cases {
		var buf bytes.Buffer
		r := New(&buf, false)
		r.Event(ev("done", tc.done))
		if !strings.Contains(buf.String(), tc.want) || r.Solved != tc.solved {
			t.Errorf("%s: %q solved=%v", tc.done, buf.String(), r.Solved)
		}
	}
	var buf bytes.Buffer
	r := New(&buf, false)
	feedAll(r, ev("plan", testPlan), ev("done", `{"solved":false,"outcome":"failed","criteria":{"hard_pass":1,"hard_total":2}}`))
	if !strings.Contains(buf.String(), "✗ FAILED  1/2 hard gates pass") || r.Outcome != "failed" {
		t.Errorf("swarm failed:\n%s", buf.String())
	}
}

func TestFitKeepsEscapeCodesFree(t *testing.T) {
	s := "\x1b[1mhello world\x1b[0m"
	got := fit(s, 5)
	if !strings.HasPrefix(got, "\x1b[1mhello") || strings.Contains(got, "world") || !strings.HasSuffix(got, "\x1b[0m") {
		t.Errorf("%q", got)
	}
	if fit("short", 10) != "short" {
		t.Error("short strings are untouched")
	}
}

func TestPlainModeIsOneLinePerEventWithoutEscapes(t *testing.T) {
	var buf bytes.Buffer
	r := New(&buf, false)
	feedAll(r, ev("plan", testPlan), ev("tool", `{"agent_id":"x","name":"run","ok":true,"ms":1}`),
		ev("clarify", `{"questions":[{"id":"q1","text":"Which?"}]}`))
	out := buf.String()
	if strings.Contains(out, "\x1b[") || strings.Contains(out, "run ") || !strings.Contains(out, "clarify: the planner needs more information") || !strings.Contains(out, "1. [q1] Which?") {
		t.Errorf("plain output:\n%s", out)
	}
}
