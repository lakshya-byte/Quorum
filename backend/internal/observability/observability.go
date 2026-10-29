// Package observability wires JSON logging (log/slog), W3C trace context and
// the New Relic Go agent. Everything is safe to use when New Relic is not
// configured: a nil *newrelic.Application and nil *newrelic.Transaction are
// valid no-op values in the New Relic API.
package observability

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"log/slog"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/newrelic/go-agent/v3/newrelic"
)

type ctxKey int

const (
	traceKey ctxKey = iota
	runIDKey
)

// Trace is the W3C trace context for one inbound request.
type Trace struct {
	TraceID string // 32 hex chars
	SpanID  string // 16 hex chars, the span representing this backend hop
	Flags   string // 2 hex chars
}

// NewLogger returns a JSON slog logger writing to stdout and installs it as
// the default logger.
func NewLogger() *slog.Logger {
	l := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(l)
	return l
}

// NewRelic starts the New Relic agent when a license key is given, otherwise
// returns nil (all New Relic calls are then no-ops).
func NewRelic(appName, licenseKey string) *newrelic.Application {
	if licenseKey == "" {
		slog.Info("new relic disabled: NEW_RELIC_LICENSE_KEY not set")
		return nil
	}
	app, err := newrelic.NewApplication(
		newrelic.ConfigAppName(appName),
		newrelic.ConfigLicense(licenseKey),
		newrelic.ConfigDistributedTracerEnabled(true),
		newrelic.ConfigAppLogForwardingEnabled(true),
	)
	if err != nil {
		slog.Error("new relic init failed, continuing without it", "error", err.Error())
		return nil
	}
	return app
}

func randomHex(n int) string {
	b := make([]byte, n)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

// ParseTraceparent parses a W3C traceparent header ("00-<trace>-<span>-<flags>").
func ParseTraceparent(v string) (Trace, bool) {
	parts := strings.Split(strings.TrimSpace(v), "-")
	if len(parts) != 4 || len(parts[1]) != 32 || len(parts[2]) != 16 || len(parts[3]) != 2 {
		return Trace{}, false
	}
	if _, err := hex.DecodeString(parts[1]); err != nil || parts[1] == strings.Repeat("0", 32) {
		return Trace{}, false
	}
	return Trace{TraceID: parts[1], SpanID: parts[2], Flags: parts[3]}, true
}

// NewTrace continues the incoming trace (if any) with a fresh span id, or
// starts a new trace.
func NewTrace(incoming string) Trace {
	if t, ok := ParseTraceparent(incoming); ok {
		return Trace{TraceID: t.TraceID, SpanID: randomHex(8), Flags: t.Flags}
	}
	return Trace{TraceID: randomHex(16), SpanID: randomHex(8), Flags: "01"}
}

func (t Trace) Traceparent() string {
	return "00-" + t.TraceID + "-" + t.SpanID + "-" + t.Flags
}

func WithTrace(ctx context.Context, t Trace) context.Context {
	return context.WithValue(ctx, traceKey, t)
}

func TraceFrom(ctx context.Context) (Trace, bool) {
	t, ok := ctx.Value(traceKey).(Trace)
	return t, ok
}

func WithRunID(ctx context.Context, runID string) context.Context {
	return context.WithValue(ctx, runIDKey, runID)
}

// TraceID returns the trace id for logs: New Relic's when a transaction is
// active, else the W3C trace context's.
func TraceID(ctx context.Context) string {
	if txn := newrelic.FromContext(ctx); txn != nil {
		if id := txn.GetTraceMetadata().TraceID; id != "" {
			return id
		}
	}
	if t, ok := TraceFrom(ctx); ok {
		return t.TraceID
	}
	return ""
}

// L returns a logger annotated with trace_id and run_id from ctx.
func L(ctx context.Context) *slog.Logger {
	l := slog.Default()
	if id := TraceID(ctx); id != "" {
		l = l.With("trace_id", id)
	}
	if id, ok := ctx.Value(runIDKey).(string); ok && id != "" {
		l = l.With("run_id", id)
	}
	return l
}

// InjectTraceHeaders writes W3C trace headers for an outgoing call to the
// agent. With New Relic active the agent's own distributed-tracing headers
// (traceparent, tracestate, newrelic) are used; otherwise a traceparent that
// continues this request's trace is written.
func InjectTraceHeaders(ctx context.Context, h http.Header) {
	if txn := newrelic.FromContext(ctx); txn != nil {
		txn.InsertDistributedTraceHeaders(h)
		if h.Get("traceparent") != "" {
			return
		}
	}
	if t, ok := TraceFrom(ctx); ok {
		h.Set("traceparent", Trace{TraceID: t.TraceID, SpanID: randomHex(8), Flags: t.Flags}.Traceparent())
	}
}

// RecordEvent records a New Relic custom event (no-op without New Relic) and
// logs it as JSON so it is visible either way.
func RecordEvent(ctx context.Context, app *newrelic.Application, eventType string, attrs map[string]any) {
	app.RecordCustomEvent(eventType, attrs)
	args := make([]any, 0, len(attrs)*2+2)
	args = append(args, "event", eventType)
	for k, v := range attrs {
		args = append(args, k, v)
	}
	L(ctx).Info("custom_event", args...)
}

// Since returns elapsed milliseconds.
func Since(t time.Time) int64 { return time.Since(t).Milliseconds() }
