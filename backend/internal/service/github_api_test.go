package service

import (
	"context"
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"encoding/base64"
	"encoding/pem"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"patchloop-backend/internal/models"
	"patchloop-backend/internal/pkg/crypt"
	"patchloop-backend/internal/repository"

	"github.com/golang-jwt/jwt/v5"
)

func newKey(t *testing.T) *rsa.PrivateKey {
	t.Helper()
	k, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	return k
}

func TestParsePrivateKeyFormats(t *testing.T) {
	k := newKey(t)
	pkcs1 := pem.EncodeToMemory(&pem.Block{Type: "RSA PRIVATE KEY", Bytes: x509.MarshalPKCS1PrivateKey(k)})
	der8, _ := x509.MarshalPKCS8PrivateKey(k)
	pkcs8 := pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: der8})
	for name, in := range map[string]string{
		"pkcs1":          string(pkcs1),
		"pkcs8":          string(pkcs8),
		"base64":         base64.StdEncoding.EncodeToString(pkcs1),
		"escaped newlns": strings.ReplaceAll(string(pkcs1), "\n", `\n`),
	} {
		got, err := ParsePrivateKey(in)
		if err != nil || !got.Equal(k) {
			t.Errorf("%s: %v", name, err)
		}
	}
	for _, bad := range []string{"", "not a key", "-----BEGIN RSA PRIVATE KEY-----\nAAAA\n-----END RSA PRIVATE KEY-----"} {
		if _, err := ParsePrivateKey(bad); err == nil {
			t.Errorf("%q accepted", bad)
		}
	}
}

func TestAppJWTClaims(t *testing.T) {
	k := newKey(t)
	pemB := pem.EncodeToMemory(&pem.Block{Type: "RSA PRIVATE KEY", Bytes: x509.MarshalPKCS1PrivateKey(k)})
	g, err := NewGitHubAPI(GitHubAppConfig{AppID: "42", Slug: "s", PrivateKey: string(pemB)})
	if err != nil {
		t.Fatal(err)
	}
	now := time.Unix(1_800_000_000, 0)
	g.now = func() time.Time { return now }
	tok, err := g.AppJWT()
	if err != nil {
		t.Fatal(err)
	}
	var claims jwt.RegisteredClaims
	parsed, err := jwt.ParseWithClaims(tok, &claims, func(*jwt.Token) (any, error) { return &k.PublicKey, nil },
		jwt.WithValidMethods([]string{"RS256"}), jwt.WithTimeFunc(func() time.Time { return now }))
	if err != nil || !parsed.Valid {
		t.Fatalf("jwt invalid: %v", err)
	}
	if claims.Issuer != "42" {
		t.Errorf("iss = %q", claims.Issuer)
	}
	if !claims.IssuedAt.Before(now) {
		t.Errorf("iat must be backdated for clock drift")
	}
	if claims.ExpiresAt.Sub(now) > 10*time.Minute {
		t.Errorf("exp > 10 minutes: %v", claims.ExpiresAt.Sub(now))
	}
	if parsed.Header["alg"] != "RS256" {
		t.Errorf("alg = %v", parsed.Header["alg"])
	}
	// Unconfigured App: no JWT.
	if _, err := (&GitHubAPI{}).AppJWT(); err == nil {
		t.Error("jwt minted without app config")
	}
}

