package service

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
)

// StreamEvents reads the agent's SSE stream for a run and calls fn for each
// event until the stream ends, fn returns false or ctx is cancelled. Used by
// server-side watchers (Slack threads); browsers use the relay instead.
func (a *AgentClient) StreamEvents(ctx context.Context, agentRunID string, fn func(typ string, data map[string]any) bool) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, a.EventsURL(agentRunID), nil)
	if err != nil {
		return err
	}
	req.Header.Set("X-Agent-Secret", a.Secret)
	req.Header.Set("Accept", "text/event-stream")
	resp, err := (&http.Client{Transport: a.Transport}).Do(req)
	if err != nil {
		return fmt.Errorf("%w: %v", ErrAgentUnavailable, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("%w: events status %d", ErrAgentUnavailable, resp.StatusCode)
	}
	sc := bufio.NewScanner(resp.Body)
	sc.Buffer(make([]byte, 1<<20), 8<<20)
	for sc.Scan() {
		line := sc.Text()
		if !strings.HasPrefix(line, "data:") {
			continue
		}
		var ev struct {
			Type string         `json:"type"`
			Data map[string]any `json:"data"`
		}
		if json.Unmarshal([]byte(strings.TrimSpace(strings.TrimPrefix(line, "data:"))), &ev) != nil {
			continue
		}
		if ev.Type == "end" || !fn(ev.Type, ev.Data) {
			return nil
		}
	}
	return sc.Err()
}
