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
	root.AddCommand(loginCmd(), whoamiCmd(), bugsCmd(), fixCmd(), runsCmd(), watchCmd(), prCmd())
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
			fmt.Fprintln(tw, "RUN\tBUG\tENGINE\tMODE\tSTATUS\tSOLVED\tCREATED\tPR")
			for _, r := range runs {
				fmt.Fprintf(tw, "%s\t%s\t%s\t%s\t%s\t%v\t%s\t%s\n", r.ID, r.BugID, r.Engine, r.Mode, r.Status, r.Solved,
					r.CreatedAt.Local().Format("2006-01-02 15:04"), r.PRURL)
			}
			return tw.Flush()
		},
	}
}

func prCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "pr <run-id>",
		Short: "Open a GitHub PR with the winning fix (a human still reviews and merges)",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			cl, err := client()
			if err != nil {
				return err
			}
			url, err := cl.OpenPR(cmd.Context(), args[0])
			if err != nil {
				return err
			}
			fmt.Fprintln(cmd.OutOrStdout(), url)
			return nil
		},
	}
}

func fixCmd() *cobra.Command {
	var engine string
	var replay, jsonOut bool
	c := &cobra.Command{
		Use:   "fix <bug-id>",
		Short: "Start a run and stream the agents' search tree (exit 0 if solved)",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			if engine != "" && engine != "loop" && engine != "graph" {
				return errors.New(`--engine must be "loop" or "graph"`)
			}
			cl, err := client()
			if err != nil {
				return err
			}
			run, err := cl.CreateRun(cmd.Context(), args[0], engine, replay)
			if err != nil {
				return err
			}
			if !jsonOut {
				fmt.Fprintf(cmd.ErrOrStderr(), "run %s started (mode=%s engine=%s)\n", run.RunID, run.Mode, run.Engine)
				if run.Notice != "" {
					fmt.Fprintf(cmd.ErrOrStderr(), "notice: %s\n", run.Notice)
				}
			}
			return stream(cmd, cl, run.RunID, jsonOut)
		},
	}
	c.Flags().StringVar(&engine, "engine", "", "search engine: graph or loop (default: server's)")
	c.Flags().BoolVar(&replay, "replay", false, "replay a recorded real run (no LLM/sandbox cost)")
	c.Flags().BoolVar(&jsonOut, "json", false, "print raw events, one JSON object per line")
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
