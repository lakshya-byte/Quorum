package service

import (
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"time"

	"patchloop-backend/internal/models"
	"patchloop-backend/internal/pkg/crypt"
	"patchloop-backend/internal/repository"
)

var (
	ErrGitHubNotConnected     = errors.New("connect github first")
	ErrGitHubAppNotConfigured = errors.New("github app not configured")
	ErrNeedUserAuth           = errors.New("github user authorization is missing or expired: reconnect GitHub")
	ErrBadState               = errors.New("invalid or expired state")
)

// DemoRepos are the bundled offline repos (the agent ships matching copies).
var DemoRepos = []GitHubRepo{
	{FullName: "demo/inventory-api", DefaultBranch: "main", Description: "Demo: stock levels and reservations (Python)", Language: "Python"},
	{FullName: "demo/billing-utils", DefaultBranch: "main", Description: "Demo: invoice totals and rounding (Python)", Language: "Python"},
	{FullName: "demo/text-tools", DefaultBranch: "main", Description: "Demo: slugify, wrap and truncate helpers (Python)", Language: "Python"},
}

// IsDemoRepo reports whether full is one of the bundled demo repos.
func IsDemoRepo(full string) bool { return strings.HasPrefix(full, "demo/") }

var repoNamePattern = regexp.MustCompile(`^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$`)
var branchPattern = regexp.MustCompile(`^[A-Za-z0-9_./-]{1,200}$`)

// ValidRepoName / ValidBranch guard values that end up in URLs and git refs.
func ValidRepoName(s string) bool {
	return repoNamePattern.MatchString(s) && !strings.Contains(s, "..")
}
func ValidBranch(s string) bool {
	return branchPattern.MatchString(s) && !strings.Contains(s, "..") && !strings.HasPrefix(s, "-") && !strings.HasSuffix(s, "/")
}

type GitHubService struct {
	api      *GitHubAPI
	store    GitHubStore
	cipher   *crypt.Cipher
	stateKey []byte
	now      func() time.Time
}

func NewGitHubService(api *GitHubAPI, store GitHubStore, cipher *crypt.Cipher, stateSecret string) *GitHubService {
	sum := sha256.Sum256([]byte("patchloop|github-state|" + stateSecret))
	return &GitHubService{api: api, store: store, cipher: cipher, stateKey: sum[:], now: time.Now}
}

func (s *GitHubService) API() *GitHubAPI { return s.api }

// ---- signed state ---------------------------------------------------------

func (s *GitHubService) sign(payload string) string {
	m := hmac.New(sha256.New, s.stateKey)
	m.Write([]byte(payload))
	return base64.RawURLEncoding.EncodeToString(m.Sum(nil))
}

// NewState returns a user-bound state valid for 10 minutes.
func (s *GitHubService) NewState(userID string) string {
	nonce := make([]byte, 8)
	_, _ = rand.Read(nonce)
	payload := base64.RawURLEncoding.EncodeToString([]byte(fmt.Sprintf("%s|%d|%x", userID, s.now().Add(10*time.Minute).Unix(), nonce)))
	return payload + "." + s.sign(payload)
}

// VerifyState checks signature and expiry and returns the bound user id.
func (s *GitHubService) VerifyState(state string) (string, error) {
	payload, sig, ok := strings.Cut(state, ".")
	if !ok || !hmac.Equal([]byte(sig), []byte(s.sign(payload))) {
		return "", ErrBadState
	}
	raw, err := base64.RawURLEncoding.DecodeString(payload)
	if err != nil {
		return "", ErrBadState
	}
	parts := strings.Split(string(raw), "|")
	if len(parts) != 3 {
		return "", ErrBadState
	}
	exp, err := strconv.ParseInt(parts[1], 10, 64)
	if err != nil || s.now().Unix() > exp || parts[0] == "" {
		return "", ErrBadState
	}
	return parts[0], nil
}

// ---- status / connect -----------------------------------------------------

type GitHubStatus struct {
	Connected      bool   `json:"connected"`
	Mode           any    `json:"mode"`
	Login          string `json:"login"`
	AvatarURL      string `json:"avatarUrl"`
	InstallationID int64  `json:"installationId"`
	AppConfigured  bool   `json:"appConfigured"`
	RepoCount      int    `json:"repoCount"`
}

