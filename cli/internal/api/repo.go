package api

import (
	"context"
	"net/http"
	"net/url"
)

// GitHubStatus is GET /api/github/status.
type GitHubStatus struct {
	Connected      bool   `json:"connected"`
	Mode           string `json:"mode"`
	Login          string `json:"login"`
	AvatarURL      string `json:"avatarUrl"`
	InstallationID int64  `json:"installationId"`
	AppConfigured  bool   `json:"appConfigured"`
	RepoCount      int    `json:"repoCount"`
}

func (c *Client) GitHubStatus(ctx context.Context) (*GitHubStatus, error) {
	var out GitHubStatus
	return &out, c.Do(ctx, http.MethodGet, "/api/github/status", nil, &out)
}

// GitHubConnectURL returns the GitHub App install URL.
func (c *Client) GitHubConnectURL(ctx context.Context) (string, error) {
	var out struct {
		URL string `json:"url"`
	}
	err := c.Do(ctx, http.MethodGet, "/api/github/connect", nil, &out)
	return out.URL, err
}

func (c *Client) GitHubDemo(ctx context.Context) error {
	return c.Do(ctx, http.MethodPost, "/api/github/demo", nil, nil)
}

type Repo struct {
	FullName      string `json:"fullName"`
	Private       bool   `json:"private"`
	DefaultBranch string `json:"defaultBranch"`
	Description   string `json:"description"`
	Language      string `json:"language"`
	UpdatedAt     string `json:"updatedAt"`
}

func (c *Client) Repos(ctx context.Context, q string) ([]Repo, error) {
	var out []Repo
	path := "/api/github/repos"
	if q != "" {
		path += "?q=" + url.QueryEscape(q)
	}
	return out, c.Do(ctx, http.MethodGet, path, nil, &out)
}

type TaskResponse struct {
	RunID  string `json:"runId"`
	Mode   string `json:"mode"`
	Engine string `json:"engine"`
	Repo   string `json:"repo"`
	Branch string `json:"branch"`
}

func (c *Client) CreateTask(ctx context.Context, repo, branch, task string, autoPR bool) (*TaskResponse, error) {
	body := map[string]any{"repo": repo, "task": task, "autoPr": autoPR}
	if branch != "" {
		body["branch"] = branch
	}
	var out TaskResponse
	return &out, c.Do(ctx, http.MethodPost, "/api/tasks", body, &out)
}

func (c *Client) GetRun(ctx context.Context, id string) (*Run, error) {
	var out Run
	return &out, c.Do(ctx, http.MethodGet, "/api/runs/"+url.PathEscape(id), nil, &out)
}

// PRInfo is GET /api/runs/:id/pr.
type PRInfo struct {
	URL       string `json:"url"`
	Number    int    `json:"number"`
	State     string `json:"state"`
	Mergeable *bool  `json:"mergeable"`
	Checks    struct {
		State   string   `json:"state"`
		Failing []string `json:"failing"`
	} `json:"checks"`
	MergeAllowed bool   `json:"mergeAllowed"`
	Reason       string `json:"reason"`
	Warning      string `json:"warning"`
	Fake         bool   `json:"fake"`
}

func (c *Client) PRInfo(ctx context.Context, runID string) (*PRInfo, error) {
	var out PRInfo
	return &out, c.Do(ctx, http.MethodGet, "/api/runs/"+url.PathEscape(runID)+"/pr", nil, &out)
}

type MergeResult struct {
	Merged  bool   `json:"merged"`
	URL     string `json:"url"`
	Method  string `json:"method"`
	By      string `json:"by"`
	Warning string `json:"warning"`
	Fake    bool   `json:"fake"`
}

func (c *Client) Merge(ctx context.Context, runID, method string) (*MergeResult, error) {
	var out MergeResult
	body := map[string]any{}
	if method != "" {
		body["method"] = method
	}
	return &out, c.Do(ctx, http.MethodPost, "/api/runs/"+url.PathEscape(runID)+"/merge", body, &out)
}

func (c *Client) Followup(ctx context.Context, runID, message string) (string, error) {
	var out struct {
		RunID string `json:"runId"`
	}
	err := c.Do(ctx, http.MethodPost, "/api/runs/"+url.PathEscape(runID)+"/followup", map[string]any{"message": message}, &out)
	return out.RunID, err
}

type SlackSettings struct {
	Configured       bool   `json:"configured"`
	WebhookURLMasked string `json:"webhookUrlMasked"`
	Linked           bool   `json:"linked"`
	DefaultRepo      string `json:"defaultRepo"`
	AppConfigured    bool   `json:"appConfigured"`
}

func (c *Client) SlackSettings(ctx context.Context) (*SlackSettings, error) {
	var out SlackSettings
	return &out, c.Do(ctx, http.MethodGet, "/api/settings/slack", nil, &out)
}

func (c *Client) SetSlackWebhook(ctx context.Context, webhook string) error {
	return c.Do(ctx, http.MethodPut, "/api/settings/slack", map[string]any{"webhookUrl": webhook}, nil)
}

func (c *Client) ClearSlackWebhook(ctx context.Context) error {
	return c.Do(ctx, http.MethodDelete, "/api/settings/slack", nil, nil)
}

func (c *Client) TestSlack(ctx context.Context) error {
	return c.Do(ctx, http.MethodPost, "/api/settings/slack/test", nil, nil)
}

type LinkCode struct {
	Code      string `json:"code"`
	ExpiresAt string `json:"expiresAt"`
	Command   string `json:"command"`
}

func (c *Client) SlackLinkCode(ctx context.Context) (*LinkCode, error) {
	var out LinkCode
	return &out, c.Do(ctx, http.MethodPost, "/api/slack/link-code", nil, &out)
}

// Health pings the unauthenticated /health endpoint.
func (c *Client) Health(ctx context.Context) error {
	return c.Do(ctx, http.MethodGet, "/health", nil, nil)
}
