package service

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestAgentClientErrorMapping(t *testing.T) {
	cases := []struct {
		name       string
		status     int
		body       string
		wantStatus int // 0 = expect ErrAgentUnavailable
		wantMsg    string
	}{
		{"pr not configured passes through", 503, `{"detail":"pull requests are not configured"}`, 503, "pull requests are not configured"},
		{"github failure passes through", 502, `{"detail":"could not open pull request: GithubException"}`, 502, "could not open pull request: GithubException"},
		{"crash stays generic", 500, `Internal Server Error`, 0, ""},
		{"proxy page stays generic", 502, `<html>bad gateway</html>`, 0, ""},
		{"client error passes through", 400, `{"detail":"run is not solved"}`, 400, "run is not solved"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(tc.status)
				_, _ = w.Write([]byte(tc.body))
			}))
			defer srv.Close()
			_, err := NewAgentClient(srv.URL, "s").OpenPR(context.Background(), "run1")
			if tc.wantStatus == 0 {
				if !errors.Is(err, ErrAgentUnavailable) {
					t.Fatalf("want ErrAgentUnavailable, got %v", err)
				}
				return
			}
			var ae *AgentError
			if !errors.As(err, &ae) || ae.Status != tc.wantStatus || ae.Message != tc.wantMsg {
				t.Fatalf("want AgentError{%d %q}, got %v", tc.wantStatus, tc.wantMsg, err)
			}
		})
	}
}
