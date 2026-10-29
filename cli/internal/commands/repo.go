package commands

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/signal"
	"regexp"
	"runtime"
	"strings"
	"syscall"
	"text/tabwriter"
	"time"

	"patchloop-cli/internal/api"
	"patchloop-cli/internal/config"
	"patchloop-cli/internal/render"
	"patchloop-cli/internal/sse"

	"github.com/spf13/cobra"
)

// Overridable in tests.
var (
	openURL     = openBrowser
	pollEvery   = 2 * time.Second
	pollTimeout = 5 * time.Minute
)

var repoPattern = regexp.MustCompile(`^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`)

func openBrowser(url string) error {
	var name string
	var args []string
	switch runtime.GOOS {
	case "darwin":
		name, args = "open", []string{url}
	case "windows":
		name, args = "rundll32", []string{"url.dll,FileProtocolHandler", url}
	default:
		name, args = "xdg-open", []string{url}
	}
	return exec.Command(name, args...).Start()
}

// hintFor turns an API error into a next step for the user.
func hintFor(err error) string {
	var ae *api.Error
	if !errors.As(err, &ae) {
		return ""
	}
	switch ae.Code {
	case "unauthorized":
		return "Your token is missing or revoked. Run: patchloop login --token plk_..."
	case "github_not_connected":
		return "Run: patchloop connect github   (or: patchloop connect github --demo for offline demo repos)"
	case "github_reauth":
		return "Run: patchloop connect github   to re-authorise your GitHub account"
	case "github_rejected":
		return "Reinstall the PatchLoop GitHub App on your account, then retry"
	case "repo_not_granted":
		return "Grant the repo to the PatchLoop GitHub App on GitHub (Settings > Applications), then retry. List granted repos: patchloop repos"
	case "rate_limited":
		if s, ok := ae.Extra["retryAfterSec"].(float64); ok {
			return fmt.Sprintf("Try again in about %d minutes", int(s/60)+1)
		}
		return "Slow down and try again later"
	case "not_configured":
		return "This feature is not configured on the server (see docs/SETUP.md)"
	case "agent_unavailable", "upstream_error":
		return "The server could not reach the agent or GitHub; retry in a minute"
	}
	if ae.Status == 401 {
		return "Run: patchloop login --token plk_..."
	}
	return ""
}

// fail prints a friendly error plus hint and returns exit code 2.
func fail(cmd *cobra.Command, err error) error {
	fmt.Fprintln(cmd.ErrOrStderr(), "error:", err)
	if h := hintFor(err); h != "" {
		fmt.Fprintln(cmd.ErrOrStderr(), "hint:", h)
	}
	return &ExitError{Code: 2}
}

func printJSON(cmd *cobra.Command, v any) error {
	enc := json.NewEncoder(cmd.OutOrStdout())
	enc.SetIndent("", "  ")
	return enc.Encode(v)
}

func repoCommands() []*cobra.Command {
	return []*cobra.Command{connectCmd(), reposCmd(), mergeCmd(), changesCmd(), slackCmd(), statusCmd(), doctorCmd()}
}

// ---- connect --------------------------------------------------------------