func (s *GitHubService) Status(ctx context.Context, userID string) (*GitHubStatus, error) {
	st := &GitHubStatus{AppConfigured: s.api.AppConfigured()}
	c, err := s.store.Get(ctx, userID)
	if err != nil {
		if errors.Is(err, repository.ErrNotFound) {
			return st, nil
		}
		return nil, err
	}
	st.Mode, st.Login, st.AvatarURL, st.InstallationID = c.Mode, c.Login, c.AvatarURL, c.InstallationID
	st.Connected = c.Mode == models.GitHubModeDemo || c.InstallationID != 0
	if c.Mode == models.GitHubModeDemo {
		st.RepoCount = len(DemoRepos)
	} else if st.Connected {
		if repos, err := s.Repos(ctx, userID, ""); err == nil {
			st.RepoCount = len(repos)
		}
	}
	return st, nil
}

func (s *GitHubService) ConnectURL(userID string) (string, error) {
	if !s.api.AppConfigured() {
		return "", ErrGitHubAppNotConfigured
	}
	return s.api.InstallURL(s.NewState(userID)), nil
}

// HandleCallback finishes the install flow: link the installation to the
// state's user and, if GitHub sent a `code`, store that user's own token
// (used so merges run with the user's permission).
func (s *GitHubService) HandleCallback(ctx context.Context, installationID int64, code, state string) error {
	userID, err := s.VerifyState(state)
	if err != nil {
		return err
	}
	conn, err := s.store.Get(ctx, userID)
	if err != nil {
		if !errors.Is(err, repository.ErrNotFound) {
			return err
		}
		conn = &models.GitHubConnection{UserID: userID}
	}
	conn.Mode = models.GitHubModeApp
	if installationID != 0 {
		conn.InstallationID = installationID
	}
	if conn.InstallationID == 0 {
		return errors.New("github did not send an installation id")
	}
	if code != "" {
		tok, err := s.api.ExchangeCode(ctx, code)
		if err != nil {
			return fmt.Errorf("code exchange failed: %w", err)
		}
		if err := s.storeUserToken(conn, tok); err != nil {
			return err
		}
		if u, err := s.api.GetUser(ctx, tok.AccessToken); err == nil {
			conn.Login, conn.AvatarURL = u.Login, u.AvatarURL
		}
	}
	return s.store.Put(ctx, conn)
}

func (s *GitHubService) storeUserToken(conn *models.GitHubConnection, tok *UserTokens) error {
	enc, err := s.cipher.Seal(tok.AccessToken)
	if err != nil {
		return err
	}
	conn.EncUserToken = enc
	conn.EncRefreshToken = ""
	if tok.RefreshToken != "" {
		if conn.EncRefreshToken, err = s.cipher.Seal(tok.RefreshToken); err != nil {
			return err
		}
	}
	conn.UserTokenExpiresAt = tok.ExpiresAt
	return nil
}

func (s *GitHubService) ConnectDemo(ctx context.Context, userID string) error {
	return s.store.Put(ctx, &models.GitHubConnection{UserID: userID, Mode: models.GitHubModeDemo, Login: "demo-user",
		AvatarURL: "https://github.com/identicons/demo-user.png"})
}

func (s *GitHubService) Disconnect(ctx context.Context, userID string) error {
	return s.store.Delete(ctx, userID)
}

// ---- webhook-driven linking ----------------------------------------------

// LinkInstallationByLogin attaches an installation to the user whose
// GitHub login we know (installation created webhook).
func (s *GitHubService) LinkInstallationByLogin(ctx context.Context, login string, installationID int64) {
	if c, err := s.store.FindByLogin(ctx, login); err == nil && c.InstallationID != installationID {
		c.InstallationID = installationID
		_ = s.store.Put(ctx, c)
	}
}

// UnlinkInstallation clears a deleted installation.
func (s *GitHubService) UnlinkInstallation(ctx context.Context, installationID int64) {
	if c, err := s.store.FindByInstallation(ctx, installationID); err == nil {
		c.InstallationID = 0
		_ = s.store.Put(ctx, c)
	}
	s.api.ForgetInstallation(installationID)
}

// UserForInstallation maps a webhook's installation to a PatchLoop user.
func (s *GitHubService) UserForInstallation(ctx context.Context, installationID int64) (string, error) {
	c, err := s.store.FindByInstallation(ctx, installationID)
	if err != nil {
		return "", err
	}
	return c.UserID, nil
}

// ---- tokens ---------------------------------------------------------------

// AgentAuth is what a run needs: an installation token for the agent, or
// Demo=true (no token) for the offline demo account.
type AgentAuth struct {
	Token string
	Demo  bool
}

