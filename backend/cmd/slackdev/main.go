// Command slackdev supports offline Slack demos and e2e scripts.
//
//	slackdev serve -addr :19090 -token xoxb-dev      # fake slack.com/api (set SLACK_API_BASE=http://localhost:19090)
//	slackdev command -url http://localhost:8080 -secret $SLACK_SIGNING_SECRET -user U1 -channel C1 "fix the bug repo:demo/text-tools"
//
// "serve" prints every message the backend posts; "command" sends a correctly
// signed slash command exactly as Slack would.
package main

import (
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"

	"patchloop-backend/internal/service"
	"patchloop-backend/internal/slackstub"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: slackdev serve|command [flags]")
		os.Exit(2)
	}
	switch os.Args[1] {
	case "serve":
		fs := flag.NewFlagSet("serve", flag.ExitOnError)
		addr := fs.String("addr", ":19090", "listen address")
		token := fs.String("token", "", "expected bot token (empty accepts any)")
		_ = fs.Parse(os.Args[2:])
		stub := slackstub.New(*token)
		log.Printf("fake slack API on %s", *addr)
		log.Fatal(http.ListenAndServe(*addr, logging(stub)))
	case "command":
		fs := flag.NewFlagSet("command", flag.ExitOnError)
		base := fs.String("url", "http://localhost:8080", "backend base URL")
		secret := fs.String("secret", os.Getenv("SLACK_SIGNING_SECRET"), "Slack signing secret")
		user := fs.String("user", "U1", "slack user id")
		channel := fs.String("channel", "C1", "channel id")
		_ = fs.Parse(os.Args[2:])
		form := url.Values{"command": {"/patchloop"}, "text": {strings.Join(fs.Args(), " ")}, "user_id": {*user}, "channel_id": {*channel}}
		body := []byte(form.Encode())
		ts, sig := service.SignSlackRequest(*secret, body, time.Now())
		req, _ := http.NewRequest("POST", strings.TrimRight(*base, "/")+"/slack/commands", strings.NewReader(string(body)))
		req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
		req.Header.Set("X-Slack-Request-Timestamp", ts)
		req.Header.Set("X-Slack-Signature", sig)
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			log.Fatal(err)
		}
		defer resp.Body.Close()
		raw, _ := io.ReadAll(resp.Body)
		fmt.Printf("%d %s\n", resp.StatusCode, raw)
	default:
		fmt.Fprintln(os.Stderr, "usage: slackdev serve|command [flags]")
		os.Exit(2)
	}
}

func logging(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		next.ServeHTTP(w, r)
		log.Printf("%s %s", r.Method, r.URL.Path)
	})
}
