// Package commands implements the patchloop commands.
package commands

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/signal"
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

// ExitError carries a process exit code without printing anything extra.
type ExitError struct{ Code int }

func (e *ExitError) Error() string { return fmt.Sprintf("exit %d", e.Code) }

var apiFlag string

func NewRoot() *cobra.Command {
	root := &cobra.Command{
		Use:           "patchloop",
		Short:         "PatchLoop: AI agents propose fixes, tests decide, humans merge",
		SilenceUsage:  true,
		SilenceErrors: true,
	}
	root.PersistentFlags().StringVar(&apiFlag, "api", "", "backend URL (default: saved config, $PATCHLOOP_API, or "+config.DefaultAPI+")")
	root.AddCommand(loginCmd(), whoamiCmd(), bugsCmd(), taskCmd("fix"), taskCmd("do"), runsCmd(), watchCmd(), prCmd())
	root.AddCommand(answerCmd(), artifactsCmd())
	root.AddCommand(repoCommands()...)
	return root
}

// Execute runs the CLI and returns the process exit code.
func Execute() int {
	err := NewRoot().Execute()
	if err == nil {
		return 0
	}
	var ee *ExitError
	if errors.As(err, &ee) {
		return ee.Code
	}
	fmt.Fprintln(os.Stderr, "error:", err)
	if h := hintFor(err); h != "" {
		fmt.Fprintln(os.Stderr, "hint:", h)
	}
	return 1
}

func resolveAPI(cfg *config.Config) string {
	switch {
	case apiFlag != "":
		return apiFlag
	case os.Getenv("PATCHLOOP_API") != "":
		return os.Getenv("PATCHLOOP_API")
	case cfg.API != "":
		return cfg.API
	}
	return config.DefaultAPI
}

func client() (*api.Client, error) {
	cfg, err := config.Load()
	if err != nil {
		return nil, err
	}
	if cfg.Token == "" {
		return nil, errors.New("not logged in: run `patchloop login --token plk_...`")
	}
	return api.New(resolveAPI(cfg), cfg.Token), nil
}

func useColor(w io.Writer) bool {
	if _, ok := os.LookupEnv("NO_COLOR"); ok {
		return false
	}
	if os.Getenv("TERM") == "dumb" {
		return false
	}
	f, ok := w.(*os.File)
	if !ok {
		return false
	}
	st, err := f.Stat()
	return err == nil && st.Mode()&os.ModeCharDevice != 0
}

func loginCmd() *cobra.Command {
	var token string
	c := &cobra.Command{
		Use:   "login --token plk_... [--api URL]",
		Short: "Save an API token (create one in the web app or via POST /api/tokens)",
		RunE: func(cmd *cobra.Command, args []string) error {
			if token == "" {
				token = os.Getenv("PATCHLOOP_TOKEN")
			}
			if !strings.HasPrefix(token, "plk_") {
				return errors.New("--token must be a PatchLoop API token starting with plk_")
			}
			cfg, err := config.Load()
			if err != nil {
				return err
			}
			base := resolveAPI(cfg)
			ctx, cancel := context.WithTimeout(cmd.Context(), 15*time.Second)
			defer cancel()
			me, err := api.New(base, token).Me(ctx)
			if err != nil {
				return fmt.Errorf("token check against %s failed: %w", base, err)
			}
			path, err := config.Save(&config.Config{API: base, Token: token})
			if err != nil {
				return err
			}
			fmt.Fprintf(cmd.OutOrStdout(), "Logged in to %s as %s. Config saved to %s\n", base, me.Email, path)
			return nil
		},
	}
	c.Flags().StringVar(&token, "token", "", "API token (plk_...); or set PATCHLOOP_TOKEN")
	return c
}

func whoamiCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "whoami",
		Short: "Show the account the saved token belongs to",
		RunE: func(cmd *cobra.Command, args []string) error {
			cl, err := client()
			if err != nil {
				return err
			}
			me, err := cl.Me(cmd.Context())
			if err != nil {
				return err
			}
			fmt.Fprintf(cmd.OutOrStdout(), "%s (%s) on %s\n", me.Email, me.CompanyName, cl.Base)
			return nil
		},
	}
}

func bugsCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "bugs",
		Short: "List bugs the agents can fix",
		RunE: func(cmd *cobra.Command, args []string) error {
			cl, err := client()
			if err != nil {
				return err
			}
			bugs, err := cl.Bugs(cmd.Context())
			if err != nil {
				return err
			}
			tw := tabwriter.NewWriter(cmd.OutOrStdout(), 0, 4, 2, ' ', 0)
			fmt.Fprintln(tw, "ID\tTIER\tTITLE")
			for _, b := range bugs {
				tier := ""
				if b.Tier != nil {
					tier = fmt.Sprint(b.Tier)
				}
				fmt.Fprintf(tw, "%s\t%s\t%s\n", b.ID, tier, b.Title)
			}
			return tw.Flush()
		},
	}
}

func runsCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "runs",
		Short: "List your recent runs",
		RunE: func(cmd *cobra.Command, args []string) error {
			cl, err := client()
			if err != nil {
				return err
			}
			runs, err := cl.Runs(cmd.Context())
			if err != nil {
				return err
			}
			tw := tabwriter.NewWriter(cmd.OutOrStdout(), 0, 4, 2, ' ', 0)
			fmt.Fprintln(tw, "RUN\tTARGET\tTYPE\tSOURCE\tMODE\tSTATUS\tOUTCOME\tCREATED\tPR")
			for _, r := range runs {
				target := r.BugID
				if r.Kind == "repo" {
					target = r.Repo
				}
				source := r.Source
				if source == "" {
					source = "web"
				}
				outcome := r.Outcome
				if outcome == "" {
					outcome = "failed"
					if r.Solved {
						outcome = "complete"
					}
					if r.Status != "completed" {
						outcome = "-"
					}
				}
				taskType := r.TaskType
				if taskType == "" {
					taskType = "-"
				}
				fmt.Fprintf(tw, "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n", r.ID, target, taskType, source, r.Mode, r.Status, outcome,
					r.CreatedAt.Local().Format("2006-01-02 15:04"), r.PRURL)
			}
			return tw.Flush()
		},
	}
}

func prCmd() *cobra.Command {
	var status bool
	c := &cobra.Command{
		Use:   "pr <run-id>",
		Short: "Open a GitHub PR with the winning fix, or (--status) show its checks (a human still reviews and merges)",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			cl, err := client()
			if err != nil {
				return err
			}
			if status {
				info, err := cl.PRInfo(cmd.Context(), args[0])
				if err != nil {
					return err
				}
				out := cmd.OutOrStdout()
				fmt.Fprintf(out, "PR #%d %s (%s)\nchecks: %s\n", info.Number, info.URL, info.State, info.Checks.State)
				if info.MergeAllowed {
					fmt.Fprintf(out, "mergeable: yes. Merge with: patchloop merge %s\n", args[0])
				} else {
					fmt.Fprintf(out, "not mergeable yet: %s\n", info.Reason)
				}
				if info.Warning != "" {
					fmt.Fprintf(out, "warning: %s\n", info.Warning)
				}
				return nil
			}
			url, err := cl.OpenPR(cmd.Context(), args[0])
			if err != nil {
				return err
			}
			fmt.Fprintln(cmd.OutOrStdout(), url)
			return nil
		},
	}
	c.Flags().BoolVar(&status, "status", false, "show PR state and checks instead of opening a PR")
	return c
}

func watchCmd() *cobra.Command {
	var jsonOut bool
	c := &cobra.Command{
		Use:   "watch <run-id>",
		Short: "Stream an existing run (exit 0 if solved)",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			cl, err := client()
			if err != nil {
				return err
			}
			if run, err := cl.GetRun(cmd.Context(), args[0]); err == nil && run.Kind == "repo" {
				return watchRepoRun(cmd, cl, args[0], jsonOut)
			}
			return stream(cmd, cl, args[0], jsonOut)
		},
	}
	c.Flags().BoolVar(&jsonOut, "json", false, "print raw events, one JSON object per line")
	return c
}

// stream renders a run's events. Ctrl-C closes only the stream: the run
// keeps going on the server and can be resumed with `patchloop watch`.
func stream(cmd *cobra.Command, cl *api.Client, runID string, jsonOut bool) error {
	ctx, stop := signal.NotifyContext(cmd.Context(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	out := cmd.OutOrStdout()
	body, err := cl.Stream(ctx, api.EventsPath(runID))
	if err != nil {
		return err
	}
	defer body.Close()

	r := render.New(out, useColor(out))
	rd := sse.NewReader(body)
	for {
		ev, err := rd.Next()
		if err != nil {
			if ctx.Err() != nil {
				fmt.Fprintf(cmd.ErrOrStderr(), "\nstream closed; the run continues on the server. Resume with: patchloop watch %s\n", runID)
				return &ExitError{Code: 130}
			}
			if err != io.EOF {
				fmt.Fprintln(cmd.ErrOrStderr(), "stream error:", err)
			}
			break
		}
		if jsonOut {
			if ev.Raw != "" {
				fmt.Fprintln(out, ev.Raw)
			}
			// Still track state for the exit code.
			r2 := render.New(io.Discard, false)
			r2.Event(ev)
			if r2.Done {
				r.Done, r.Solved = true, r2.Solved
			}
		} else {
			r.Event(ev)
		}
		if ev.Type == "end" {
			break
		}
	}
	if !jsonOut && !r.Done && len(r.Errors) == 0 {
		fmt.Fprintln(cmd.ErrOrStderr(), "stream ended before the run finished")
	}
	if !jsonOut {
		fmt.Fprintf(cmd.ErrOrStderr(), "run id: %s\n", runID)
	}
	if r.Solved {
		return nil
	}
	return &ExitError{Code: 1}
}
