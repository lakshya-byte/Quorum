// Package sse parses a text/event-stream body into PatchLoop events.
package sse

import (
	"bufio"
	"encoding/json"
	"io"
	"strings"
)

// Event is one PatchLoop stream message: {"type": T, "data": {...}}.
type Event struct {
	Type string          `json:"type"`
	Data json.RawMessage `json:"data,omitempty"`
	Raw  string          `json:"-"` // the JSON exactly as received
}

// Reader yields events from an SSE stream. Multi-line data fields are
// joined with "\n"; comments and non-data fields are ignored; messages
// whose data is not valid JSON are reported with Type "" and Raw set.
type Reader struct {
	sc *bufio.Scanner
}

func NewReader(r io.Reader) *Reader {
	sc := bufio.NewScanner(r)
	sc.Buffer(make([]byte, 64*1024), 8<<20)
	return &Reader{sc: sc}
}

// Next returns the next event, or io.EOF when the stream ends. A stream
// that stops mid-message (no terminating blank line) still yields what was
// received.
func (r *Reader) Next() (Event, error) {
	var data []string
	have := false
	for r.sc.Scan() {
		line := strings.TrimSuffix(r.sc.Text(), "\r")
		if line == "" {
			if have {
				return decode(strings.Join(data, "\n")), nil
			}
			continue
		}
		if strings.HasPrefix(line, ":") {
			continue
		}
		field, value, _ := strings.Cut(line, ":")
		value = strings.TrimPrefix(value, " ")
		if field == "data" {
			data = append(data, value)
			have = true
		}
	}
	if err := r.sc.Err(); err != nil {
		return Event{}, err
	}
	if have {
		return decode(strings.Join(data, "\n")), nil
	}
	return Event{}, io.EOF
}

func decode(raw string) Event {
	var ev Event
	if err := json.Unmarshal([]byte(raw), &ev); err != nil {
		return Event{Raw: raw}
	}
	ev.Raw = raw
	return ev
}