func connectCmd() *cobra.Command {
	var demo, noOpen bool
	c := &cobra.Command{
		Use:   "connect github",
		Short: "Install the PatchLoop GitHub App (or use the offline demo account)",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			if args[0] != "github" {
				return errors.New(`only "github" can be connected: patchloop connect github`)
			}
			cl, err := client()
			if err != nil {
				return err
			}
			ctx := cmd.Context()
			if demo {
				if err := cl.GitHubDemo(ctx); err != nil {
					return fail(cmd, err)
				}
				fmt.Fprintln(cmd.OutOrStdout(), "Connected the demo account (offline demo repos: demo/inventory-api, demo/billing-utils, demo/text-tools).")
				return nil
			}
			if st, err := cl.GitHubStatus(ctx); err == nil && st.Connected && st.Mode == "app" {
				fmt.Fprintf(cmd.OutOrStdout(), "Already connected as %s (%d repos). Manage repos on GitHub: Settings > Applications.\n", st.Login, st.RepoCount)
				return nil
			}
			u, err := cl.GitHubConnectURL(ctx)
			if err != nil {
				return fail(cmd, err)
			}
			out := cmd.OutOrStdout()
			fmt.Fprintln(out, "Install the PatchLoop GitHub App and choose which repositories it may access:")
			fmt.Fprintln(out, "  "+u)
			if !noOpen {
				if err := openURL(u); err != nil {
					fmt.Fprintln(cmd.ErrOrStderr(), "(could not open a browser; open the URL above yourself)")
				}
			}
			sp := render.NewSpinner(cmd.ErrOrStderr(), useColor(cmd.ErrOrStderr()))
			sp.Start("waiting for the install to finish (Ctrl-C to stop)")
			defer sp.Stop()
			ictx, stop := signal.NotifyContext(ctx, os.Interrupt, syscall.SIGTERM)
			defer stop()
			deadline := time.Now().Add(pollTimeout)
			for time.Now().Before(deadline) {
				select {
				case <-ictx.Done():
					sp.Stop()
					return &ExitError{Code: 130}
				case <-time.After(pollEvery):
				}
				st, err := cl.GitHubStatus(ictx)
				if err == nil && st.Connected {
					sp.Stop()
					fmt.Fprintf(out, "Connected as %s: %d repositories granted.\n", st.Login, st.RepoCount)
					fmt.Fprintln(out, `Next: patchloop repos   then   patchloop fix --repo owner/name "describe the bug"`)
					return nil
				}
			}
			sp.Stop()
			return fail(cmd, errors.New("timed out waiting for the GitHub install; run the command again"))
		},
	}
	c.Flags().BoolVar(&demo, "demo", false, "connect the offline demo account instead")
	c.Flags().BoolVar(&noOpen, "no-open", false, "print the URL without opening a browser")
	return c
}

// ---- repos ----------------------------------------------------------------

func reposCmd() *cobra.Command {
	var q string
	var jsonOut bool
	c := &cobra.Command{
		Use:   "repos",
		Short: "List repositories PatchLoop can work on",
		RunE: func(cmd *cobra.Command, args []string) error {
			cl, err := client()
			if err != nil {
				return err
			}
			repos, err := cl.Repos(cmd.Context(), q)
			if err != nil {
				return fail(cmd, err)
			}
			if jsonOut {
				return printJSON(cmd, repos)
			}
			if len(repos) == 0 {
				fmt.Fprintln(cmd.OutOrStdout(), "No repositories. Grant some to the GitHub App, or run: patchloop connect github --demo")
				return nil
			}
			tw := tabwriter.NewWriter(cmd.OutOrStdout(), 0, 4, 2, ' ', 0)
			fmt.Fprintln(tw, "REPO\tBRANCH\tLANG\tVISIBILITY\tDESCRIPTION")
			for _, r := range repos {
				vis := "public"
				if r.Private {
					vis = "private"
				}
				fmt.Fprintf(tw, "%s\t%s\t%s\t%s\t%s\n", r.FullName, r.DefaultBranch, r.Language, vis, r.Description)
			}
			return tw.Flush()
		},
	}
	c.Flags().StringVar(&q, "q", "", "filter by name or description")
	c.Flags().BoolVar(&jsonOut, "json", false, "print JSON")
	return c
}

// ---- fix on a repo ----------------------------------------------------------

