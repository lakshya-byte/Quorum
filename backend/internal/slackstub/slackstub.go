// Package slackstub is an in-process stand-in for slack.com/api used in fake
// mode and tests (point SLACK_API_BASE at it). It records every message so a
// test or demo can assert what a Slack channel would have shown.
package slackstub

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"sync"
)

// Message is one recorded Web API call.
type Message struct {
	Method    string // chat.postMessage | chat.update | chat.postEphemeral
	Channel   string
	ThreadTS  string
	TS        string
	User      string
	Text      string
	Blocks    []any
	AuthToken string
}

// Stub implements the three chat.* methods PatchLoop uses.
type Stub struct {
	Token string // expected bot token; empty accepts any

	mu   sync.Mutex
	seq  int
	msgs []Message
}

func New(token string) *Stub { return &Stub{Token: token} }

func (s *Stub) reply(w http.ResponseWriter, v map[string]any) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(v)
}

func (s *Stub) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	method := strings.TrimPrefix(r.URL.Path, "/")
	auth := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
	if s.Token != "" && auth != s.Token {
		s.reply(w, map[string]any{"ok": false, "error": "invalid_auth"})
		return
	}
	var body struct {
		Channel  string `json:"channel"`
		ThreadTS string `json:"thread_ts"`
		TS       string `json:"ts"`
		User     string `json:"user"`
		Text     string `json:"text"`
		Blocks   []any  `json:"blocks"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		s.reply(w, map[string]any{"ok": false, "error": "invalid_json"})
		return
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	switch method {
	case "chat.postMessage", "chat.postEphemeral":
		s.seq++
		ts := fmt.Sprintf("1700000000.%06d", s.seq)
		s.msgs = append(s.msgs, Message{Method: method, Channel: body.Channel, ThreadTS: body.ThreadTS, TS: ts, User: body.User,
			Text: body.Text, Blocks: body.Blocks, AuthToken: auth})
		s.reply(w, map[string]any{"ok": true, "ts": ts, "channel": body.Channel})
	case "chat.update":
		for i := range s.msgs {
			if s.msgs[i].TS == body.TS && s.msgs[i].Channel == body.Channel {
				s.msgs[i].Text, s.msgs[i].Blocks = body.Text, body.Blocks
				s.reply(w, map[string]any{"ok": true, "ts": body.TS, "channel": body.Channel})
				return
			}
		}
		s.reply(w, map[string]any{"ok": false, "error": "message_not_found"})
	default:
		s.reply(w, map[string]any{"ok": false, "error": "unknown_method"})
	}
}

// Messages returns a snapshot of everything recorded so far (updates are
// applied in place, like Slack's own view of the thread).
func (s *Stub) Messages() []Message {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]Message(nil), s.msgs...)
}

// Find returns messages whose text contains substr.
func (s *Stub) Find(substr string) []Message {
	var out []Message
	for _, m := range s.Messages() {
		if strings.Contains(m.Text, substr) {
			out = append(out, m)
		}
	}
	return out
}
