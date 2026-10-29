package service

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"time"

	"patchloop-backend/internal/observability"
)

// ErrAgentUnavailable means the agent could not be reached or failed.
var ErrAgentUnavailable = errors.New("agent unavailable")

// AgentError is a non-2xx answer from the agent that should be shown to the
// caller (e.g. unknown bug -> 400/404).
type AgentError struct {
	Status  int
	Message string
}

func (e *AgentError) Error() string { return fmt.Sprintf("agent returned %d: %s", e.Status, e.Message) }

// AgentClient talks to the internal Python agent over a pooled keep-alive
// HTTP client. Transport is exposed for the SSE reverse proxy so streams
// reuse the same connection pool.
type AgentClient struct {
	BaseURL   string
	Secret    string
	Transport *http.Transport
	client    *http.Client
}

func NewAgentClient(baseURL, secret string) *AgentClient {
	tr := &http.Transport{
		Proxy:                 nil, // the agent is internal; never route via HTTP(S)_PROXY
		DialContext:           (&net.Dialer{Timeout: 3 * time.Second, KeepAlive: 30 * time.Second}).DialContext,
		MaxIdleConns:          100,
		MaxIdleConnsPerHost:   64,
		IdleConnTimeout:       90 * time.Second,
		ResponseHeaderTimeout: 15 * time.Second,
		ForceAttemptHTTP2:     false,
	}
	return &AgentClient{
		BaseURL:   baseURL,
		Secret:    secret,
		Transport: tr,
		client:    &http.Client{Transport: tr, Timeout: 20 * time.Second},
	}
}

type AgentBug struct {
	ID    string `json:"id"`
	Title string `json:"title"`
	Issue string `json:"issue"`
	Tier  any    `json:"tier,omitempty"`
}

type AgentCreateRunRequest struct {
	BugID         string `json:"bug_id"`
	UserID        string `json:"user_id,omitempty"`
	Engine        string `json:"engine,omitempty"`
	ModelOverride string `json:"model_override,omitempty"`
	Replay        bool   `json:"replay,omitempty"`
}

type AgentCreateRunResponse struct {
	RunID  string `json:"run_id"`
	Mode   string `json:"mode"`
	Engine string `json:"engine"`
}

func (a *AgentClient) do(ctx context.Context, method, path string, body any, out any, timeout time.Duration) error {
	var rdr io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return err
		}
		rdr = bytes.NewReader(b)
	}
	if timeout > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, timeout)
		defer cancel()
	}
	req, err := http.NewRequestWithContext(ctx, method, a.BaseURL+path, rdr)
	if err != nil {
		return err
	}
	req.Header.Set("X-Agent-Secret", a.Secret)
	req.Header.Set("Accept", "application/json")
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	observability.InjectTraceHeaders(ctx, req.Header)

	client := a.client
	if timeout > a.client.Timeout {
		client = &http.Client{Transport: a.Transport, Timeout: timeout}
	}
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("%w: %v", ErrAgentUnavailable, err)
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	if resp.StatusCode >= 500 {
		// The agent reports deliberate upstream failures (GitHub down, PRs not
		// configured) as 502/503 with a JSON detail: pass that message on.
		// Anything else (500, a proxy page) stays a generic "unavailable".
		if resp.StatusCode == http.StatusBadGateway || resp.StatusCode == http.StatusServiceUnavailable {
			if msg, ok := agentJSONMessage(raw); ok {
				return &AgentError{Status: resp.StatusCode, Message: msg}
			}
		}
		return fmt.Errorf("%w: status %d", ErrAgentUnavailable, resp.StatusCode)
	}
	if resp.StatusCode >= 300 {
		return &AgentError{Status: resp.StatusCode, Message: agentErrorMessage(raw)}
	}
	if out != nil {
		if err := json.Unmarshal(raw, out); err != nil {
			return fmt.Errorf("%w: bad response: %v", ErrAgentUnavailable, err)
		}
	}
	return nil
}

// agentJSONMessage extracts FastAPI's {"detail": ...} or {"error": ...}.
func agentJSONMessage(raw []byte) (string, bool) {
	var m map[string]any
	if json.Unmarshal(raw, &m) == nil {
		for _, k := range []string{"detail", "error", "message"} {
			if s, ok := m[k].(string); ok && s != "" {
				return s, true
			}
		}
	}
	return "", false
}

// agentErrorMessage is agentJSONMessage with the raw body (truncated) as fallback.
func agentErrorMessage(raw []byte) string {
	if s, ok := agentJSONMessage(raw); ok {
		return s
	}
	if len(raw) > 200 {
		raw = raw[:200]
	}
	return string(raw)
}

func (a *AgentClient) ListBugs(ctx context.Context) ([]AgentBug, error) {
	var bugs []AgentBug
	if err := a.do(ctx, http.MethodGet, "/bugs", nil, &bugs, 10*time.Second); err != nil {
		return nil, err
	}
	return bugs, nil
}

func (a *AgentClient) CreateRun(ctx context.Context, req AgentCreateRunRequest) (*AgentCreateRunResponse, error) {
	var out AgentCreateRunResponse
	if err := a.do(ctx, http.MethodPost, "/runs", req, &out, 15*time.Second); err != nil {
		return nil, err
	}
	if out.RunID == "" {
		return nil, fmt.Errorf("%w: missing run_id", ErrAgentUnavailable)
	}
	return &out, nil
}

func (a *AgentClient) OpenPR(ctx context.Context, agentRunID string) (string, error) {
	var out struct {
		URL string `json:"url"`
	}
	// Opening a PR talks to GitHub; allow more time.
	if err := a.do(ctx, http.MethodPost, "/runs/"+url.PathEscape(agentRunID)+"/pr", nil, &out, 90*time.Second); err != nil {
		return "", err
	}
	return out.URL, nil
}

// EventsURL is the agent SSE endpoint for a run.
func (a *AgentClient) EventsURL(agentRunID string) string {
	return a.BaseURL + "/runs/" + url.PathEscape(agentRunID) + "/events"
}
