package service

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

var (
	ErrSlackBadSignature = errors.New("invalid slack signature")
	ErrSlackStale        = errors.New("stale slack request")
)

// VerifySlackSignature implements https://api.slack.com/authentication/verifying-requests-from-slack :
// v0=HMAC_SHA256(secret, "v0:" + timestamp + ":" + rawBody), compared in
// constant time, and the timestamp must be within 5 minutes of now.
func VerifySlackSignature(secret, timestamp, signature string, body []byte, now time.Time) error {
	if secret == "" {
		return ErrSlackBadSignature
	}
	ts, err := strconv.ParseInt(timestamp, 10, 64)
	if err != nil {
		return ErrSlackBadSignature
	}
	if d := now.Unix() - ts; d > 300 || d < -300 {
		return ErrSlackStale
	}
	m := hmac.New(sha256.New, []byte(secret))
	m.Write([]byte("v0:" + timestamp + ":"))
	m.Write(body)
	want := "v0=" + hex.EncodeToString(m.Sum(nil))
	if !hmac.Equal([]byte(want), []byte(signature)) {
		return ErrSlackBadSignature
	}
	return nil
}

// SignSlackRequest computes the headers a genuine Slack request would carry
// (used by tests and the dev helper that simulates slash commands).
func SignSlackRequest(secret string, body []byte, now time.Time) (timestamp, signature string) {
	timestamp = strconv.FormatInt(now.Unix(), 10)
	m := hmac.New(sha256.New, []byte(secret))
	m.Write([]byte("v0:" + timestamp + ":"))
	m.Write(body)
	return timestamp, "v0=" + hex.EncodeToString(m.Sum(nil))
}

// SlackAPI is a minimal Web API client (chat.postMessage, chat.update,
// chat.postEphemeral). Base is overridable (SLACK_API_BASE) so a stub can
// stand in for slack.com.
type SlackAPI struct {
	BotToken string
	Base     string
	client   *http.Client
}

func NewSlackAPI(botToken, base string) *SlackAPI {
	if base == "" {
		base = "https://slack.com/api"
	}
	return &SlackAPI{BotToken: botToken, Base: strings.TrimRight(base, "/"), client: &http.Client{Timeout: 10 * time.Second}}
}

func (a *SlackAPI) Enabled() bool { return a != nil && a.BotToken != "" }

type slackResp struct {
	OK    bool   `json:"ok"`
	Error string `json:"error"`
	TS    string `json:"ts"`
}

func (a *SlackAPI) call(ctx context.Context, method string, body map[string]any) (string, error) {
	if !a.Enabled() {
		return "", errors.New("slack bot token not configured")
	}
	b, _ := json.Marshal(body)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, a.Base+"/"+method, bytes.NewReader(b))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/json; charset=utf-8")
	req.Header.Set("Authorization", "Bearer "+a.BotToken)
	resp, err := a.client.Do(req)
	if err != nil {
		var uerr *url.Error
		if errors.As(err, &uerr) {
			err = uerr.Err
		}
		return "", fmt.Errorf("slack %s failed: %v", method, err)
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	var out slackResp
	if err := json.Unmarshal(raw, &out); err != nil {
		return "", fmt.Errorf("slack %s: unreadable response (status %d)", method, resp.StatusCode)
	}
	if !out.OK {
		return "", fmt.Errorf("slack %s: %s", method, out.Error)
	}
	return out.TS, nil
}

// PostMessage posts text (and optional blocks) and returns the message ts.
// threadTS may be empty for a top-level message.
func (a *SlackAPI) PostMessage(ctx context.Context, channel, threadTS, text string, blocks any) (string, error) {
	body := map[string]any{"channel": channel, "text": text}
	if threadTS != "" {
		body["thread_ts"] = threadTS
	}
	if blocks != nil {
		body["blocks"] = blocks
	}
	return a.call(ctx, "chat.postMessage", body)
}

func (a *SlackAPI) UpdateMessage(ctx context.Context, channel, ts, text string, blocks any) error {
	body := map[string]any{"channel": channel, "ts": ts, "text": text}
	if blocks != nil {
		body["blocks"] = blocks
	}
	_, err := a.call(ctx, "chat.update", body)
	return err
}

func (a *SlackAPI) PostEphemeral(ctx context.Context, channel, user, threadTS, text string) error {
	body := map[string]any{"channel": channel, "user": user, "text": text}
	if threadTS != "" {
		body["thread_ts"] = threadTS
	}
	_, err := a.call(ctx, "chat.postEphemeral", body)
	return err
}
