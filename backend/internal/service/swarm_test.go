package service

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"patchloop-backend/internal/models"
)

func TestValidateTaskOptions(t *testing.T) {
	for _, tt := range models.TaskTypes {
		if got, _, err := ValidateTaskOptions(strings.ToUpper(tt), nil); err != nil || got != tt {
			t.Errorf("%q: %q %v", tt, got, err)
		}
	}
	if got, _, err := ValidateTaskOptions("", nil); err != nil || got != "auto" {
		t.Errorf("default: %q %v", got, err)
	}
	for _, bad := range []string{"fix", "ui ", "ui;", "../x", "bug fix"} {
		if bad == "ui " {
			continue // surrounding space is trimmed
		}
		if _, _, err := ValidateTaskOptions(bad, nil); err == nil {
			t.Errorf("%q accepted", bad)
		}
	}
	if _, _, err := ValidateTaskOptions("ui", []string{"ok_1", "a b"}); err == nil {
		t.Error("strict id with a space accepted")
	}
	if _, strict, err := ValidateTaskOptions("ui", []string{"a", "a", "b"}); err != nil || len(strict) != 2 {
		t.Errorf("dedupe: %v %v", strict, err)
	}
}

func TestClampLimits(t *testing.T) {
	s := &RunService{caps: SwarmCaps{MaxWorkers: 8, MaxTokens: 1000, MaxWallS: 60}.withDefaults()}
	if l, c, err := s.ClampLimits(nil); l != nil || c || err != nil {
		t.Errorf("nil: %v %v %v", l, c, err)
	}
	if l, c, _ := s.ClampLimits(&models.Limits{}); l != nil || c {
		t.Errorf("zero limits mean defaults: %v %v", l, c)
	}
	l, c, err := s.ClampLimits(&models.Limits{MaxWorkers: 100, MaxTokens: 5000, MaxWallS: 30})
	if err != nil || !c || l.MaxWorkers != 8 || l.MaxTokens != 1000 || l.MaxWallS != 30 {
		t.Errorf("clamp: %v %v %v", l, c, err)
	}
	if _, _, err := s.ClampLimits(&models.Limits{MaxWorkers: -1}); err == nil {
		t.Error("negative accepted")
	}
	d := &RunService{caps: SwarmCaps{}.withDefaults()}
	if d.caps.MaxWorkers != 8 || d.caps.MaxTokens != DefaultMaxTokensCap || d.caps.MaxWallS != DefaultMaxWallSCap {
		t.Errorf("defaults: %+v", d.caps)
	}
}

func TestExtractTaskType(t *testing.T) {
	tt, rest, err := ExtractTaskType("type:Feature add coupons repo:o/n")
	if err != nil || tt != "feature" || rest != "add coupons repo:o/n" {
		t.Errorf("%q %q %v", tt, rest, err)
	}
	tt, rest, _ = ExtractTaskType("add coupons TYPE:ui")
	if tt != "ui" || rest != "add coupons" {
		t.Errorf("%q %q", tt, rest)
	}
	if tt, rest, err := ExtractTaskType("nothing special"); tt != "" || rest != "nothing special" || err != nil {
		t.Errorf("none: %q %q %v", tt, rest, err)
	}
	if _, _, err := ExtractTaskType("type:wizardry x"); err == nil {
		t.Error("unknown type accepted")
	}
	// "prototype:" is not a type token.
	if tt, _, err := ExtractTaskType("the prototype:ui is odd"); tt != "" || err != nil {
		t.Errorf("embedded token matched: %q %v", tt, err)
	}
}