// repoFix creates a task and streams it. Exit codes: 0 solved, 1 unsolved, 2 error.
func repoFix(cmd *cobra.Command, cl *api.Client, repo, branch, task string, autoPR, jsonOut bool) error {
	if !repoPattern.MatchString(repo) {
		return fail(cmd, errors.New(`--repo must look like owner/name`))
	}
	t, err := cl.CreateTask(cmd.Context(), repo, branch, task, autoPR)
	if err != nil {
		return fail(cmd, err)
	}
	if !jsonOut {
		fmt.Fprintf(cmd.ErrOrStderr(), "run %s started on %s@%s (%s)\n", t.RunID, t.Repo, t.Branch, t.Mode)
	}
	return watchRepoRun(cmd, cl, t.RunID, jsonOut)
}

// watchRepoRun streams a repo run, prints the summary and maps the outcome to an exit code.
func watchRepoRun(cmd *cobra.Command, cl *api.Client, runID string, jsonOut bool) error {
	ctx, stop := signal.NotifyContext(cmd.Context(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	out := cmd.OutOrStdout()
	body, err := cl.Stream(ctx, api.EventsPath(runID))
	if err != nil {
		return fail(cmd, err)
	}
	defer body.Close()

	r := render.New(out, useColor(out))
	track := render.New(io.Discard, false)
	sp := render.NewSpinner(cmd.ErrOrStderr(), !jsonOut && useColor(cmd.ErrOrStderr()))
	sp.Start("agents are working")
	defer sp.Stop()
	rd := sse.NewReader(body)
	for {
		ev, err := rd.Next()
		if err != nil {
			sp.Stop()
			if ctx.Err() != nil {
				fmt.Fprintf(cmd.ErrOrStderr(), "\nstream closed; the run continues on the server. Resume with: patchloop watch %s\n", runID)
				return &ExitError{Code: 130}
			}
			if err != io.EOF {
				fmt.Fprintln(cmd.ErrOrStderr(), "stream error:", err)
			}
			break
		}
		sp.Pause()
		if jsonOut {
			if ev.Raw != "" {
				fmt.Fprintln(out, ev.Raw)
			}
			track.Event(ev)
			r.Done, r.Solved, r.PRURL = track.Done, track.Solved, track.PRURL
			r.Errors = track.Errors
		} else {
			r.Event(ev)
		}
		sp.Resume()
		switch ev.Type {
		case "round":
			sp.SetMessage("candidates are being tested")
		case "done":
			sp.SetMessage("opening the pull request")
		}
		if ev.Type == "end" {
			break
		}
	}
	sp.Stop()

	if !jsonOut {
		summarize(cmd, cl, runID, r)
	}
	switch {
	case r.Solved:
		return nil
	case r.Done:
		return &ExitError{Code: 1}
	default:
		if !jsonOut && len(r.Errors) == 0 {
			fmt.Fprintln(cmd.ErrOrStderr(), "error: the stream ended before the run finished")
		}
		return &ExitError{Code: 2}
	}
}

func summarize(cmd *cobra.Command, cl *api.Client, runID string, r *render.Renderer) {
	ctx, cancel := context.WithTimeout(cmd.Context(), 15*time.Second)
	defer cancel()
	errw := cmd.ErrOrStderr()
	fmt.Fprintf(errw, "run id: %s\n", runID)
	run, err := cl.GetRun(ctx, runID)
	prURL := r.PRURL
	if err == nil {
		if run.PRURL != "" {
			prURL = run.PRURL
		}
		if run.Cost != nil && run.Cost.Tokens > 0 {
			fmt.Fprintf(errw, "cost: %d tokens, latency %.1fs\n", run.Cost.Tokens, float64(run.LatencyMs)/1000)
		}
	}
	if prURL != "" {
		fmt.Fprintf(cmd.OutOrStdout(), "PR: %s\n", prURL)
		fmt.Fprintf(errw, "Review it, then merge on GitHub or run: patchloop merge %s\n", runID)
	} else if r.Solved {
		fmt.Fprintf(errw, "No PR yet. Open one with: patchloop pr %s\n", runID)
	}
}

// ---- merge ------------------------------------------------------------------

func mergeCmd() *cobra.Command {
	var yes, jsonOut bool
	var method string
	c := &cobra.Command{
		Use:   "merge <run-id>",
		Short: "Merge a run's pull request with YOUR GitHub permissions (checks must be green)",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			cl, err := client()
			if err != nil {
				return err
			}
			ctx := cmd.Context()
			info, err := cl.PRInfo(ctx, args[0])
			if err != nil {
				return fail(cmd, err)
			}
			out := cmd.OutOrStdout()
			if !jsonOut {
				fmt.Fprintf(out, "PR #%d %s (%s)\n", info.Number, info.URL, info.State)
				checks := info.Checks.State
				if len(info.Checks.Failing) > 0 {
					checks += " (" + strings.Join(info.Checks.Failing, ", ") + ")"
				}
				fmt.Fprintf(out, "checks: %s\n", checks)
				if info.Fake {
					fmt.Fprintln(out, "[fake mode: demo repo, nothing real is merged]")
				}
			}
			if !info.MergeAllowed {
				if jsonOut {
					_ = printJSON(cmd, map[string]any{"merged": false, "reason": info.Reason})
				} else {
					fmt.Fprintf(cmd.ErrOrStderr(), "not merging: %s\n", info.Reason)
				}
				return &ExitError{Code: 1}
			}
			if info.Warning != "" && !jsonOut {
				fmt.Fprintf(out, "warning: %s\n", info.Warning)
			}
			if !yes {
				fmt.Fprintf(cmd.ErrOrStderr(), "Merge (%s) with your GitHub account? [y/N] ", orDefault(method, "squash"))
				line, _ := bufio.NewReader(cmd.InOrStdin()).ReadString('\n')
				if a := strings.ToLower(strings.TrimSpace(line)); a != "y" && a != "yes" {
					fmt.Fprintln(cmd.ErrOrStderr(), "cancelled")
					return &ExitError{Code: 1}
				}
			}
			res, err := cl.Merge(ctx, args[0], method)
			if err != nil {
				var ae *api.Error
				if errors.As(err, &ae) && ae.Code == "merge_refused" {
					fmt.Fprintf(cmd.ErrOrStderr(), "not merging: %s\n", ae.Message)
					return &ExitError{Code: 1}
				}
				return fail(cmd, err)
			}
			if jsonOut {
				return printJSON(cmd, res)
			}
			fmt.Fprintf(out, "Merged by %s (%s): %s\n", res.By, res.Method, res.URL)
			return nil
		},
	}
	c.Flags().BoolVarP(&yes, "yes", "y", false, "do not ask for confirmation")
	c.Flags().StringVar(&method, "method", "", "squash (default), merge or rebase")
	c.Flags().BoolVar(&jsonOut, "json", false, "print JSON")
	return c
}

func orDefault(s, d string) string {
	if s == "" {
		return d
	}
	return s
}

// ---- changes ----------------------------------------------------------------

func changesCmd() *cobra.Command {
	var jsonOut bool
	c := &cobra.Command{
		Use:   "changes <run-id> <message>",
		Short: "Ask for changes: pushes one more commit to the same pull request",
		Args:  cobra.MinimumNArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			cl, err := client()
			if err != nil {
				return err
			}
			child, err := cl.Followup(cmd.Context(), args[0], strings.Join(args[1:], " "))
			if err != nil {
				return fail(cmd, err)
			}
			if !jsonOut {
				fmt.Fprintf(cmd.ErrOrStderr(), "follow-up run %s started\n", child)
			}
			return watchRepoRun(cmd, cl, child, jsonOut)
		},
	}
	c.Flags().BoolVar(&jsonOut, "json", false, "print raw events")
	return c
}

