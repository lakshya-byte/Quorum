package middleware

import (
	"time"

	"patchloop-backend/internal/observability"

	"github.com/gin-gonic/gin"
	"github.com/newrelic/go-agent/v3/integrations/nrgin"
	"github.com/newrelic/go-agent/v3/newrelic"
)

const ContextRunIDKey = "runID"

// Observability must run after nrgin.Middleware. It puts the New Relic
// transaction and a W3C trace context on the request context (so services
// can log trace_id and propagate traceparent to the agent) and writes one
// JSON access-log line per request.
func Observability() gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		ctx := c.Request.Context()
		if txn := nrgin.Transaction(c); txn != nil {
			// nrgin already accepted inbound distributed-trace headers.
			ctx = newrelic.NewContext(ctx, txn)
		}
		ctx = observability.WithTrace(ctx, observability.NewTrace(c.GetHeader("traceparent")))
		c.Request = c.Request.WithContext(ctx)

		c.Next()

		logCtx := c.Request.Context()
		if runID := c.GetString(ContextRunIDKey); runID != "" {
			logCtx = observability.WithRunID(logCtx, runID)
		}
		observability.L(logCtx).Info("http_request",
			"method", c.Request.Method,
			"route", c.FullPath(),
			"status", c.Writer.Status(),
			"latency_ms", observability.Since(start),
		)
	}
}
