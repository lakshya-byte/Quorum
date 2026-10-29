package service

import (
	"bytes"
	"context"
	"crypto/rsa"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

// GitHubAPIError is a non-2xx answer from GitHub. The message never contains
// credentials.
type GitHubAPIError struct {
	Status  int
	Message string
}

func (e *GitHubAPIError) Error() string {
	return fmt.Sprintf("github returned %d: %s", e.Status, e.Message)
}

// GitHubAppConfig configures the GitHub App client. APIBase and WebBase are
// overridable so tests can point them at an httptest server.
type GitHubAppConfig struct {
	AppID        string
	Slug         string
	PrivateKey   string // PEM or base64 of PEM
	ClientID     string
	ClientSecret string
	APIBase      string
	WebBase      string
}

// GitHubAPI talks to GitHub as the App (JWT -> installation tokens) and as a
// user (OAuth user-to-server token).
type GitHubAPI struct {
	cfg    GitHubAppConfig
	key    *rsa.PrivateKey
	client *http.Client
	now    func() time.Time

	mu    sync.Mutex
	cache map[int64]cachedToken
}

type cachedToken struct {
	token   string
	expires time.Time
}

// ParsePrivateKey accepts a PEM (PKCS#1 or PKCS#8) or base64 of a PEM.
func ParsePrivateKey(s string) (*rsa.PrivateKey, error) {
	s = strings.TrimSpace(strings.ReplaceAll(s, `\n`, "\n"))
	if !strings.Contains(s, "BEGIN") {
		dec, err := base64.StdEncoding.DecodeString(s)
		if err != nil {
			return nil, errors.New("GITHUB_APP_PRIVATE_KEY is neither PEM nor base64 PEM")
		}
		s = string(dec)
	}
	block, _ := pem.Decode([]byte(s))
	if block == nil {
		return nil, errors.New("GITHUB_APP_PRIVATE_KEY: no PEM block found")
	}
	if k, err := x509.ParsePKCS1PrivateKey(block.Bytes); err == nil {
		return k, nil
	}
	k, err := x509.ParsePKCS8PrivateKey(block.Bytes)
	if err != nil {
		return nil, errors.New("GITHUB_APP_PRIVATE_KEY: unsupported key format")
	}
	rk, ok := k.(*rsa.PrivateKey)
	if !ok {
		return nil, errors.New("GITHUB_APP_PRIVATE_KEY is not an RSA key")
	}
	return rk, nil
}

func NewGitHubAPI(cfg GitHubAppConfig) (*GitHubAPI, error) {
	if cfg.APIBase == "" {
		cfg.APIBase = "https://api.github.com"
	}
	if cfg.WebBase == "" {
		cfg.WebBase = "https://github.com"
	}
	cfg.APIBase = strings.TrimRight(cfg.APIBase, "/")
	cfg.WebBase = strings.TrimRight(cfg.WebBase, "/")
	g := &GitHubAPI{cfg: cfg, client: &http.Client{Timeout: 20 * time.Second}, now: time.Now, cache: map[int64]cachedToken{}}
	if cfg.PrivateKey != "" {
		k, err := ParsePrivateKey(cfg.PrivateKey)
		if err != nil {
			return nil, err
		}
		g.key = k
	}
	return g, nil
}

// AppConfigured reports whether installs can be started and tokens minted.
func (g *GitHubAPI) AppConfigured() bool {
	return g != nil && g.cfg.AppID != "" && g.cfg.Slug != "" && g.key != nil
}

// UserAuthConfigured reports whether the App's OAuth credentials are set
// (needed for merges as the user).
func (g *GitHubAPI) UserAuthConfigured() bool {
	return g != nil && g.cfg.ClientID != "" && g.cfg.ClientSecret != ""
}

// InstallURL is where the browser is sent to install the App.
func (g *GitHubAPI) InstallURL(state string) string {
	return fmt.Sprintf("%s/apps/%s/installations/new?state=%s", g.cfg.WebBase, url.PathEscape(g.cfg.Slug), url.QueryEscape(state))
}

// AppJWT signs the App JWT (RS256, iss = app id, exp <= 10 minutes). iat is
// backdated 60s to tolerate clock drift, as GitHub recommends.
func (g *GitHubAPI) AppJWT() (string, error) {
	if !g.AppConfigured() {
		return "", errors.New("github app not configured")
	}
	now := g.now()
	claims := jwt.RegisteredClaims{
		Issuer:    g.cfg.AppID,
		IssuedAt:  jwt.NewNumericDate(now.Add(-60 * time.Second)),
		ExpiresAt: jwt.NewNumericDate(now.Add(9 * time.Minute)),
	}
	return jwt.NewWithClaims(jwt.SigningMethodRS256, claims).SignedString(g.key)
}

func (g *GitHubAPI) do(ctx context.Context, method, rawURL, bearer string, body any, out any) error {
	var rdr io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return err
		}
		rdr = bytes.NewReader(b)
	}
	req, err := http.NewRequestWithContext(ctx, method, rawURL, rdr)
	if err != nil {
		return err
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	req.Header.Set("X-GitHub-Api-Version", "2022-11-28")
	req.Header.Set("User-Agent", "patchloop")
	if bearer != "" {
		req.Header.Set("Authorization", "Bearer "+bearer)
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := g.client.Do(req)
	if err != nil {
		var uerr *url.Error
		if errors.As(err, &uerr) {
			err = uerr.Err
		}
		return fmt.Errorf("github request failed: %v", err)
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 8<<20))
	if resp.StatusCode >= 300 {
		msg := strings.TrimSpace(string(raw))
		var m struct {
			Message string `json:"message"`
		}
		if json.Unmarshal(raw, &m) == nil && m.Message != "" {
			msg = m.Message
		}
		if len(msg) > 200 {
			msg = msg[:200]
		}
		return &GitHubAPIError{Status: resp.StatusCode, Message: msg}
	}
	if out != nil && len(raw) > 0 {
		if err := json.Unmarshal(raw, out); err != nil {
			return fmt.Errorf("github sent an unreadable response: %v", err)
		}
	}
	return nil
}