// ---- slack ------------------------------------------------------------------

func slackCmd() *cobra.Command {
	root := &cobra.Command{Use: "slack", Short: "Slack integration: link your account, completion webhook"}
	root.AddCommand(
		&cobra.Command{
			Use:   "link",
			Short: "Create a one-time code, then run /patchloop link <code> in Slack",
			Args:  cobra.NoArgs,
			RunE: func(cmd *cobra.Command, args []string) error {
				cl, err := client()
				if err != nil {
					return err
				}
				lc, err := cl.SlackLinkCode(cmd.Context())
				if err != nil {
					return fail(cmd, err)
				}
				fmt.Fprintf(cmd.OutOrStdout(), "Your link code is %s (valid 10 minutes).\nIn Slack run:\n  /patchloop link %s\n", lc.Code, lc.Code)
				return nil
			},
		},
		&cobra.Command{
			Use:   "set <webhook-url>",
			Short: "Save a Slack incoming-webhook URL for completion messages",
			Args:  cobra.ExactArgs(1),
			RunE: func(cmd *cobra.Command, args []string) error {
				cl, err := client()
				if err != nil {
					return err
				}
				if err := cl.SetSlackWebhook(cmd.Context(), args[0]); err != nil {
					return fail(cmd, err)
				}
				fmt.Fprintln(cmd.OutOrStdout(), "Webhook saved. Try: patchloop slack test")
				return nil
			},
		},
		&cobra.Command{
			Use:   "test",
			Short: "Send a test card to your webhook",
			Args:  cobra.NoArgs,
			RunE: func(cmd *cobra.Command, args []string) error {
				cl, err := client()
				if err != nil {
					return err
				}
				if err := cl.TestSlack(cmd.Context()); err != nil {
					return fail(cmd, err)
				}
				fmt.Fprintln(cmd.OutOrStdout(), "Test message sent.")
				return nil
			},
		},
		&cobra.Command{
			Use:   "clear",
			Short: "Remove your webhook",
			Args:  cobra.NoArgs,
			RunE: func(cmd *cobra.Command, args []string) error {
				cl, err := client()
				if err != nil {
					return err
				}
				if err := cl.ClearSlackWebhook(cmd.Context()); err != nil {
					return fail(cmd, err)
				}
				fmt.Fprintln(cmd.OutOrStdout(), "Webhook removed.")
				return nil
			},
		},
	)
	return root
}

