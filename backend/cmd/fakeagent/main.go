// Command fakeagent runs a contract-compatible fake of the Python agent for
// local demos and integration checks (no LLM, no sandboxes).
//
//	AGENT_SHARED_SECRET=... BACKEND_CALLBACK_URL=http://localhost:18080 \
//	  go run ./cmd/fakeagent -addr :18001 -delay 150ms
package main

import (
	"flag"
	"log"
	"net/http"
	"os"

	"patchloop-backend/internal/fakeagent"
)

func main() {
	addr := flag.String("addr", ":18001", "listen address")
	delay := flag.Duration("delay", 0, "delay between events (default 100ms)")
	flag.Parse()

	secret := os.Getenv("AGENT_SHARED_SECRET")
	if secret == "" {
		log.Fatal("AGENT_SHARED_SECRET is required")
	}
	a := fakeagent.New(fakeagent.Options{
		Secret:      secret,
		CallbackURL: os.Getenv("BACKEND_CALLBACK_URL"),
		Delay:       *delay,
	})
	log.Printf("fake agent listening on %s", *addr)
	log.Fatal(http.ListenAndServe(*addr, a))
}