// InstallationToken returns a (cached) 1h installation access token.
func (g *GitHubAPI) InstallationToken(ctx context.Context, installationID int64) (string, error) {
	g.mu.Lock()
	if t, ok := g.cache[installationID]; ok && g.now().Before(t.expires.Add(-5*time.Minute)) {
		g.mu.Unlock()
		return t.token, nil
	}
	g.mu.Unlock()

	appJWT, err := g.AppJWT()
	if err != nil {
		return "", err
	}
	var out struct {
		Token     string    `json:"token"`
		ExpiresAt time.Time `json:"expires_at"`
	}
	err = g.do(ctx, http.MethodPost, fmt.Sprintf("%s/app/installations/%d/access_tokens", g.cfg.APIBase, installationID), appJWT, map[string]any{}, &out)
	if err != nil {
		return "", err
	}
	if out.Token == "" {
		return "", errors.New("github returned no installation token")
	}
	g.mu.Lock()
	g.cache[installationID] = cachedToken{token: out.Token, expires: out.ExpiresAt}
	g.mu.Unlock()
	return out.Token, nil
}

// ForgetInstallation drops a cached token (e.g. installation deleted).
func (g *GitHubAPI) ForgetInstallation(id int64) {
	g.mu.Lock()
	delete(g.cache, id)
	g.mu.Unlock()
}

// UserTokens is the result of an OAuth code exchange or refresh.
type UserTokens struct {
	AccessToken  string
	RefreshToken string
	ExpiresAt    *time.Time // nil = does not expire
}

func (g *GitHubAPI) tokenRequest(ctx context.Context, form url.Values) (*UserTokens, error) {
	form.Set("client_id", g.cfg.ClientID)
	form.Set("client_secret", g.cfg.ClientSecret)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, g.cfg.WebBase+"/login/oauth/access_token", strings.NewReader(form.Encode()))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Accept", "application/json")
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("User-Agent", "patchloop")
	resp, err := g.client.Do(req)
	if err != nil {
		var uerr *url.Error
		if errors.As(err, &uerr) {
			err = uerr.Err
		}
		return nil, fmt.Errorf("github token request failed: %v", err)
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	var out struct {
		AccessToken      string `json:"access_token"`
		RefreshToken     string `json:"refresh_token"`
		ExpiresIn        int    `json:"expires_in"`
		Error            string `json:"error"`
		ErrorDescription string `json:"error_description"`
	}
	if err := json.Unmarshal(raw, &out); err != nil {
		return nil, errors.New("github sent an unreadable token response")
	}
	// GitHub answers 200 with {"error": ...} for bad codes.
	if out.Error != "" || out.AccessToken == "" {
		return nil, &GitHubAPIError{Status: http.StatusBadRequest, Message: strings.TrimSpace(out.Error + " " + out.ErrorDescription)}
	}
	t := &UserTokens{AccessToken: out.AccessToken, RefreshToken: out.RefreshToken}
	if out.ExpiresIn > 0 {
		e := g.now().Add(time.Duration(out.ExpiresIn) * time.Second)
		t.ExpiresAt = &e
	}
	return t, nil
}

