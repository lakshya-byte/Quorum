package sse

import (
	"io"
	"strings"
	"testing"
)

func collect(t *testing.T, in string) []Event {
	t.Helper()
	r := NewReader(strings.NewReader(in))
	var out []Event
	for {
		ev, err := r.Next()
		if err == io.EOF {
			return out
		}
		if err != nil {
			t.Fatal(err)
		}
		out = append(out, ev)
	}
}

func TestParsesEvents(t *testing.T) {
	in := ": keepalive\n\n" +
		"data: {\"type\": \"round\", \"data\": {\"depth\": 1}}\n\n" +
		"event: ignored\r\ndata: {\"type\":\"node\",\r\ndata: \"data\":{\"id\":3}}\r\n\r\n" +
		"data: {\"type\":\"end\"}\n\n"
	evs := collect(t, in)
	if len(evs) != 3 {
		t.Fatalf("got %d: %+v", len(evs), evs)
	}
	if evs[0].Type != "round" || string(evs[0].Data) != `{"depth": 1}` {
		t.Fatalf("ev0 %+v", evs[0])
	}
	if evs[1].Type != "node" || string(evs[1].Data) != `{"id":3}` {
		t.Fatalf("multi-line data: %+v", evs[1])
	}
	if evs[2].Type != "end" || evs[2].Data != nil {
		t.Fatalf("end: %+v", evs[2])
	}
}

func TestTruncatedAndInvalid(t *testing.T) {
	evs := collect(t, "data: {\"type\":\"node\",\"da\n\ndata: {\"type\":\"error\",\"data\":{\"stage\":\"relay\"}}")
	if len(evs) != 2 || evs[0].Type != "" || evs[0].Raw == "" || evs[1].Type != "error" {
		t.Fatalf("%+v", evs)
	}
}
