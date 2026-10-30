package service

import (
	"context"
	"fmt"
	"io"
	"mime"
	"net/http"
	"net/url"
	"strings"
	"time"

	"patchloop-backend/internal/observability"
)

// MaxArtifactBytes is the largest artifact the backend will relay (the agent
// caps its own at 5 MB as well).
const MaxArtifactBytes = 5 << 20

// ArtifactBlob is one artifact fetched from the agent.
type ArtifactBlob struct {
	ContentType string // the agent's Content-Type, parameters stripped, lower case
	Data        []byte
}

// ListArtifacts returns the agent's artifact index for a run (raw JSON objects).
func (a *AgentClient) ListArtifacts(ctx context.Context, agentRunID string) ([]map[string]any, error) {
	var out []map[string]any
	if err := a.do(ctx, http.MethodGet, "/runs/"+url.PathEscape(agentRunID)+"/artifacts", nil, &out, 10*time.Second); err != nil {
		return nil, err
	}
	return out, nil
}

// GetArtifact fetches one artifact's bytes. It never follows redirects (the
// shared secret must not leave the agent) and never reads more than
// MaxArtifactBytes+1 bytes.
func (a *AgentClient) GetArtifact(ctx context.Context, agentRunID, artifactID string) (*ArtifactBlob, error) {
	ctx, cancel := context.WithTimeout(ctx, 20*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, a.BaseURL+"/runs/"+url.PathEscape(agentRunID)+"/artifacts/"+url.PathEscape(artifactID), nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("X-Agent-Secret", a.Secret)
	req.Header.Set("Accept", "*/*")
	observability.InjectTraceHeaders(ctx, req.Header)
	client := &http.Client{Transport: a.Transport, Timeout: 20 * time.Second,
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrAgentUnavailable, err)
	}
	defer resp.Body.Close()
	switch {
	case resp.StatusCode == http.StatusNotFound:
		return nil, ErrArtifactNotFound
	case resp.StatusCode >= 500:
		return nil, fmt.Errorf("%w: status %d", ErrAgentUnavailable, resp.StatusCode)
	case resp.StatusCode != http.StatusOK:
		return nil, &AgentError{Status: resp.StatusCode, Message: "agent refused the artifact request"}
	}
	if resp.ContentLength > MaxArtifactBytes {
		return nil, ErrArtifactTooLarge
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, MaxArtifactBytes+1))
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrAgentUnavailable, err)
	}
	if len(data) > MaxArtifactBytes {
		return nil, ErrArtifactTooLarge
	}
	ct := ""
	if mt, _, err := mime.ParseMediaType(resp.Header.Get("Content-Type")); err == nil {
		ct = strings.ToLower(mt)
	}
	return &ArtifactBlob{ContentType: ct, Data: data}, nil
}