func TestInstallationTokenCacheAndRefresh(t *testing.T) {
	k := newKey(t)
	pemB := pem.EncodeToMemory(&pem.Block{Type: "RSA PRIVATE KEY", Bytes: x509.MarshalPKCS1PrivateKey(k)})
	var mints atomic.Int32
	expires := time.Now().Add(time.Hour)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/app/installations/9/access_tokens" || r.Method != "POST" || !strings.HasPrefix(r.Header.Get("Authorization"), "Bearer ey") {
			w.WriteHeader(404)
			return
		}
		n := mints.Add(1)
		w.WriteHeader(201)
		_, _ = w.Write([]byte(`{"token":"tok` + string(rune('0'+n)) + `","expires_at":"` + expires.UTC().Format(time.RFC3339) + `"}`))
	}))
	defer srv.Close()
	g, _ := NewGitHubAPI(GitHubAppConfig{AppID: "1", Slug: "s", PrivateKey: string(pemB), APIBase: srv.URL})
	ctx := context.Background()
	t1, err := g.InstallationToken(ctx, 9)
	t2, _ := g.InstallationToken(ctx, 9)
	if err != nil || t1 != "tok1" || t2 != "tok1" || mints.Load() != 1 {
		t.Fatalf("cache: %q %q mints=%d err=%v", t1, t2, mints.Load(), err)
	}
	// Within 5 minutes of expiry the token is re-minted.
	g.now = func() time.Time { return expires.Add(-4 * time.Minute) }
	t3, _ := g.InstallationToken(ctx, 9)
	if t3 != "tok2" || mints.Load() != 2 {
		t.Fatalf("refresh: %q mints=%d", t3, mints.Load())
	}
	// Errors never carry the JWT.
	g2, _ := NewGitHubAPI(GitHubAppConfig{AppID: "1", Slug: "s", PrivateKey: string(pemB), APIBase: srv.URL})
	_, err = g2.InstallationToken(ctx, 404)
	if err == nil || strings.Contains(err.Error(), "eyJ") {
		t.Fatalf("error: %v", err)
	}
}

func TestChecksCombination(t *testing.T) {
	cases := []struct {
		name, runs, status, want string
		failing                  string
	}{
		{"none", `{"check_runs":[]}`, `{"state":"pending","total_count":0,"statuses":[]}`, "none", ""},
		{"green", `{"check_runs":[{"name":"a","status":"completed","conclusion":"success"},{"name":"b","status":"completed","conclusion":"skipped"}]}`, `{"state":"pending","total_count":0}`, "success", ""},
		{"neutral ok", `{"check_runs":[{"name":"a","status":"completed","conclusion":"neutral"}]}`, `{"total_count":0}`, "success", ""},
		{"cancelled fails", `{"check_runs":[{"name":"a","status":"completed","conclusion":"cancelled"}]}`, `{"total_count":0}`, "failure", "a"},
		{"timed out fails", `{"check_runs":[{"name":"a","status":"completed","conclusion":"timed_out"}]}`, `{"total_count":0}`, "failure", "a"},
		{"queued is pending", `{"check_runs":[{"name":"a","status":"queued"}]}`, `{"total_count":0}`, "pending", ""},
		{"failure beats pending", `{"check_runs":[{"name":"a","status":"in_progress"},{"name":"b","status":"completed","conclusion":"failure"}]}`, `{"total_count":0}`, "failure", "b"},
		{"status success", `{"check_runs":[]}`, `{"state":"success","total_count":1,"statuses":[{"context":"ci","state":"success"}]}`, "success", ""},
		{"status error", `{"check_runs":[]}`, `{"state":"failure","total_count":1,"statuses":[{"context":"ci","state":"error"}]}`, "failure", "ci"},
		{"status pending", `{"check_runs":[]}`, `{"state":"pending","total_count":1,"statuses":[{"context":"ci","state":"pending"}]}`, "pending", ""},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if strings.HasSuffix(r.URL.Path, "/check-runs") {
					_, _ = w.Write([]byte(tc.runs))
				} else {
					_, _ = w.Write([]byte(tc.status))
				}
			}))
			defer srv.Close()
			g, _ := NewGitHubAPI(GitHubAppConfig{APIBase: srv.URL})
			sum, err := g.Checks(context.Background(), "t", "o/r", "sha")
			if err != nil || sum.State != tc.want || strings.Join(sum.Failing, ",") != tc.failing {
				t.Fatalf("got %+v err=%v", sum, err)
			}
		})
	}
}

func TestGitHubErrorsAreTruncatedAndTokenFree(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(500)
		_, _ = w.Write([]byte(strings.Repeat("x", 5000)))
	}))
	defer srv.Close()
	g, _ := NewGitHubAPI(GitHubAppConfig{APIBase: srv.URL})
	_, err := g.GetUser(context.Background(), "ghu_SECRET")
	if err == nil || len(err.Error()) > 300 || strings.Contains(err.Error(), "ghu_SECRET") {
		t.Fatalf("error: %v", err)
	}
	// Transport failures do not embed the URL (which may carry secrets).
	g2, _ := NewGitHubAPI(GitHubAppConfig{APIBase: "http://127.0.0.1:1"})
	_, err = g2.GetUser(context.Background(), "ghu_SECRET")
	if err == nil || strings.Contains(err.Error(), "127.0.0.1:1/user") {
		t.Fatalf("transport error leaks url: %v", err)
	}
}