// ExchangeCode trades the install/authorize `code` for a user token.
func (g *GitHubAPI) ExchangeCode(ctx context.Context, code string) (*UserTokens, error) {
	if !g.UserAuthConfigured() {
		return nil, errors.New("github app user authorization not configured")
	}
	return g.tokenRequest(ctx, url.Values{"code": {code}})
}

// RefreshUserToken exchanges a refresh token for a new user token.
func (g *GitHubAPI) RefreshUserToken(ctx context.Context, refresh string) (*UserTokens, error) {
	if !g.UserAuthConfigured() {
		return nil, errors.New("github app user authorization not configured")
	}
	return g.tokenRequest(ctx, url.Values{"grant_type": {"refresh_token"}, "refresh_token": {refresh}})
}

// GitHubUser is the subset of GET /user we keep.
type GitHubUser struct {
	Login     string `json:"login"`
	AvatarURL string `json:"avatar_url"`
}

func (g *GitHubAPI) GetUser(ctx context.Context, userToken string) (*GitHubUser, error) {
	var u GitHubUser
	if err := g.do(ctx, http.MethodGet, g.cfg.APIBase+"/user", userToken, nil, &u); err != nil {
		return nil, err
	}
	return &u, nil
}

// GitHubRepo is what the API returns for a repository.
type GitHubRepo struct {
	FullName      string `json:"fullName"`
	Private       bool   `json:"private"`
	DefaultBranch string `json:"defaultBranch"`
	Description   string `json:"description"`
	Language      string `json:"language"`
	UpdatedAt     string `json:"updatedAt"`
}

type ghRepo struct {
	FullName      string  `json:"full_name"`
	Private       bool    `json:"private"`
	DefaultBranch string  `json:"default_branch"`
	Description   *string `json:"description"`
	Language      *string `json:"language"`
	UpdatedAt     string  `json:"updated_at"`
}

func (r ghRepo) toRepo() GitHubRepo {
	out := GitHubRepo{FullName: r.FullName, Private: r.Private, DefaultBranch: r.DefaultBranch, UpdatedAt: r.UpdatedAt}
	if r.Description != nil {
		out.Description = *r.Description
	}
	if r.Language != nil {
		out.Language = *r.Language
	}
	return out
}

// InstallationRepos lists repositories the installation was granted
// (GET /installation/repositories), following pagination up to 5 pages.
func (g *GitHubAPI) InstallationRepos(ctx context.Context, installToken string) ([]GitHubRepo, error) {
	var all []GitHubRepo
	for page := 1; page <= 5; page++ {
		var out struct {
			Repositories []ghRepo `json:"repositories"`
		}
		u := fmt.Sprintf("%s/installation/repositories?per_page=100&page=%d", g.cfg.APIBase, page)
		if err := g.do(ctx, http.MethodGet, u, installToken, nil, &out); err != nil {
			return nil, err
		}
		for _, r := range out.Repositories {
			all = append(all, r.toRepo())
		}
		if len(out.Repositories) < 100 {
			break
		}
	}
	return all, nil
}

// GitHubBranch is one branch.
type GitHubBranch struct {
	Name    string `json:"name"`
	Default bool   `json:"default"`
}

func (g *GitHubAPI) Branches(ctx context.Context, token, owner, repo string) ([]GitHubBranch, error) {
	base := fmt.Sprintf("%s/repos/%s/%s", g.cfg.APIBase, url.PathEscape(owner), url.PathEscape(repo))
	var meta struct {
		DefaultBranch string `json:"default_branch"`
	}
	if err := g.do(ctx, http.MethodGet, base, token, nil, &meta); err != nil {
		return nil, err
	}
	var bs []struct {
		Name string `json:"name"`
	}
	if err := g.do(ctx, http.MethodGet, base+"/branches?per_page=100", token, nil, &bs); err != nil {
		return nil, err
	}
	out := make([]GitHubBranch, 0, len(bs))
	for _, b := range bs {
		out = append(out, GitHubBranch{Name: b.Name, Default: b.Name == meta.DefaultBranch})
	}
	return out, nil
}

// PullRequest is the subset of a pull request the merge gate needs.
type PullRequest struct {
	Number         int
	State          string // open | closed
	Merged         bool
	Mergeable      *bool // nil = GitHub is still computing
	MergeableState string
	HeadSHA        string
	HeadRef        string
	HTMLURL        string
}

