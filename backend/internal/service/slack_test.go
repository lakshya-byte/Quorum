package service

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"patchloop-backend/internal/models"

	"go.mongodb.org/mongo-driver/v2/bson"
)

func TestSlackPayloadShape(t *testing.T) {
	s := NewSlackNotifier("http://unused", "https://app.example")
	run := &models.Run{
		ID: bson.NewObjectID(), BugID: "cart", Engine: "graph", Mode: "live", Solved: true,
		BestNodeID: float64(4), LatencyMs: 4200,
		Nodes: []any{
			map[string]any{"id": float64(0), "passed": float64(2), "total": float64(6)},
			map[string]any{"id": float64(4), "passed": float64(6), "total": float64(6)},
		},
		Usage: map[string]any{"prompt_tokens": float64(100), "completion_tokens": float64(20)},
		PRURL: "https://github.com/o/r/pull/7",
	}
	p := s.BuildRunMessage(run)
	b, _ := json.Marshal(p)
	str := string(b)
	for _, want := range []string{`"type":"header"`, `"type":"actions"`, "6/6 passed", "https://github.com/o/r/pull/7",
		"https://app.example/runs/" + run.ID.Hex(), `"text":"Review PR"`, "120 / 4200 ms"} {
		if !strings.Contains(str, want) {
			t.Fatalf("payload missing %s: %s", want, str)
		}
	}
}

func TestSlackPostErrorHidesWebhookURL(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(500)
	}))
	defer srv.Close()
	s := NewSlackNotifier(srv.URL+"/services/SECRET", "x")
	if code, err := s.Post(context.Background(), map[string]any{"text": "x"}); err == nil || code != 500 {
		t.Fatalf("want 500 error, got %d %v", code, err)
	}
	srv.Close()
	_, err := s.Post(context.Background(), map[string]any{"text": "x"})
	if err == nil || strings.Contains(err.Error(), "SECRET") {
		t.Fatalf("error leaks webhook: %v", err)
	}
}