// ---- GitHubService: state + token handling --------------------------------

type memGH struct {
	m map[string]*models.GitHubConnection
}

func (s *memGH) Get(_ context.Context, id string) (*models.GitHubConnection, error) {
	if c, ok := s.m[id]; ok {
		cp := *c
		return &cp, nil
	}
	return nil, repository.ErrNotFound
}
func (s *memGH) Put(_ context.Context, c *models.GitHubConnection) error {
	cp := *c
	s.m[c.UserID] = &cp
	return nil
}
func (s *memGH) Delete(_ context.Context, id string) error { delete(s.m, id); return nil }
func (s *memGH) FindByInstallation(context.Context, int64) (*models.GitHubConnection, error) {
	return nil, repository.ErrNotFound
}
func (s *memGH) FindByLogin(context.Context, string) (*models.GitHubConnection, error) {
	return nil, repository.ErrNotFound
}

func TestStateIsSignedBoundAndExpires(t *testing.T) {
	g := NewGitHubService(&GitHubAPI{}, &memGH{m: map[string]*models.GitHubConnection{}}, nil, "secret")
	now := time.Unix(1_800_000_000, 0)
	g.now = func() time.Time { return now }
	st := g.NewState("user-1")
	if u, err := g.VerifyState(st); err != nil || u != "user-1" {
		t.Fatalf("verify: %q %v", u, err)
	}
	// States differ per call (nonce) and are bound to the signing secret.
	if g.NewState("user-1") == st {
		t.Error("state is deterministic")
	}
	other := NewGitHubService(&GitHubAPI{}, &memGH{}, nil, "other-secret")
	other.now = g.now
	if _, err := other.VerifyState(st); err == nil {
		t.Error("state verified under a different secret")
	}
	// Tampering with the payload (swap the user) invalidates the signature.
	payload, sig, _ := strings.Cut(st, ".")
	forged := base64.RawURLEncoding.EncodeToString([]byte("user-2|"+"9999999999|00")) + "." + sig
	if _, err := g.VerifyState(forged); err == nil {
		t.Error("forged payload accepted")
	}
	_ = payload
	for _, bad := range []string{"", ".", "abc", "a.b", st + "x", "x" + st} {
		if _, err := g.VerifyState(bad); err == nil {
			t.Errorf("%q accepted", bad)
		}
	}
	g.now = func() time.Time { return now.Add(10*time.Minute + time.Second) }
	if _, err := g.VerifyState(st); err == nil {
		t.Error("expired state accepted")
	}
	g.now = func() time.Time { return now.Add(9 * time.Minute) }
	if _, err := g.VerifyState(st); err != nil {
		t.Errorf("state rejected inside the 10 minute window: %v", err)
	}
}

