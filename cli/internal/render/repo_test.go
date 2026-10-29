package render

import (
	"bytes"
	"strings"
	"testing"
	"time"

	"patchloop-cli/internal/sse"
)

func TestRendersRepoEvents(t *testing.T) {
	var buf bytes.Buffer
	r := New(&buf, false)
	for _, ev := range []sse.Event{
		{Type: "repo", Data: []byte(`{"full_name":"o/r","branch":"main","files":9,"language":"python","test_command":"pytest","truncated":true}`)},
		{Type: "locate", Data: []byte(`{"files":[{"path":"a.py","reason":"parses input"}]}`)},
		{Type: "repro", Data: []byte(`{"path":"t.py","test_name":"test_x","failed_on_original":true}`)},
		{Type: "repro", Data: []byte(`{"failed_on_original":false}`)},
		{Type: "pr", Data: []byte(`{"url":"https://github.com/o/r/pull/7","number":7,"branch":"patchloop/x-1","updated":true,"fake":true}`)},
	} {
		r.Event(ev)
	}
	out := buf.String()
	for _, want := range []string{"repo o/r@main", "9 files · python · tests: pytest", "size cap", "a.py parses input", "✔ reproducer test_x (t.py) fails on the original code",
		"no reproducer that fails on the original code", "PR #7 updated (new commit): https://github.com/o/r/pull/7", "patchloop/x-1", "[fake mode]"} {
		if !strings.Contains(out, want) {
			t.Errorf("missing %q in:\n%s", want, out)
		}
	}
	if r.PRURL != "https://github.com/o/r/pull/7" {
		t.Errorf("PRURL = %q", r.PRURL)
	}
}

func TestSpinnerDisabledWritesNothingAndEnabledClears(t *testing.T) {
	var off bytes.Buffer
	s := NewSpinner(&off, false)
	s.Start("x")
	s.Pause()
	s.Resume()
	s.Stop()
	if off.Len() != 0 {
		t.Fatalf("disabled spinner wrote %q", off.String())
	}

	var on syncBuffer
	s = NewSpinner(&on, true)
	s.Start("thinking")
	time.Sleep(250 * time.Millisecond)
	s.Pause()
	s.Stop()
	out := on.String()
	if !strings.Contains(out, "thinking") || !strings.HasSuffix(out, "\r\x1b[K") {
		t.Fatalf("spinner output %q", out)
	}
	s.Stop() // idempotent
}
