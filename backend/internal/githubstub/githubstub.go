// Package githubstub is a small fake of the parts of api.github.com and
// github.com that PatchLoop calls. Tests point GITHUB_API_URL/GITHUB_WEB_URL
// at it. It verifies the App JWT signature and records who called what.
package githubstub

import (
	"crypto/rsa"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

// Call is one recorded request.
type Call struct {
	Method, Path, Auth string
	Body               map[string]any
}

// Stub is both the API and the web host (one httptest server serves both).
type Stub struct {
	AppID  string
	PubKey *rsa.PublicKey

	InstallToken string // token minted for installations
	UserToken    string // token returned for the OAuth code
	Login        string

	mu        sync.Mutex
	Repos     []map[string]any
	Branches  []string
	Mergeable *bool  // nil = null
	PRState   string // open | closed
	Merged    bool
	CheckRuns []map[string]any
	Statuses  []map[string]any
	calls     []Call
	mints     int
	MergeFail int // when non-zero, merge answers with this status
}

func New(appID string, pub *rsa.PublicKey) *Stub {
	t := true
	return &Stub{AppID: appID, PubKey: pub, InstallToken: "ghs_install_SECRET_TOKEN", UserToken: "ghu_user_SECRET_TOKEN", Login: "octo-owner",
		Repos: []map[string]any{
			{"full_name": "octo/widgets", "private": true, "default_branch": "main", "description": "Widgets", "language": "Go", "updated_at": "2026-01-02T03:04:05Z"},
			{"full_name": "octo/gadgets", "private": false, "default_branch": "trunk", "description": nil, "language": nil, "updated_at": "2026-01-01T00:00:00Z"},
		},
		Branches: []string{"main", "dev"}, Mergeable: &t, PRState: "open",
		CheckRuns: []map[string]any{{"name": "ci", "status": "completed", "conclusion": "success"}},
	}
}

func (s *Stub) Calls() []Call {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]Call(nil), s.calls...)
}

func (s *Stub) Mints() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.mints
}

// CallsTo returns calls whose "METHOD path" starts with prefix.
func (s *Stub) CallsTo(prefix string) []Call {
	var out []Call
	for _, c := range s.Calls() {
		if strings.HasPrefix(c.Method+" "+c.Path, prefix) {
			out = append(out, c)
		}
	}
	return out
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func (s *Stub) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	var body map[string]any
	if strings.Contains(r.Header.Get("Content-Type"), "x-www-form-urlencoded") {
		_ = r.ParseForm()
	} else if r.Body != nil {
		_ = json.NewDecoder(r.Body).Decode(&body)
	}
	auth := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
	s.mu.Lock()
	s.calls = append(s.calls, Call{Method: r.Method, Path: r.URL.Path, Auth: auth, Body: body})
	s.mu.Unlock()

	p := r.URL.Path
	switch {
	case r.Method == http.MethodPost && strings.HasPrefix(p, "/app/installations/") && strings.HasSuffix(p, "/access_tokens"):
		tok, err := jwt.Parse(auth, func(t *jwt.Token) (any, error) { return s.PubKey, nil },
			jwt.WithValidMethods([]string{"RS256"}), jwt.WithIssuer(s.AppID), jwt.WithExpirationRequired())
		if err != nil || !tok.Valid {
			writeJSON(w, 401, map[string]any{"message": "bad credentials"})
			return
		}
		s.mu.Lock()
		s.mints++
		s.mu.Unlock()
		writeJSON(w, 201, map[string]any{"token": s.InstallToken, "expires_at": time.Now().Add(time.Hour).UTC().Format(time.RFC3339)})
	case r.Method == http.MethodPost && p == "/login/oauth/access_token":
		if r.PostForm.Get("code") == "bad" {
			writeJSON(w, 200, map[string]any{"error": "bad_verification_code", "error_description": "The code passed is incorrect or expired."})
			return
		}
		writeJSON(w, 200, map[string]any{"access_token": s.UserToken, "refresh_token": "ghr_refresh", "expires_in": 28800})
	case p == "/user":
		if auth != s.UserToken {
			writeJSON(w, 401, map[string]any{"message": "Bad credentials"})
			return
		}
		writeJSON(w, 200, map[string]any{"login": s.Login, "avatar_url": "https://avatars.example/octo.png"})
	case p == "/installation/repositories":
		if auth != s.InstallToken {
			writeJSON(w, 401, map[string]any{"message": "Bad credentials"})
			return
		}
		writeJSON(w, 200, map[string]any{"total_count": len(s.Repos), "repositories": s.Repos})
	case r.Method == http.MethodGet && strings.HasSuffix(p, "/branches"):
		var bs []map[string]any
		for _, b := range s.Branches {
			bs = append(bs, map[string]any{"name": b})
		}
		writeJSON(w, 200, bs)
	case r.Method == http.MethodGet && strings.HasPrefix(p, "/repos/") && strings.Count(p, "/") == 3:
		writeJSON(w, 200, map[string]any{"default_branch": "main"})
	case r.Method == http.MethodGet && strings.Contains(p, "/pulls/") && !strings.HasSuffix(p, "/merge"):
		s.mu.Lock()
		defer s.mu.Unlock()
		writeJSON(w, 200, map[string]any{"number": 42, "state": s.PRState, "merged": s.Merged, "mergeable": s.Mergeable,
			"mergeable_state": "clean", "html_url": "https://github.com/octo/widgets/pull/42",
			"head": map[string]any{"sha": "abc123", "ref": "patchloop/x-1"}})
	case r.Method == http.MethodGet && strings.HasSuffix(p, "/check-runs"):
		writeJSON(w, 200, map[string]any{"total_count": len(s.CheckRuns), "check_runs": s.CheckRuns})
	case r.Method == http.MethodGet && strings.HasSuffix(p, "/status"):
		st := "pending"
		if len(s.Statuses) > 0 {
			st = "success"
		}
		writeJSON(w, 200, map[string]any{"state": st, "total_count": len(s.Statuses), "statuses": s.Statuses})
	case r.Method == http.MethodPut && strings.HasSuffix(p, "/merge"):
		if s.MergeFail != 0 {
			writeJSON(w, s.MergeFail, map[string]any{"message": "Pull Request is not mergeable"})
			return
		}
		if auth != s.UserToken {
			writeJSON(w, 403, map[string]any{"message": "Resource not accessible by integration"})
			return
		}
		s.mu.Lock()
		s.Merged = true
		s.mu.Unlock()
		writeJSON(w, 200, map[string]any{"merged": true, "sha": "def456", "message": "Pull Request successfully merged"})
	case r.Method == http.MethodPost && strings.HasSuffix(p, "/comments"):
		writeJSON(w, 201, map[string]any{"id": 1})
	default:
		writeJSON(w, 404, map[string]any{"message": fmt.Sprintf("not found: %s %s", r.Method, p)})
	}
}