// ---- status / doctor --------------------------------------------------------

func statusCmd() *cobra.Command {
	var jsonOut bool
	c := &cobra.Command{
		Use:   "status",
		Short: "Show API, GitHub and Slack status",
		RunE: func(cmd *cobra.Command, args []string) error {
			cl, err := client()
			if err != nil {
				return err
			}
			ctx := cmd.Context()
			res := map[string]any{"api": cl.Base}
			if err := cl.Health(ctx); err != nil {
				res["apiReachable"] = false
			} else {
				res["apiReachable"] = true
			}
			gh, ghErr := cl.GitHubStatus(ctx)
			sl, slErr := cl.SlackSettings(ctx)
			res["github"], res["slack"] = gh, sl
			if jsonOut {
				return printJSON(cmd, res)
			}
			out := cmd.OutOrStdout()
			reach := "reachable"
			if res["apiReachable"] == false {
				reach = "UNREACHABLE"
			}
			fmt.Fprintf(out, "api     %s (%s)\n", cl.Base, reach)
			switch {
			case ghErr != nil:
				fmt.Fprintf(out, "github  unknown (%v)\n", ghErr)
			case gh.Connected:
				fmt.Fprintf(out, "github  connected as %s (%s), %d repos\n", gh.Login, gh.Mode, gh.RepoCount)
			default:
				fmt.Fprintln(out, "github  not connected: run patchloop connect github")
			}
			switch {
			case slErr != nil:
				fmt.Fprintf(out, "slack   unknown (%v)\n", slErr)
			default:
				fmt.Fprintf(out, "slack   account linked: %v · completion webhook: %s\n", sl.Linked, yesNo(sl.Configured, sl.WebhookURLMasked))
			}
			return nil
		},
	}
	c.Flags().BoolVar(&jsonOut, "json", false, "print JSON")
	return c
}

