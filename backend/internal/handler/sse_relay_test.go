package handler

import (
	"context"
	"errors"
	"io"
	"strings"
	"testing"
)

type chunkReader struct {
	chunks []string
	err    error
}

func (c *chunkReader) Read(p []byte) (int, error) {
	if len(c.chunks) == 0 {
		return 0, c.err
	}
	n := copy(p, c.chunks[0])
	c.chunks[0] = c.chunks[0][n:]
	if c.chunks[0] == "" {
		c.chunks = c.chunks[1:]
	}
	return n, nil
}
func (c *chunkReader) Close() error { return nil }

func readAll(t *testing.T, ctx context.Context, rc io.ReadCloser) (string, bool) {
	t.Helper()
	aborted := false
	g := newSSEGuard(ctx, rc, func(string) { aborted = true })
	b, err := io.ReadAll(g)
	if err != nil {
		t.Fatalf("guard returned error: %v", err)
	}
	return string(b), aborted
}

func TestGuardPassesCompleteStreamUnchanged(t *testing.T) {
	in := "data: {\"type\": \"round\", \"data\": {\"depth\": 0}}\n\ndata: {\"type\": \"end\"}\n\n"
	out, aborted := readAll(t, context.Background(), &chunkReader{chunks: []string{in[:10], in[10:]}, err: io.EOF})
	if out != in || aborted {
		t.Fatalf("out=%q aborted=%v", out, aborted)
	}
}

func TestGuardAppendsErrorWhenUpstreamDies(t *testing.T) {
	in := "data: {\"type\": \"round\", \"data\": {\"depth\": 0}}\n\ndata: {\"type\": \"no"
	out, aborted := readAll(t, context.Background(), &chunkReader{chunks: []string{in}, err: errors.New("connection reset")})
	if !aborted {
		t.Fatal("abort not reported")
	}
	if !strings.HasPrefix(out, in+"\n\n") {
		t.Fatalf("partial event not terminated: %q", out)
	}
	if !strings.HasSuffix(out, "data: {\"type\":\"end\"}\n\n") || !strings.Contains(out, `"stage":"relay"`) {
		t.Fatalf("missing error/end: %q", out)
	}
}

func TestGuardAppendsErrorOnEOFWithoutEnd(t *testing.T) {
	in := "data: {\"type\":\"node\",\"data\":{}}\n\n"
	out, aborted := readAll(t, context.Background(), &chunkReader{chunks: []string{in}, err: io.EOF})
	if !aborted || !strings.Contains(out, `"type":"error"`) || strings.Contains(out, in+"\n\n") {
		t.Fatalf("out=%q", out)
	}
}

func TestGuardSilentWhenClientGone(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	out, aborted := readAll(t, ctx, &chunkReader{chunks: []string{"data: {}\n\n"}, err: context.Canceled})
	if aborted || strings.Contains(out, "error") {
		t.Fatalf("out=%q aborted=%v", out, aborted)
	}
}