func TestUserTokenRefreshAndReauth(t *testing.T) {
	var refreshed atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = r.ParseForm()
		if r.URL.Path != "/login/oauth/access_token" || r.PostForm.Get("grant_type") != "refresh_token" || r.PostForm.Get("refresh_token") != "ghr_old" {
			w.WriteHeader(400)
			_, _ = w.Write([]byte(`{"error":"bad_refresh_token"}`))
			return
		}
		refreshed.Add(1)
		_, _ = w.Write([]byte(`{"access_token":"ghu_new","refresh_token":"ghr_new","expires_in":28800}`))
	}))
	defer srv.Close()
	api, _ := NewGitHubAPI(GitHubAppConfig{ClientID: "c", ClientSecret: "s", WebBase: srv.URL, APIBase: srv.URL})
	cipher, _ := crypt.Derive("k", "t")
	store := &memGH{m: map[string]*models.GitHubConnection{}}
	svc := NewGitHubService(api, store, cipher, "s")
	now := time.Now()
	svc.now = func() time.Time { return now }

	encOld, _ := cipher.Seal("ghu_old")
	encRef, _ := cipher.Seal("ghr_old")
	exp := now.Add(-time.Hour)
	store.m["u"] = &models.GitHubConnection{UserID: "u", Mode: models.GitHubModeApp, InstallationID: 1, EncUserToken: encOld, EncRefreshToken: encRef, UserTokenExpiresAt: &exp}
	tok, err := svc.UserToken(context.Background(), "u")
	if err != nil || tok != "ghu_new" || refreshed.Load() != 1 {
		t.Fatalf("refresh: %q %v", tok, err)
	}
	if c := store.m["u"]; strings.Contains(c.EncUserToken, "ghu_") || c.UserTokenExpiresAt == nil || !c.UserTokenExpiresAt.After(now) {
		t.Fatalf("stored token: %+v", c)
	}
	// Fresh token is returned without another refresh.
	if tok, _ = svc.UserToken(context.Background(), "u"); tok != "ghu_new" || refreshed.Load() != 1 {
		t.Fatalf("unexpected refresh: %q", tok)
	}
	// Expired with no refresh token (or a rejected one): ask the user to reconnect.
	expired := now.Add(-time.Hour)
	store.m["v"] = &models.GitHubConnection{UserID: "v", Mode: models.GitHubModeApp, InstallationID: 1, EncUserToken: encOld, UserTokenExpiresAt: &expired}
	if _, err := svc.UserToken(context.Background(), "v"); err != ErrNeedUserAuth {
		t.Fatalf("no refresh token: %v", err)
	}
	bad, _ := cipher.Seal("ghr_revoked")
	store.m["w"] = &models.GitHubConnection{UserID: "w", Mode: models.GitHubModeApp, InstallationID: 1, EncUserToken: encOld, EncRefreshToken: bad, UserTokenExpiresAt: &expired}
	if _, err := svc.UserToken(context.Background(), "w"); err != ErrNeedUserAuth {
		t.Fatalf("revoked refresh token: %v", err)
	}
	store.m["x"] = &models.GitHubConnection{UserID: "x", Mode: models.GitHubModeApp, InstallationID: 1}
	if _, err := svc.UserToken(context.Background(), "x"); err != ErrNeedUserAuth {
		t.Fatalf("never authorised: %v", err)
	}
	if _, err := svc.UserToken(context.Background(), "nobody"); err != ErrGitHubNotConnected {
		t.Fatalf("not connected: %v", err)
	}
}

func TestSignatureHelpers(t *testing.T) {
	body := []byte(`{"a":1}`)
	sig := SignGitHubBody("s3cret", body)
	if !VerifyGitHubSignature("s3cret", body, sig) {
		t.Error("valid github signature rejected")
	}
	for name, c := range map[string]struct {
		secret string
		body   []byte
		sig    string
	}{
		"wrong secret":  {"x", body, sig},
		"empty secret":  {"", body, sig},
		"tampered body": {"s3cret", []byte(`{"a":2}`), sig},
		"no prefix":     {"s3cret", body, strings.TrimPrefix(sig, "sha256=")},
		"sha1 prefix":   {"s3cret", body, "sha1=" + strings.TrimPrefix(sig, "sha256=")},
		"empty":         {"s3cret", body, ""},
	} {
		if VerifyGitHubSignature(c.secret, c.body, c.sig) {
			t.Errorf("%s accepted", name)
		}
	}

	now := time.Unix(1_800_000_000, 0)
	ts, ssig := SignSlackRequest("sl", body, now)
	if err := VerifySlackSignature("sl", ts, ssig, body, now); err != nil {
		t.Errorf("valid slack signature: %v", err)
	}
	if err := VerifySlackSignature("sl", ts, ssig, body, now.Add(299*time.Second)); err != nil {
		t.Errorf("inside 5 min window: %v", err)
	}
	if err := VerifySlackSignature("sl", ts, ssig, body, now.Add(301*time.Second)); err != ErrSlackStale {
		t.Errorf("stale: %v", err)
	}
	if err := VerifySlackSignature("sl", ts, ssig, body, now.Add(-301*time.Second)); err != ErrSlackStale {
		t.Errorf("future-dated: %v", err)
	}
	for name, c := range map[string]struct{ secret, ts, sig string }{
		"wrong secret": {"x", ts, ssig}, "empty secret": {"", ts, ssig}, "bad ts": {"sl", "abc", ssig},
		"v1 prefix": {"sl", ts, strings.Replace(ssig, "v0=", "v1=", 1)}, "empty sig": {"sl", ts, ""},
	} {
		if err := VerifySlackSignature(c.secret, c.ts, c.sig, body, now); err == nil {
			t.Errorf("%s accepted", name)
		}
	}
}