func TestArtifactHelpers(t *testing.T) {
	for _, ok := range []string{"shot-before-375", "a", "report_1", "A9"} {
		if !ValidArtifactID(ok) {
			t.Errorf("%q rejected", ok)
		}
	}
	for _, bad := range []string{"", "..", ".x", "a/b", "a\\b", "a b", "a.png", "a%2f", "-x", strings.Repeat("a", 65), "a\x00b"} {
		if ValidArtifactID(bad) {
			t.Errorf("%q accepted", bad)
		}
	}
	cases := map[string]struct {
		out string
		ok  bool
	}{
		"image/png": {"image/png", true}, "IMAGE/JPEG": {"image/jpeg", true}, "image/svg+xml": {"image/svg+xml", true},
		"text/plain": {"text/plain", true}, "application/json": {"application/json", true},
		"text/html": {"text/plain", true}, "application/octet-stream": {"application/octet-stream", false},
		"application/x-msdownload": {"application/x-msdownload", false}, "": {"", false}, "image/gif": {"image/gif", false},
	}
	for in, want := range cases {
		if out, ok := SafeArtifactMIME(in); out != want.out || ok != want.ok {
			t.Errorf("%q -> %q %v", in, out, ok)
		}
	}
	idx := SanitizeArtifactIndex([]any{
		map[string]any{"id": "ok", "mime": "image/png", "size": float64(10), "kind": "screenshot", "extra": "dropped"},
		map[string]any{"id": "../../etc/passwd", "mime": "text/plain"},
		map[string]any{"id": "exe", "mime": "application/x-msdownload"},
		map[string]any{"id": "h", "mime": "text/html"},
		"not a map",
	})
	if len(idx) != 2 {
		t.Fatalf("index: %v", idx)
	}
	first := idx[0].(map[string]any)
	if _, has := first["extra"]; has || first["size"] != 10 || first["id"] != "ok" {
		t.Errorf("entry: %v", first)
	}
	if idx[1].(map[string]any)["mime"] != "text/plain" {
		t.Errorf("html not downgraded: %v", idx[1])
	}
	if !magicMatches("image/png", []byte("\x89PNG\r\n\x1a\nxxxx")) || magicMatches("image/png", []byte("<html>")) || magicMatches("image/jpeg", []byte("GIF89")) {
		t.Error("magic bytes")
	}
}

func TestParseSlackAnswers(t *testing.T) {
	run := &models.Run{Questions: []any{
		map[string]any{"id": "q1", "text": "a?"}, map[string]any{"id": "scope", "text": "b?"},
	}}
	got := ParseSlackAnswers(run, "1: the cart\n2) all of it\nand more")
	if got["q1"] != "the cart" || got["scope"] != "all of it\nand more" {
		t.Errorf("numbered: %v", got)
	}
	got = ParseSlackAnswers(run, "Scope: only pricing\nq1 - the cart module")
	if got["scope"] != "only pricing" || got["q1"] != "the cart module" {
		t.Errorf("by id: %v", got)
	}
	got = ParseSlackAnswers(run, "just do the cart")
	if len(got) != 1 || got["q1"] != "just do the cart" {
		t.Errorf("free text: %v", got)
	}
	if got := ParseSlackAnswers(&models.Run{}, "hello"); got["q1"] != "hello" {
		t.Errorf("no stored questions: %v", got)
	}
	// Out-of-range numbers fall back to the first question.
	if got := ParseSlackAnswers(run, "7: nope"); got["q1"] != "7: nope" {
		t.Errorf("out of range: %v", got)
	}
}

func TestCleanAnswersAndOutcome(t *testing.T) {
	run := &models.Run{Questions: []any{map[string]any{"id": "q1", "text": "x"}}}
	if _, err := CleanAnswers(run, map[string]string{"q1": " ok "}); err != nil {
		t.Error(err)
	}
	for _, bad := range []map[string]string{nil, {}, {"q2": "x"}, {"q1": " "}, {"q1": strings.Repeat("a", 2001)}, {"q 1": "x"}} {
		if _, err := CleanAnswers(run, bad); err == nil {
			t.Errorf("%v accepted", bad)
		}
	}
	if resolveOutcome("", true) != "complete" || resolveOutcome("", false) != "failed" || resolveOutcome("partial", false) != "partial" ||
		resolveOutcome("weird", true) != "complete" || resolveOutcome("NEEDS_INPUT", false) != "needs_input" {
		t.Error("resolveOutcome")
	}
	cs := criteriaSummary(map[string]any{"hard_pass": float64(3), "hard_total": float64(4), "advisory": []any{map[string]any{"criterion_id": "x"}}})
	if cs == nil || cs.HardPass != 3 || cs.HardTotal != 4 || len(cs.Advisory) != 1 {
		t.Errorf("criteria: %+v", cs)
	}
	if criteriaSummary([]any{1}) != nil || criteriaSummary(map[string]any{}) != nil {
		t.Error("non-summary criteria must be ignored")
	}
	if q := cleanQuestions([]any{map[string]any{"id": "q1", "text": "ok"}, map[string]any{"id": "bad id", "text": "x"}, map[string]any{"id": "q2", "text": " "}}); len(q) != 1 {
		t.Errorf("questions: %v", q)
	}
}

