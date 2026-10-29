// Package api is a small client for the PatchLoop backend public API.
package api

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

type Client struct {
	Base  string
	Token string
	http  *http.Client // for JSON calls
	sse   *http.Client // no overall timeout, for streams
}

func New(base, token string) *Client {
	return &Client{
		Base:  strings.TrimRight(base, "/"),
		Token: token,
		http:  &http.Client{Timeout: 120 * time.Second},
		sse:   &http.Client{},
	}
}

// Error is a non-2xx API answer ({"error": "..."}).
type Error struct {
	Status  int
	Code    string // stable machine-readable code from {"error","code"}
	Message string
	Extra   map[string]any
}

func (e *Error) Error() string { return fmt.Sprintf("%s (HTTP %d)", e.Message, e.Status) }

func (c *Client) newRequest(ctx context.Context, method, path string, body any) (*http.Request, error) {
	var rdr io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return nil, err
		}
		rdr = bytes.NewReader(b)
	}
	req, err := http.NewRequestWithContext(ctx, method, c.Base+path, rdr)
	if err != nil {
		return nil, err
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if c.Token != "" {
		req.Header.Set("Authorization", "Bearer "+c.Token)
	}
	req.Header.Set("User-Agent", "patchloop-cli")
	return req, nil
}

func apiError(resp *http.Response) error {
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 64<<10))
	var m map[string]any
	msg := strings.TrimSpace(string(raw))
	code := ""
	if json.Unmarshal(raw, &m) == nil {
		if e, ok := m["error"].(string); ok && e != "" {
			msg = e
		}
		code, _ = m["code"].(string)
	}
	if msg == "" {
		msg = http.StatusText(resp.StatusCode)
	}
	return &Error{Status: resp.StatusCode, Code: code, Message: msg, Extra: m}
}

// Do sends a JSON request and decodes a JSON response into out.
func (c *Client) Do(ctx context.Context, method, path string, body, out any) error {
	req, err := c.newRequest(ctx, method, path, body)
	if err != nil {
		return err
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		return apiError(resp)
	}
	if out == nil {
		return nil
	}
	return json.NewDecoder(resp.Body).Decode(out)
}

// Stream opens an SSE endpoint; the caller closes the body. Cancelling ctx
// closes the stream.
func (c *Client) Stream(ctx context.Context, path string) (io.ReadCloser, error) {
	req, err := c.newRequest(ctx, http.MethodGet, path, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Accept", "text/event-stream")
	resp, err := c.sse.Do(req)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode != http.StatusOK {
		defer resp.Body.Close()
		return nil, apiError(resp)
	}
	return resp.Body, nil
}

type User struct {
	ID          string `json:"id"`
	Email       string `json:"email"`
	CompanyName string `json:"companyName"`
}

func (c *Client) Me(ctx context.Context) (*User, error) {
	var out struct {
		User User `json:"user"`
	}
	if err := c.Do(ctx, http.MethodGet, "/api/auth/me", nil, &out); err != nil {
		return nil, err
	}
	return &out.User, nil
}

type Bug struct {
	ID    string `json:"id"`
	Title string `json:"title"`
	Issue string `json:"issue"`
	Tier  any    `json:"tier"`
}

func (c *Client) Bugs(ctx context.Context) ([]Bug, error) {
	var out []Bug
	return out, c.Do(ctx, http.MethodGet, "/api/bugs", nil, &out)
}

type CreateRunResponse struct {
	RunID  string `json:"runId"`
	Mode   string `json:"mode"`
	Engine string `json:"engine"`
	Notice string `json:"notice"`
}

func (c *Client) CreateRun(ctx context.Context, bugID, engine string, replay bool) (*CreateRunResponse, error) {
	body := map[string]any{"bugId": bugID, "replay": replay}
	if engine != "" {
		body["engine"] = engine
	}
	var out CreateRunResponse
	return &out, c.Do(ctx, http.MethodPost, "/api/runs", body, &out)
}

type Run struct {
	ID          string         `json:"id"`
	BugID       string         `json:"bugId"`
	Mode        string         `json:"mode"`
	Engine      string         `json:"engine"`
	Status      string         `json:"status"`
	Solved      bool           `json:"solved"`
	LatencyMs   int64          `json:"latencyMs"`
	PRURL       string         `json:"prUrl"`
	Usage       map[string]any `json:"usage"`
	CreatedAt   time.Time      `json:"createdAt"`
	CompletedAt *time.Time     `json:"completedAt"`

	Kind     string `json:"kind"`
	Source   string `json:"source"`
	Repo     string `json:"repo"`
	Branch   string `json:"branch"`
	Task     string `json:"task"`
	PRNumber int    `json:"prNumber"`
	PRBranch string `json:"prBranch"`
	TraceID  string `json:"traceId"`
	Merged   *struct {
		By string    `json:"by"`
		At time.Time `json:"at"`
	} `json:"merged"`
	Cost *struct {
		Tokens int64   `json:"tokens"`
		USD    float64 `json:"usd"`
	} `json:"cost"`
}

func (c *Client) Runs(ctx context.Context) ([]Run, error) {
	var out []Run
	return out, c.Do(ctx, http.MethodGet, "/api/runs", nil, &out)
}

func (c *Client) OpenPR(ctx context.Context, runID string) (string, error) {
	var out struct {
		URL string `json:"url"`
	}
	err := c.Do(ctx, http.MethodPost, "/api/runs/"+url.PathEscape(runID)+"/pr", nil, &out)
	return out.URL, err
}

func EventsPath(runID string) string { return "/api/runs/" + url.PathEscape(runID) + "/events" }
