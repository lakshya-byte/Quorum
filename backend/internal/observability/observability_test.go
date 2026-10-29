package observability

import (
	"context"
	"net/http"
	"strings"
	"testing"
)

func TestTraceparentContinuesTrace(t *testing.T) {
	in := "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
	tr := NewTrace(in)
	if tr.TraceID != "0af7651916cd43dd8448eb211c80319c" || tr.SpanID == "b7ad6b7169203331" {
		t.Fatalf("bad continuation: %+v", tr)
	}
	ctx := WithTrace(context.Background(), tr)
	h := http.Header{}
	InjectTraceHeaders(ctx, h)
	out, ok := ParseTraceparent(h.Get("traceparent"))
	if !ok || out.TraceID != tr.TraceID {
		t.Fatalf("injected %q", h.Get("traceparent"))
	}
	if TraceID(ctx) != tr.TraceID {
		t.Fatal("TraceID mismatch")
	}
}

func TestInvalidTraceparentStartsNewTrace(t *testing.T) {
	for _, in := range []string{"", "garbage", "00-" + strings.Repeat("0", 32) + "-b7ad6b7169203331-01"} {
		tr := NewTrace(in)
		if len(tr.TraceID) != 32 || tr.TraceID == strings.Repeat("0", 32) {
			t.Fatalf("%q -> %+v", in, tr)
		}
	}
}