func (s *GitHubService) connection(ctx context.Context, userID string) (*models.GitHubConnection, error) {
	c, err := s.store.Get(ctx, userID)
	if err != nil {
		if errors.Is(err, repository.ErrNotFound) {
			return nil, ErrGitHubNotConnected
		}
		return nil, err
	}
	if c.Mode != models.GitHubModeDemo && c.InstallationID == 0 {
		return nil, ErrGitHubNotConnected
	}
	return c, nil
}

// AgentToken returns the installation token the agent receives per run. The
// user's own token is never given to the agent.
func (s *GitHubService) AgentToken(ctx context.Context, userID string) (AgentAuth, error) {
	c, err := s.connection(ctx, userID)
	if err != nil {
		return AgentAuth{}, err
	}
	if c.Mode == models.GitHubModeDemo {
		return AgentAuth{Demo: true}, nil
	}
	t, err := s.api.InstallationToken(ctx, c.InstallationID)
	return AgentAuth{Token: t}, err
}

// UserToken returns the user's own token (refreshing it when expired). Used
// only by the merge service.
func (s *GitHubService) UserToken(ctx context.Context, userID string) (string, error) {
	c, err := s.connection(ctx, userID)
	if err != nil {
		return "", err
	}
	if c.EncUserToken == "" {
		return "", ErrNeedUserAuth
	}
	if c.UserTokenExpiresAt != nil && s.now().After(c.UserTokenExpiresAt.Add(-1*time.Minute)) {
		if c.EncRefreshToken == "" {
			return "", ErrNeedUserAuth
		}
		refresh, err := s.cipher.Open(c.EncRefreshToken)
		if err != nil {
			return "", err
		}
		tok, err := s.api.RefreshUserToken(ctx, refresh)
		if err != nil {
			return "", ErrNeedUserAuth
		}
		if err := s.storeUserToken(c, tok); err != nil {
			return "", err
		}
		if err := s.store.Put(ctx, c); err != nil {
			return "", err
		}
		return tok.AccessToken, nil
	}
	return s.cipher.Open(c.EncUserToken)
}

// IsDemo reports whether the user is on the demo account.
func (s *GitHubService) IsDemo(ctx context.Context, userID string) bool {
	c, err := s.store.Get(ctx, userID)
	return err == nil && c.Mode == models.GitHubModeDemo
}

// ---- repos ----------------------------------------------------------------

func (s *GitHubService) Repos(ctx context.Context, userID, q string) ([]GitHubRepo, error) {
	c, err := s.connection(ctx, userID)
	if err != nil {
		return nil, err
	}
	var repos []GitHubRepo
	if c.Mode == models.GitHubModeDemo {
		repos = append(repos, DemoRepos...)
	} else {
		tok, err := s.api.InstallationToken(ctx, c.InstallationID)
		if err != nil {
			return nil, err
		}
		if repos, err = s.api.InstallationRepos(ctx, tok); err != nil {
			return nil, err
		}
	}
	q = strings.ToLower(strings.TrimSpace(q))
	if q == "" {
		return repos, nil
	}
	out := []GitHubRepo{}
	for _, r := range repos {
		if strings.Contains(strings.ToLower(r.FullName+" "+r.Description), q) {
			out = append(out, r)
		}
	}
	return out, nil
}

func (s *GitHubService) Branches(ctx context.Context, userID, owner, repo string) ([]GitHubBranch, error) {
	c, err := s.connection(ctx, userID)
	if err != nil {
		return nil, err
	}
	if !ValidRepoName(owner + "/" + repo) {
		return nil, errors.New("invalid repository name")
	}
	if c.Mode == models.GitHubModeDemo || IsDemoRepo(owner+"/"+repo) {
		return []GitHubBranch{{Name: "main", Default: true}}, nil
	}
	tok, err := s.api.InstallationToken(ctx, c.InstallationID)
	if err != nil {
		return nil, err
	}
	return s.api.Branches(ctx, tok, owner, repo)
}

// RepoGranted reports whether the installation can see repo (case-insensitive).
func (s *GitHubService) RepoGranted(ctx context.Context, userID, repo string) (bool, error) {
	if IsDemoRepo(repo) {
		return true, nil
	}
	repos, err := s.Repos(ctx, userID, "")
	if err != nil {
		return false, err
	}
	for _, r := range repos {
		if strings.EqualFold(r.FullName, repo) {
			return true, nil
		}
	}
	return false, nil
}