func TestMaskAndValidateWebhook(t *testing.T) {
	if got := MaskWebhook("https://hooks.slack.com/services/T0/B0/abcdWXYZ"); got != "https://hooks.slack.com/…WXYZ" {
		t.Errorf("mask = %q", got)
	}
	s := NewSlackSettingsService(nil, nil, nil, false)
	if err := s.ValidateWebhook("https://hooks.slack.com/services/T0000/B0000/abcdWXYZ"); err != nil {
		t.Errorf("valid rejected: %v", err)
	}
	if err := s.ValidateWebhook("http://localhost/x"); err == nil {
		t.Error("loopback accepted without dev mode")
	}
}

func TestRepoAndBranchValidation(t *testing.T) {
	for _, ok := range []string{"octo/widgets", "a-b/c_d.e", "demo/text-tools"} {
		if !ValidRepoName(ok) {
			t.Errorf("%q rejected", ok)
		}
	}
	for _, bad := range []string{"", "octo", "octo/", "/x", "a/b/c", "a/..", "../x", "a b/c", "a/b;rm", "a/b\n", strings.Repeat("a", 101) + "/b"} {
		if ValidRepoName(bad) {
			t.Errorf("repo %q accepted", bad)
		}
	}
	for _, ok := range []string{"main", "feature/x-1", "release_1.2"} {
		if !ValidBranch(ok) {
			t.Errorf("branch %q rejected", ok)
		}
	}
	for _, bad := range []string{"", "-x", "a..b", "a b", "a~1", "a:b", "x/", "a\\b", "refs/heads/..", "a^b"} {
		if ValidBranch(bad) {
			t.Errorf("branch %q accepted", bad)
		}
	}
}

func TestEvaluateMergeGate(t *testing.T) {
	tr, fl := true, false
	cases := []struct {
		name  string
		info  PRInfo
		allow bool
	}{
		{"green", PRInfo{State: "open", Mergeable: &tr, Checks: ChecksSummary{State: "success"}}, true},
		{"none warns", PRInfo{State: "open", Mergeable: &tr, Checks: ChecksSummary{State: "none"}}, true},
		{"pending", PRInfo{State: "open", Mergeable: &tr, Checks: ChecksSummary{State: "pending"}}, false},
		{"failure", PRInfo{State: "open", Mergeable: &tr, Checks: ChecksSummary{State: "failure", Failing: []string{"x"}}}, false},
		{"conflict", PRInfo{State: "open", Mergeable: &fl, Checks: ChecksSummary{State: "success"}}, false},
		{"unknown", PRInfo{State: "open", Checks: ChecksSummary{State: "success"}}, false},
		{"closed", PRInfo{State: "closed", Mergeable: &tr, Checks: ChecksSummary{State: "success"}}, false},
		{"merged", PRInfo{State: "merged", Mergeable: &tr, Checks: ChecksSummary{State: "success"}}, false},
		{"empty state fails closed", PRInfo{Mergeable: &tr, Checks: ChecksSummary{State: "success"}}, false},
		{"empty checks fails closed", PRInfo{State: "open", Mergeable: &tr}, false},
	}
	for _, tc := range cases {
		info := tc.info
		evaluate(&info)
		if info.MergeAllowed != tc.allow {
			t.Errorf("%s: allowed=%v reason=%q", tc.name, info.MergeAllowed, info.Reason)
		}
		if !info.MergeAllowed && info.Reason == "" {
			t.Errorf("%s: refused without a reason", tc.name)
		}
	}
}