func TestClarifyFromEventsFallback(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-Agent-Secret") != "s3" {
			http.Error(w, "no", 401)
			return
		}
		w.Header().Set("Content-Type", "text/event-stream")
		fmt.Fprint(w, "data: {\"type\":\"repo\",\"data\":{}}\n\n")
		fmt.Fprint(w, "data: {\"type\":\"clarify\",\"data\":{\"questions\":[{\"id\":\"q1\",\"text\":\"which?\"},{\"id\":\"bad id\",\"text\":\"x\"}]}}\n\n")
		w.(http.Flusher).Flush()
		<-r.Context().Done() // the stream never ends: the fallback must stop at clarify
	}))
	defer srv.Close()
	s := &RunService{agent: NewAgentClient(srv.URL, "s3")}
	start := time.Now()
	qs := s.clarifyFromEvents(context.Background(), "run1")
	if len(qs) != 1 || qs[0].(map[string]any)["id"] != "q1" {
		t.Fatalf("questions: %v", qs)
	}
	if time.Since(start) > 2*time.Second {
		t.Fatal("fallback waited for the end of the stream")
	}
}

func TestAgentClientArtifactsNeverFollowRedirectsOrOverread(t *testing.T) {
	var leaked bool
	evil := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-Agent-Secret") != "" {
			leaked = true
		}
	}))
	defer evil.Close()
	agent := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case strings.HasSuffix(r.URL.Path, "/redir"):
			http.Redirect(w, r, evil.URL, http.StatusFound)
		case strings.HasSuffix(r.URL.Path, "/huge"):
			w.Header().Set("Content-Type", "text/plain")
			w.Write(make([]byte, MaxArtifactBytes+10))
		case strings.HasSuffix(r.URL.Path, "/ok"):
			w.Header().Set("Content-Type", "Text/Plain; charset=utf-8")
			w.Write([]byte("hi"))
		default:
			http.NotFound(w, r)
		}
	}))
	defer agent.Close()
	a := NewAgentClient(agent.URL, "s3")
	ctx := context.Background()
	if _, err := a.GetArtifact(ctx, "r", "redir"); err == nil {
		t.Error("a redirect was followed or accepted")
	}
	if leaked {
		t.Fatal("the agent secret was sent to a redirect target")
	}
	if _, err := a.GetArtifact(ctx, "r", "huge"); !errors.Is(err, ErrArtifactTooLarge) {
		t.Errorf("oversize: %v", err)
	}
	if _, err := a.GetArtifact(ctx, "r", "missing"); !errors.Is(err, ErrArtifactNotFound) {
		t.Errorf("missing: %v", err)
	}
	b, err := a.GetArtifact(ctx, "r", "ok")
	if err != nil || b.ContentType != "text/plain" || string(b.Data) != "hi" {
		t.Errorf("ok: %v %+v", err, b)
	}
}

func TestHasPatchAndLabels(t *testing.T) {
	for out, want := range map[string]bool{"complete": true, "partial": true, "failed": false, "needs_input": false, "blocked": false} {
		if got := (&models.Run{Outcome: out}).HasPatch(); got != want {
			t.Errorf("%s: %v", out, got)
		}
	}
	if !(&models.Run{Solved: true}).HasPatch() || (&models.Run{}).HasPatch() {
		t.Error("legacy runs fall back to Solved")
	}
	for out, want := range map[string]string{"complete": "Complete", "partial": "Partial", "needs_input": "Needs input", "failed": "Failed", "blocked": "Blocked"} {
		if OutcomeLabel(out) != want {
			t.Errorf("label %s", out)
		}
	}
}
