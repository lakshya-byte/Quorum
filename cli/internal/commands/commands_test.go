package commands

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const goodToken = "plk_testtokentesttokentesttoken"

func fakeBackend(t *testing.T, solved bool) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer "+goodToken {
			w.WriteHeader(401)
			_, _ = w.Write([]byte(`{"error":"invalid or revoked api token"}`))
			return
		}
		switch {
		case r.URL.Path == "/api/auth/me":
			_, _ = w.Write([]byte(`{"user":{"id":"u1","email":"dev@example.com","companyName":"Acme"}}`))
		case r.URL.Path == "/api/bugs":
			_, _ = w.Write([]byte(`[{"id":"cart","title":"Cart total","issue":"x","tier":1}]`))
		case r.URL.Path == "/api/runs" && r.Method == "POST":
			var body map[string]any
			_ = json.NewDecoder(r.Body).Decode(&body)
			if body["bugId"] != "cart" || body["engine"] != "graph" {
				w.WriteHeader(400)
				_, _ = w.Write([]byte(`{"error":"bad"}`))
				return
			}
			w.WriteHeader(201)
			_, _ = w.Write([]byte(`{"runId":"r1","mode":"live","engine":"graph"}`))
		case r.URL.Path == "/api/runs/r1/events":
			w.Header().Set("Content-Type", "text/event-stream")
			fl := w.(http.Flusher)
			evs := []string{
				`{"type":"run_started","data":{"run_id":"a1","bug_id":"cart","mode":"live","engine":"graph"}}`,
				`{"type":"node","data":{"id":0,"depth":0,"idea":"orig","passed":2,"total":6}}`,
				fmt.Sprintf(`{"type":"done","data":{"solved":%v,"best":{"id":0,"passed":6,"total":6},"usage":{"prompt_tokens":10,"completion_tokens":5},"latency_ms":900}}`, solved),
				`{"type":"end"}`,
			}
			for _, e := range evs {
				fmt.Fprintf(w, "data: %s\n\n", e)
				fl.Flush()
			}
		default:
			w.WriteHeader(404)
			_, _ = w.Write([]byte(`{"error":"not found"}`))
		}
	}))
	t.Cleanup(srv.Close)
	return srv
}

func run(t *testing.T, args ...string) (string, string, error) {
	t.Helper()
	apiFlag = ""
	root := NewRoot()
	var out, errb bytes.Buffer
	root.SetOut(&out)
	root.SetErr(&errb)
	root.SetArgs(args)
	err := root.Execute()
	return out.String(), errb.String(), err
}

func TestLoginWhoamiFix(t *testing.T) {
	cfgPath := filepath.Join(t.TempDir(), "sub", "config.json")
	t.Setenv("PATCHLOOP_CONFIG", cfgPath)
	t.Setenv("NO_COLOR", "1")
	srv := fakeBackend(t, true)

	if _, _, err := run(t, "login", "--token", "plk_wrongwrongwrongwrong", "--api", srv.URL); err == nil {
		t.Fatal("login with bad token should fail")
	}
	out, _, err := run(t, "login", "--token", goodToken, "--api", srv.URL)
	if err != nil || !strings.Contains(out, "dev@example.com") {
		t.Fatalf("login: %v %s", err, out)
	}
	st, err := os.Stat(cfgPath)
	if err != nil || st.Mode().Perm() != 0o600 {
		t.Fatalf("config mode: %v %v", st.Mode(), err)
	}

	out, _, err = run(t, "whoami")
	if err != nil || !strings.Contains(out, "dev@example.com") {
		t.Fatalf("whoami: %v %s", err, out)
	}
	out, _, err = run(t, "bugs")
	if err != nil || !strings.Contains(out, "cart") {
		t.Fatalf("bugs: %v %s", err, out)
	}

	out, errOut, err := run(t, "fix", "cart", "--engine", "graph")
	if err != nil {
		t.Fatalf("fix: %v\n%s\n%s", err, out, errOut)
	}
	if !strings.Contains(out, "├─ #0 [2/6] orig") || !strings.Contains(out, "✓ SOLVED") || strings.Contains(out, "\x1b[") {
		t.Fatalf("fix output:\n%s", out)
	}

	out, _, err = run(t, "watch", "r1", "--json")
	lines := strings.Split(strings.TrimSpace(out), "\n")
	if err != nil || len(lines) != 4 || !json.Valid([]byte(lines[0])) {
		t.Fatalf("json output: %v %q", err, out)
	}

	if _, _, err := run(t, "fix", "cart", "--engine", "magic"); err == nil {
		t.Fatal("bad engine accepted")
	}
}

func TestFixUnsolvedExitsOne(t *testing.T) {
	t.Setenv("PATCHLOOP_CONFIG", filepath.Join(t.TempDir(), "config.json"))
	srv := fakeBackend(t, false)
	if _, _, err := run(t, "login", "--token", goodToken, "--api", srv.URL); err != nil {
		t.Fatal(err)
	}
	_, _, err := run(t, "fix", "cart", "--engine", "graph")
	var ee *ExitError
	if !errors.As(err, &ee) || ee.Code != 1 {
		t.Fatalf("want exit 1, got %v", err)
	}
}

func TestNotLoggedIn(t *testing.T) {
	t.Setenv("PATCHLOOP_CONFIG", filepath.Join(t.TempDir(), "none.json"))
	_, _, err := run(t, "whoami")
	if err == nil || !strings.Contains(err.Error(), "not logged in") {
		t.Fatalf("got %v", err)
	}
}
