package commands

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"text/tabwriter"

	"patchloop-cli/internal/api"

	"github.com/spf13/cobra"
)

var answerLine = regexp.MustCompile(`^\s*(?:q?(\d{1,2})|([A-Za-z][A-Za-z0-9_.-]{0,63}))\s*[:.)\-]\s*(.+)$`)

// parseAnswers maps free text onto question ids: lines "1: text", "q2: text" or
// "<id>: text" answer that question; text without such lines answers the first.
func parseAnswers(qs []api.Question, text string) map[string]string {
	ids := make([]string, 0, len(qs))
	byLower := map[string]string{}
	for _, q := range qs {
		ids = append(ids, q.ID)
		byLower[strings.ToLower(q.ID)] = q.ID
	}
	if len(ids) == 0 {
		ids = []string{"q1"}
		byLower["q1"] = "q1"
	}
	out := map[string]string{}
	last := ""
	for _, line := range strings.Split(text, "\n") {
		if m := answerLine.FindStringSubmatch(line); m != nil {
			id := ""
			if m[1] != "" {
				n := 0
				fmt.Sscanf(m[1], "%d", &n)
				if n >= 1 && n <= len(ids) {
					id = ids[n-1]
				}
			} else if v, ok := byLower[strings.ToLower(m[2])]; ok {
				id = v
			}
			if id != "" {
				out[id] = strings.TrimSpace(m[3])
				last = id
				continue
			}
		}
		if last != "" && strings.TrimSpace(line) != "" {
			out[last] += "\n" + strings.TrimSpace(line)
		}
	}
	if len(out) == 0 {
		out[ids[0]] = strings.TrimSpace(text)
	}
	return out
}

func answerCmd() *cobra.Command {
	var jsonOut bool
	var sets []string
	c := &cobra.Command{
		Use:   "answer <run-id> [text]",
		Short: "Answer the questions of a run that needs input; the swarm continues as a new run",
		Long: `When a run ends with "needs input", PatchLoop printed its questions. Answer them:

  patchloop answer <run> "1: the cart module"$'\n'"2: totals include shipping"
  patchloop answer <run> --set q1="the cart module" --set q2="totals include shipping"
  patchloop answer <run> "just do the cart module"      # plain text answers the first question

The answers re-run the task as a child run (same repo and branch) and stream it.
Exit codes are those of patchloop do.`,
		Args: cobra.MinimumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			cl, err := client()
			if err != nil {
				return err
			}
			runID := args[0]
			answers := map[string]string{}
			for _, kv := range sets {
				k, v, ok := strings.Cut(kv, "=")
				if !ok || strings.TrimSpace(k) == "" || strings.TrimSpace(v) == "" {
					return fmt.Errorf("--set wants id=text, got %q", kv)
				}
				answers[strings.TrimSpace(k)] = strings.TrimSpace(v)
			}
			if text := strings.TrimSpace(strings.Join(args[1:], " ")); text != "" {
				run, err := cl.GetRun(cmd.Context(), runID)
				if err != nil {
					return fail(cmd, err)
				}
				for k, v := range parseAnswers(run.Questions, strings.Join(args[1:], " ")) {
					if _, dup := answers[k]; !dup {
						answers[k] = v
					}
				}
			}
			if len(answers) == 0 {
				return errors.New(`give the answers as text or with --set id=text`)
			}
			child, err := cl.Answer(cmd.Context(), runID, answers)
			if err != nil {
				return fail(cmd, err)
			}
			if !jsonOut {
				fmt.Fprintf(cmd.ErrOrStderr(), "run %s started with your answers\n", child)
			}
			return watchRepoRun(cmd, cl, child, jsonOut)
		},
	}
	c.Flags().StringArrayVar(&sets, "set", nil, "answer one question: --set q1=text (repeatable)")
	c.Flags().BoolVar(&jsonOut, "json", false, "print raw events")
	return c
}

var extByMime = map[string]string{
	"image/png": ".png", "image/jpeg": ".jpg", "image/svg+xml": ".svg", "text/plain": ".txt", "application/json": ".json",
}

func artifactsCmd() *cobra.Command {
	var saveDir string
	var open, jsonOut bool
	c := &cobra.Command{
		Use:   "artifacts <run-id> [--save dir] [--open]",
		Short: "List a run's artifacts (screenshots, logs, reports) and optionally download them",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			cl, err := client()
			if err != nil {
				return err
			}
			arts, err := cl.Artifacts(cmd.Context(), args[0])
			if err != nil {
				return fail(cmd, err)
			}
			if jsonOut {
				return printJSON(cmd, arts)
			}
			out := cmd.OutOrStdout()
			if len(arts) == 0 {
				fmt.Fprintln(out, "No artifacts for this run.")
				return nil
			}
			tw := tabwriter.NewWriter(out, 0, 4, 2, ' ', 0)
			fmt.Fprintln(tw, "ID\tKIND\tPHASE\tVIEWPORT\tTYPE\tSIZE\tLABEL")
			for _, a := range arts {
				fmt.Fprintf(tw, "%s\t%s\t%s\t%s\t%s\t%d\t%s\n", a.ID, a.Kind, a.Phase, a.Viewport, a.Mime, a.Size, a.Label)
			}
			if err := tw.Flush(); err != nil {
				return err
			}
			if saveDir == "" && !open {
				return nil
			}
			if saveDir == "" {
				saveDir, err = os.MkdirTemp("", "patchloop-artifacts-")
				if err != nil {
					return err
				}
			}
			if err := os.MkdirAll(saveDir, 0o755); err != nil {
				return err
			}
			saved := 0
			for _, a := range arts {
				if !api.ValidArtifactID(a.ID) {
					fmt.Fprintf(cmd.ErrOrStderr(), "skipping artifact with unsafe id %q\n", a.ID)
					continue
				}
				data, err := cl.DownloadArtifact(cmd.Context(), args[0], a.ID)
				if err != nil {
					fmt.Fprintf(cmd.ErrOrStderr(), "could not download %s: %v\n", a.ID, err)
					continue
				}
				// The file name is built from the validated id and a fixed extension, never from server text.
				dst := filepath.Join(saveDir, a.ID+extByMime[a.Mime])
				if err := os.WriteFile(dst, data, 0o644); err != nil {
					return err
				}
				saved++
			}
			fmt.Fprintf(out, "Saved %d artifacts to %s\n", saved, saveDir)
			if open {
				if err := openURL(saveDir); err != nil {
					fmt.Fprintln(cmd.ErrOrStderr(), "(could not open the folder; it is at the path above)")
				}
			}
			return nil
		},
	}
	c.Flags().StringVar(&saveDir, "save", "", "download every artifact into this directory")
	c.Flags().BoolVar(&open, "open", false, "download to a temp directory (or --save) and open it")
	c.Flags().BoolVar(&jsonOut, "json", false, "print the artifact index as JSON")
	return c
}
