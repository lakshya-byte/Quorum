package service

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"time"

	"patchloop-backend/internal/models"
)

// SlackNotifier posts Block Kit messages to an incoming webhook. A zero
// WebhookURL disables it.
type SlackNotifier struct {
	WebhookURL   string
	PublicAppURL string
	client       *http.Client
}

func NewSlackNotifier(webhookURL, publicAppURL string) *SlackNotifier {
	return &SlackNotifier{
		WebhookURL:   webhookURL,
		PublicAppURL: publicAppURL,
		client:       &http.Client{Timeout: 5 * time.Second},
	}
}

func (s *SlackNotifier) Enabled() bool { return s != nil && s.WebhookURL != "" }

// RunURL is the public page for a run.
func (s *SlackNotifier) RunURL(run *models.Run) string {
	return fmt.Sprintf("%s/runs/%s", s.PublicAppURL, run.ID.Hex())
}

// TestsPassed returns passed/total for the run's best node.
func TestsPassed(run *models.Run) (passed, total int, ok bool) {
	best := fmt.Sprint(run.BestNodeID)
	for _, n := range run.Nodes {
		m, isMap := n.(map[string]any)
		if !isMap {
			continue
		}
		if fmt.Sprint(m["id"]) != best {
			continue
		}
		p, ok1 := toInt(m["passed"])
		t, ok2 := toInt(m["total"])
		return p, t, ok1 && ok2
	}
	return 0, 0, false
}

func toInt(v any) (int, bool) {
	switch x := v.(type) {
	case float64:
		return int(x), true
	case int:
		return x, true
	case int32:
		return int(x), true
	case int64:
		return int(x), true
	}
	return 0, false
}

// BuildRunMessage builds the Block Kit payload for a solved run (and, when
// prURL is set, a "Review PR" button).
func (s *SlackNotifier) BuildRunMessage(run *models.Run) map[string]any {
	tests := "n/a"
	if p, t, ok := TestsPassed(run); ok {
		tests = fmt.Sprintf("%d/%d passed", p, t)
	}
	tokens := "n/a"
	if run.Usage != nil {
		pt, _ := toInt(run.Usage["prompt_tokens"])
		ct, _ := toInt(run.Usage["completion_tokens"])
		tokens = fmt.Sprintf("%d", pt+ct)
	}
	title := fmt.Sprintf("PatchLoop fixed `%s`: tests pass, ready for review", run.BugID)
	if run.PRURL != "" {
		title = fmt.Sprintf("PatchLoop opened a PR for `%s`: please review and merge", run.BugID)
	}
	buttons := []map[string]any{}
	if run.PRURL != "" {
		buttons = append(buttons, map[string]any{
			"type": "button", "style": "primary", "action_id": "open_pr",
			"text": map[string]any{"type": "plain_text", "text": "Review PR"},
			"url":  run.PRURL,
		})
	}
	buttons = append(buttons, map[string]any{
		"type": "button", "action_id": "open_run",
		"text": map[string]any{"type": "plain_text", "text": "Open run"},
		"url":  s.RunURL(run),
	})
	return map[string]any{
		"text": fmt.Sprintf("PatchLoop: %s solved (%s)", run.BugID, tests),
		"blocks": []map[string]any{
			{"type": "header", "text": map[string]any{"type": "plain_text", "text": "PatchLoop fix ready"}},
			{"type": "section", "text": map[string]any{"type": "mrkdwn", "text": title}},
			{"type": "section", "fields": []map[string]any{
				{"type": "mrkdwn", "text": "*Bug*\n" + run.BugID},
				{"type": "mrkdwn", "text": "*Tests*\n" + tests},
				{"type": "mrkdwn", "text": "*Engine / mode*\n" + run.Engine + " / " + run.Mode},
				{"type": "mrkdwn", "text": fmt.Sprintf("*Tokens / latency*\n%s / %d ms", tokens, run.LatencyMs)},
			}},
			{"type": "context", "elements": []map[string]any{
				{"type": "mrkdwn", "text": "Agents cannot merge. A human must review and merge this fix."},
			}},
			{"type": "actions", "elements": buttons},
		},
	}
}

// Post sends a payload; returns the HTTP status (0 on transport error).
func (s *SlackNotifier) Post(ctx context.Context, payload map[string]any) (int, error) {
	b, err := json.Marshal(payload)
	if err != nil {
		return 0, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, s.WebhookURL, bytes.NewReader(b))
	if err != nil {
		return 0, errors.New("invalid SLACK_WEBHOOK_URL")
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := s.client.Do(req)
	if err != nil {
		// *url.Error embeds the webhook URL, which is a secret: drop it.
		var uerr *url.Error
		if errors.As(err, &uerr) {
			err = uerr.Err
		}
		return 0, fmt.Errorf("slack request failed: %v", err)
	}
	resp.Body.Close()
	if resp.StatusCode >= 300 {
		return resp.StatusCode, fmt.Errorf("slack returned %d", resp.StatusCode)
	}
	return resp.StatusCode, nil
}