func (g *GitHubAPI) GetPull(ctx context.Context, token, repo string, number int) (*PullRequest, error) {
	var out struct {
		Number         int    `json:"number"`
		State          string `json:"state"`
		Merged         bool   `json:"merged"`
		Mergeable      *bool  `json:"mergeable"`
		MergeableState string `json:"mergeable_state"`
		HTMLURL        string `json:"html_url"`
		Head           struct {
			SHA string `json:"sha"`
			Ref string `json:"ref"`
		} `json:"head"`
	}
	if err := g.do(ctx, http.MethodGet, fmt.Sprintf("%s/repos/%s/pulls/%d", g.cfg.APIBase, repo, number), token, nil, &out); err != nil {
		return nil, err
	}
	return &PullRequest{Number: out.Number, State: out.State, Merged: out.Merged, Mergeable: out.Mergeable,
		MergeableState: out.MergeableState, HeadSHA: out.Head.SHA, HeadRef: out.Head.Ref, HTMLURL: out.HTMLURL}, nil
}

// ChecksSummary is the combined state of check runs and commit statuses.
type ChecksSummary struct {
	State   string   `json:"state"` // success | failure | pending | none
	Failing []string `json:"failing"`
}

// Checks combines GET /commits/{sha}/check-runs and GET /commits/{sha}/status.
func (g *GitHubAPI) Checks(ctx context.Context, token, repo, sha string) (*ChecksSummary, error) {
	var runs struct {
		CheckRuns []struct {
			Name       string  `json:"name"`
			Status     string  `json:"status"`
			Conclusion *string `json:"conclusion"`
		} `json:"check_runs"`
	}
	if err := g.do(ctx, http.MethodGet, fmt.Sprintf("%s/repos/%s/commits/%s/check-runs?per_page=100", g.cfg.APIBase, repo, url.PathEscape(sha)), token, nil, &runs); err != nil {
		return nil, err
	}
	var combined struct {
		State      string `json:"state"`
		TotalCount int    `json:"total_count"`
		Statuses   []struct {
			Context string `json:"context"`
			State   string `json:"state"`
		} `json:"statuses"`
	}
	if err := g.do(ctx, http.MethodGet, fmt.Sprintf("%s/repos/%s/commits/%s/status", g.cfg.APIBase, repo, url.PathEscape(sha)), token, nil, &combined); err != nil {
		return nil, err
	}

	sum := &ChecksSummary{State: "none", Failing: []string{}}
	pending, total := false, 0
	for _, r := range runs.CheckRuns {
		total++
		if r.Status != "completed" {
			pending = true
			continue
		}
		c := ""
		if r.Conclusion != nil {
			c = *r.Conclusion
		}
		switch c {
		case "success", "neutral", "skipped":
		default:
			sum.Failing = append(sum.Failing, r.Name)
		}
	}
	// A combined status with zero statuses reports "pending": that means none.
	if combined.TotalCount > 0 || len(combined.Statuses) > 0 {
		for _, s := range combined.Statuses {
			total++
			switch s.State {
			case "success":
			case "pending":
				pending = true
			default:
				sum.Failing = append(sum.Failing, s.Context)
			}
		}
	}
	switch {
	case total == 0:
		sum.State = "none"
	case len(sum.Failing) > 0:
		sum.State = "failure"
	case pending:
		sum.State = "pending"
	default:
		sum.State = "success"
	}
	return sum, nil
}

// MergePull calls PUT /repos/{o}/{r}/pulls/{n}/merge with the USER's token.
// This is the only merge call in the whole system.
func (g *GitHubAPI) MergePull(ctx context.Context, userToken, repo string, number int, method, sha string) error {
	body := map[string]any{"merge_method": method}
	if sha != "" {
		body["sha"] = sha // refuse if the head moved since we checked
	}
	return g.do(ctx, http.MethodPut, fmt.Sprintf("%s/repos/%s/pulls/%d/merge", g.cfg.APIBase, repo, number), userToken, body, nil)
}

// CommentIssue posts a comment on an issue or PR as the App installation.
func (g *GitHubAPI) CommentIssue(ctx context.Context, installToken, repo string, number int, body string) error {
	return g.do(ctx, http.MethodPost, fmt.Sprintf("%s/repos/%s/issues/%d/comments", g.cfg.APIBase, repo, number), installToken, map[string]any{"body": body}, nil)
}
