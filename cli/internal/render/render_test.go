package render

import (
	"bytes"
	"strings"
	"testing"

	"patchloop-cli/internal/sse"
)

func feed(color bool, in string) (*Renderer, string) {
	var buf bytes.Buffer
	r := New(&buf, color)
	rd := sse.NewReader(strings.NewReader(in))
	for {
		ev, err := rd.Next()
		if err != nil {
			break
		}
		r.Event(ev)
	}
	return r, buf.String()
}

const stream = `data: {"type":"run_started","data":{"run_id":"r1","bug_id":"cart","mode":"live","engine":"graph"}}

data: {"type":"guard","data":{"stage":"input","verdict":"pass","reasons":[],"latency_ms":12}}

data: {"type":"triage","data":{"cause":"qty ignored","strategies":["a","b"]}}

data: {"type":"round","data":{"depth":0}}

data: {"type":"node","data":{"id":0,"parent":-1,"depth":0,"idea":"original","passed":0,"total":6,"model":"m"}}

data: {"type":"node","data":{"id":1,"parent":0,"depth":1,"idea":"partial","passed":3,"total":6}}

data: {"type":"node","data":{"id":4,"parent":1,"depth":2,"idea":"fix","passed":6,"total":6,"latency_ms":1200,"policy":{"ok":false,"reasons":["touches tests"]}}}

data: {"type":"critic","data":{"node_id":1,"lesson":"look at qty"}}

data: {"type":"guard","data":{"stage":"policy","verdict":"block","reasons":["edits tests"],"latency_ms":3}}

data: {"type":"done","data":{"solved":true,"best":{"id":4,"passed":6,"total":6},"usage":{"prompt_tokens":100,"completion_tokens":20},"latency_ms":4200,"time_to_first_node_ms":350}}

data: {"type":"pr","data":{"url":"https://github.com/o/r/pull/1"}}

data: {"type":"end"}

`

func TestRendersTreePlain(t *testing.T) {
	r, out := feed(false, stream)
	if strings.Contains(out, "\x1b[") {
		t.Fatalf("color codes with color=false:\n%s", out)
	}
	for _, want := range []string{
		"PatchLoop run r1  bug=cart mode=live engine=graph",
		"◆ guard input  pass (12ms)",
		"◇ triage: qty ignored",
		"── round 0 ──",
		"\n  ├─ #0 [0/6] original  (m)",
		"\n    ├─ #1 [3/6] partial",
		"\n      ├─ #4 [6/6] fix  (1.2s, policy: touches tests)",
		"✎ critic on #1: look at qty",
		"guard policy BLOCK: edits tests",
		"✓ SOLVED  best #4 6/6 tests",
		"tokens 120 (prompt 100 + completion 20) · latency 4.2s · first node 350ms",
		"PR opened: https://github.com/o/r/pull/1",
	} {
		if !strings.Contains(out, want) {
			t.Fatalf("missing %q in:\n%s", want, out)
		}
	}
	if !r.Solved || !r.Done || !r.Ended || r.PRURL == "" {
		t.Fatalf("state: %+v", r)
	}
}

func TestColorsByTestsPassed(t *testing.T) {
	_, out := feed(true, stream)
	for _, want := range []string{red + "[0/6]", amber + "[3/6]", green + "[6/6]"} {
		if !strings.Contains(out, want) {
			t.Fatalf("missing colored %q in:\n%q", want, out)
		}
	}
}

func TestErrorAndUnsolved(t *testing.T) {
	r, out := feed(false, `data: {"type":"node","data":{"id":0,"depth":0,"passed":1,"total":2}}

data: {"type":"node","da

data: {"type":"error","data":{"stage":"relay","message":"agent connection lost"}}

data: {"type":"end"}

`)
	if r.Solved || r.Done || len(r.Errors) != 1 || !strings.Contains(out, "✗ error relay: agent connection lost") {
		t.Fatalf("state %+v out:\n%s", r, out)
	}
}
