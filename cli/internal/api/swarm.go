package api

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
)

// Limits are the optional per-task swarm budgets (the server clamps them).
type Limits struct {
	MaxWorkers int   `json:"maxWorkers,omitempty"`
	MaxTokens  int64 `json:"maxTokens,omitempty"`
	MaxWallS   int   `json:"maxWallS,omitempty"`
}

// TaskOptions are the optional parts of POST /api/tasks.
type TaskOptions struct {
	Branch   string
	AutoPR   bool
	TaskType string // "" = server default (auto)
	Strict   []string
	Limits   *Limits
}

// CreateTaskWith starts a repo task with swarm options.
func (c *Client) CreateTaskWith(ctx context.Context, repo, task string, o TaskOptions) (*TaskResponse, error) {
	body := map[string]any{"repo": repo, "task": task, "autoPr": o.AutoPR}
	if o.Branch != "" {
		body["branch"] = o.Branch
	}
	if o.TaskType != "" {
		body["taskType"] = o.TaskType
	}
	if len(o.Strict) > 0 {
		body["strict"] = o.Strict
	}
	if o.Limits != nil {
		body["limits"] = o.Limits
	}
	var out TaskResponse
	return &out, c.Do(ctx, http.MethodPost, "/api/tasks", body, &out)
}

// Artifact is one entry of a run's artifact index.
type Artifact struct {
	ID       string `json:"id"`
	Kind     string `json:"kind"`
	Label    string `json:"label"`
	Phase    string `json:"phase"`
	Viewport string `json:"viewport"`
	Mime     string `json:"mime"`
	Size     int64  `json:"size"`
}

// Question is one clarifying question of a needs_input run.
type Question struct {
	ID   string `json:"id"`
	Text string `json:"text"`
}

// CriteriaSummary is the run's verdict over its plan's criteria.
type CriteriaSummary struct {
	HardPass  int              `json:"hardPass"`
	HardTotal int              `json:"hardTotal"`
	Advisory  []map[string]any `json:"advisory"`
}

// MaxArtifactBytes caps what the CLI downloads per artifact.
const MaxArtifactBytes = 6 << 20

var artifactID = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`)

// ValidArtifactID is true for ids that are safe as a path segment and file name.
func ValidArtifactID(id string) bool { return artifactID.MatchString(id) }

// Artifacts lists a run's artifacts.
func (c *Client) Artifacts(ctx context.Context, runID string) ([]Artifact, error) {
	var out []Artifact
	return out, c.Do(ctx, http.MethodGet, "/api/runs/"+url.PathEscape(runID)+"/artifacts", nil, &out)
}

// DownloadArtifact fetches one artifact's bytes (at most MaxArtifactBytes).
func (c *Client) DownloadArtifact(ctx context.Context, runID, id string) ([]byte, error) {
	if !ValidArtifactID(id) {
		return nil, fmt.Errorf("refusing artifact id %q", id)
	}
	req, err := c.newRequest(ctx, http.MethodGet, "/api/runs/"+url.PathEscape(runID)+"/artifacts/"+url.PathEscape(id), nil)
	if err != nil {
		return nil, err
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		return nil, apiError(resp)
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, MaxArtifactBytes+1))
	if err != nil {
		return nil, err
	}
	if len(data) > MaxArtifactBytes {
		return nil, fmt.Errorf("artifact %s is larger than %d bytes", id, MaxArtifactBytes)
	}
	return data, nil
}

// Answer answers a needs_input run's questions; the server re-runs it as a child run.
func (c *Client) Answer(ctx context.Context, runID string, answers map[string]string) (string, error) {
	var out struct {
		RunID string `json:"runId"`
	}
	err := c.Do(ctx, http.MethodPost, "/api/runs/"+url.PathEscape(runID)+"/answers", map[string]any{"answers": answers}, &out)
	return out.RunID, err
}