func yesNo(b bool, detail string) string {
	if b {
		return "set (" + detail + ")"
	}
	return "not set"
}

type check struct {
	name string
	ok   bool
	warn bool
	msg  string
	hint string
}

func doctorCmd() *cobra.Command {
	var jsonOut bool
	c := &cobra.Command{
		Use:   "doctor",
		Short: "Check API reachability, login, GitHub and Slack setup",
		RunE: func(cmd *cobra.Command, args []string) error {
			var checks []check
			add := func(c check) { checks = append(checks, c) }
			ctx := cmd.Context()

			cfg, err := config.Load()
			if err != nil {
				return fail(cmd, err)
			}
			base := resolveAPI(cfg)
			cl := api.New(base, cfg.Token)
			if err := cl.Health(ctx); err != nil {
				add(check{name: "API reachable", msg: fmt.Sprintf("%s: %v", base, err), hint: "Is the backend running? Set --api or PATCHLOOP_API"})
			} else {
				add(check{name: "API reachable", ok: true, msg: base})
			}
			if cfg.Token == "" {
				add(check{name: "Logged in", msg: "no token saved", hint: "patchloop login --token plk_..."})
			} else if me, err := cl.Me(ctx); err != nil {
				add(check{name: "Logged in", msg: err.Error(), hint: hintFor(err)})
			} else {
				add(check{name: "Logged in", ok: true, msg: me.Email})
				if gh, err := cl.GitHubStatus(ctx); err != nil {
					add(check{name: "GitHub", msg: err.Error(), hint: hintFor(err)})
				} else if !gh.Connected {
					add(check{name: "GitHub", msg: "not connected", hint: "patchloop connect github   (offline: --demo)"})
				} else if gh.RepoCount == 0 {
					add(check{name: "GitHub", warn: true, msg: fmt.Sprintf("connected as %s but no repositories granted", gh.Login), hint: "Grant repos to the GitHub App on GitHub"})
				} else {
					add(check{name: "GitHub", ok: true, msg: fmt.Sprintf("%s (%s), %d repos", gh.Login, gh.Mode, gh.RepoCount)})
				}
				if sl, err := cl.SlackSettings(ctx); err != nil {
					add(check{name: "Slack", warn: true, msg: err.Error()})
				} else if sl.Linked || sl.Configured {
					add(check{name: "Slack", ok: true, msg: fmt.Sprintf("linked=%v webhook=%v", sl.Linked, sl.Configured)})
				} else {
					add(check{name: "Slack", warn: true, msg: "not linked (optional)", hint: "patchloop slack link"})
				}
			}
			failed := false
			for _, ch := range checks {
				if !ch.ok && !ch.warn {
					failed = true
				}
			}
			if jsonOut {
				rows := []map[string]any{}
				for _, ch := range checks {
					rows = append(rows, map[string]any{"check": ch.name, "ok": ch.ok, "warning": ch.warn, "message": ch.msg, "hint": ch.hint})
				}
				_ = printJSON(cmd, rows)
			} else {
				out := cmd.OutOrStdout()
				col := useColor(out)
				for _, ch := range checks {
					mark := paint(col, "31", "✗")
					if ch.ok {
						mark = paint(col, "32", "✓")
					} else if ch.warn {
						mark = paint(col, "33", "!")
					}
					fmt.Fprintf(out, "%s %-14s %s\n", mark, ch.name, ch.msg)
					if !ch.ok && ch.hint != "" {
						fmt.Fprintf(out, "    %s\n", ch.hint)
					}
				}
			}
			if failed {
				return &ExitError{Code: 1}
			}
			return nil
		},
	}
	c.Flags().BoolVar(&jsonOut, "json", false, "print JSON")
	return c
}

func paint(on bool, code, s string) string {
	if !on {
		return s
	}
	return "\x1b[" + code + "m" + s + "\x1b[0m"
}
