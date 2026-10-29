package handler

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httputil"
	"net/url"

	"patchloop-backend/internal/observability"

	"github.com/gin-gonic/gin"
)

// SSERelay streams an agent run's events to the client unchanged through
// httputil.ReverseProxy with FlushInterval=-1 (flush after every write, no
// buffering). The upstream request is bound to the client's context, so a
// client disconnect cancels the upstream stream. If the agent goes away
// mid-stream (or never answers) the client receives a clean
// {"type":"error","data":{"stage":"relay",...}} event followed by
// {"type":"end"} instead of a hung or truncated stream.
type SSERelay struct {
	Transport http.RoundTripper
	Secret    string
}

func setSSEHeaders(h http.Header) {
	h.Set("Content-Type", "text/event-stream")
	h.Set("Cache-Control", "no-cache")
	h.Set("Connection", "keep-alive")
	h.Set("X-Accel-Buffering", "no")
	h.Del("Content-Length")
}

func sseEvent(typ string, data any) []byte {
	var b []byte
	if data == nil {
		b, _ = json.Marshal(map[string]any{"type": typ})
	} else {
		b, _ = json.Marshal(map[string]any{"type": typ, "data": data})
	}
	return []byte("data: " + string(b) + "\n\n")
}

func relayErrorEvents(message string) []byte {
	out := sseEvent("error", map[string]any{"stage": "relay", "message": message})
	return append(out, sseEvent("end", nil)...)
}

// Serve proxies GET {target} to the client.
func (r *SSERelay) Serve(c *gin.Context, target string) {
	u, err := url.Parse(target)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "bad agent url"})
		return
	}
	ctx := c.Request.Context()
	log := observability.L(ctx)

	// A client hang-up surfaces as a write error, which ReverseProxy turns
	// into panic(http.ErrAbortHandler); the connection is already gone, so
	// swallow it here instead of letting gin's recovery log a 500.
	defer func() {
		if rec := recover(); rec != nil {
			if rec == http.ErrAbortHandler {
				log.Info("sse client disconnected")
				return
			}
			panic(rec)
		}
	}()

	proxy := &httputil.ReverseProxy{
		Transport:     r.Transport,
		FlushInterval: -1,
		Rewrite: func(pr *httputil.ProxyRequest) {
			out := *u
			pr.Out.URL = &out
			pr.Out.Host = u.Host
			pr.Out.Method = http.MethodGet
			pr.Out.Body = nil
			pr.Out.ContentLength = 0
			// Fresh header set: never forward the user's cookies/tokens.
			h := http.Header{}
			h.Set("Accept", "text/event-stream")
			h.Set("Accept-Encoding", "identity")
			h.Set("X-Agent-Secret", r.Secret)
			if v := pr.In.Header.Get("Last-Event-ID"); v != "" {
				h.Set("Last-Event-ID", v)
			}
			observability.InjectTraceHeaders(pr.In.Context(), h)
			pr.Out.Header = h
		},
		ModifyResponse: func(res *http.Response) error {
			if res.StatusCode != http.StatusOK {
				return fmt.Errorf("agent returned status %d", res.StatusCode)
			}
			setSSEHeaders(res.Header)
			res.Header.Del("Access-Control-Allow-Origin")
			res.Header.Del("Access-Control-Allow-Credentials")
			res.Body = newSSEGuard(res.Request.Context(), res.Body, func(msg string) {
				log.Warn("agent stream ended abnormally", "reason", msg)
			})
			return nil
		},
		ErrorHandler: func(w http.ResponseWriter, req *http.Request, err error) {
			if req.Context().Err() != nil {
				return // client went away
			}
			log.Error("agent stream unavailable", "error", err.Error())
			setSSEHeaders(w.Header())
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write(relayErrorEvents("agent unavailable, please retry"))
			_ = http.NewResponseController(w).Flush()
		},
	}
	proxy.ServeHTTP(c.Writer, c.Request)
}

// sseGuard wraps the upstream body. It watches event types; if the body
// ends (error or EOF) before an "end" event, it appends a relay error event
// and an end event, then reports a clean EOF.
type sseGuard struct {
	ctx      context.Context
	rc       io.ReadCloser
	onAbort  func(string)
	line     []byte
	last2    [2]byte
	sawEnd   bool
	pending  []byte
	finished bool
}

func newSSEGuard(ctx context.Context, rc io.ReadCloser, onAbort func(string)) *sseGuard {
	return &sseGuard{ctx: ctx, rc: rc, onAbort: onAbort}
}

const maxSSELine = 4 << 20

func (g *sseGuard) scan(p []byte) {
	if len(p) >= 2 {
		g.last2 = [2]byte{p[len(p)-2], p[len(p)-1]}
	} else if len(p) == 1 {
		g.last2 = [2]byte{g.last2[1], p[0]}
	}
	for len(p) > 0 {
		i := bytes.IndexByte(p, '\n')
		if i < 0 {
			if len(g.line)+len(p) <= maxSSELine {
				g.line = append(g.line, p...)
			}
			return
		}
		g.line = append(g.line, p[:i]...)
		g.checkLine(bytes.TrimRight(g.line, "\r"))
		g.line = g.line[:0]
		p = p[i+1:]
	}
}

func (g *sseGuard) checkLine(line []byte) {
	data, ok := bytes.CutPrefix(line, []byte("data:"))
	if !ok {
		return
	}
	var ev struct {
		Type string `json:"type"`
	}
	if json.Unmarshal(bytes.TrimSpace(data), &ev) == nil && ev.Type == "end" {
		g.sawEnd = true
	}
}

func (g *sseGuard) Read(p []byte) (int, error) {
	if len(g.pending) > 0 {
		n := copy(p, g.pending)
		g.pending = g.pending[n:]
		return n, nil
	}
	if g.finished {
		return 0, io.EOF
	}
	n, err := g.rc.Read(p)
	if n > 0 {
		g.scan(p[:n])
	}
	if err == nil {
		return n, nil
	}
	g.finished = true
	if g.sawEnd || g.ctx.Err() != nil {
		// Normal end, or the client left (nothing to tell it).
		return n, io.EOF
	}
	reason := "agent stream closed before the run ended"
	if err != io.EOF {
		reason = "agent connection lost: " + err.Error()
	}
	g.onAbort(reason)
	var tail []byte
	if g.last2 != [2]byte{'\n', '\n'} && !(g.last2 == [2]byte{} && n == 0) {
		tail = append(tail, '\n', '\n') // terminate any half-written event
	}
	tail = append(tail, relayErrorEvents(reason)...)
	g.pending = tail
	return n, nil
}

func (g *sseGuard) Close() error { return g.rc.Close() }
