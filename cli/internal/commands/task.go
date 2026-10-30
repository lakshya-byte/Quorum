package commands

import (
	"errors"
	"fmt"
	"strconv"
	"strings"

	"patchloop-cli/internal/api"

	"github.com/spf13/cobra"
)

// taskTypes is the server's enum (CONTRACT-V3); "auto" lets the planner choose.
var taskTypes = []string{"auto", "bugfix", "feature", "refactor", "ui", "tests", "perf", "deps", "docs", "migration", "other"}

func validTaskType(t string) bool {
	for _, v := range taskTypes {
		if v == t {
			return true
		}
	}
	return false
}

// parseLimits reads "workers=4,tokens=500000,wall=600" (maxWorkers/maxTokens/maxWallS also work).
func parseLimits(s string) (*api.Limits, error) {
	if strings.TrimSpace(s) == "" {
		return nil, nil
	}
	var l api.Limits
	for _, part := range strings.Split(s, ",") {
		k, v, ok := strings.Cut(strings.TrimSpace(part), "=")
		n, err := strconv.ParseInt(strings.TrimSpace(v), 10, 64)
		if !ok || err != nil || n < 0 {
			return nil, fmt.Errorf(`--limits: %q is not key=number (use workers=4,tokens=500000,wall=600)`, part)
		}
		switch strings.ToLower(strings.TrimSpace(k)) {
		case "workers", "maxworkers":
			l.MaxWorkers = int(n)
		case "tokens", "maxtokens":
			l.MaxTokens = n
		case "wall", "walls", "maxwalls":
			l.MaxWallS = int(n)
		default:
			return nil, fmt.Errorf(`--limits: unknown key %q (workers, tokens, wall)`, k)
		}
	}
	return &l, nil
}

// taskCmd builds `patchloop fix` and `patchloop do`: both start a swarm task on
// a repo; `fix` also keeps the bundled-bug demo mode when --repo is absent.
func taskCmd(name string) *cobra.Command {
	var engine, repo, branch, taskType, limitsStr string
	var strict []string
	var replay, jsonOut, noPR bool
	long := `With --repo, the argument is a plain-English task: a bug, a feature, a refactor, a UI change ...

  patchloop do  --repo octo/widgets --type ui "make the header responsive"
  patchloop fix --repo octo/widgets "pagination returns the wrong last page"

PatchLoop plans success criteria (hard gates and advisory checks), spawns a swarm
of agents sized to the task, runs everything in sandboxes and opens a pull request
only when its own checks pass. Agents never merge; you do (patchloop merge).

--type picks the task type (default auto: the planner decides). --strict promotes
advisory criteria to hard gates. --limits caps the swarm (workers=4,tokens=500000,wall=600).

Exit codes: 0 complete, 3 partial (hard gates pass, not everything could be verified),
1 failed or blocked, 2 error, 4 needs input (answer with: patchloop answer <run> "...").`
	short := "Run a task (bug, feature, refactor, UI ...) on a GitHub repo with an agent swarm"
	if name == "fix" {
		short = "Fix a bug (or run any task) on a GitHub repo (--repo), or fix a bundled demo bug"
		long += "\n\nWithout --repo, the argument is the id of a bundled bug (patchloop bugs)."
	}
	c := &cobra.Command{
		Use:   name + " --repo owner/name [--type auto|bugfix|feature|refactor|ui|...] <task>",
		Short: short,
		Long:  long,
		Args:  cobra.MinimumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			if engine != "" && engine != "loop" && engine != "graph" {
				return errors.New(`--engine must be "loop" or "graph"`)
			}
			taskType = strings.ToLower(strings.TrimSpace(taskType))
			if taskType != "" && !validTaskType(taskType) {
				return fmt.Errorf("--type must be one of: %s", strings.Join(taskTypes, ", "))
			}
			limits, err := parseLimits(limitsStr)
			if err != nil {
				return err
			}
			cl, err := client()
			if err != nil {
				if repo != "" {
					return fail(cmd, err)
				}
				return err
			}
			if repo != "" {
				return repoFix(cmd, cl, repo, strings.Join(args, " "), api.TaskOptions{
					Branch: branch, AutoPR: !noPR, TaskType: taskType, Strict: strict, Limits: limits}, jsonOut)
			}
			if name == "do" {
				return errors.New("patchloop do needs --repo owner/name")
			}
			if taskType != "" || len(strict) > 0 || limits != nil {
				return errors.New("--type, --strict and --limits only apply to repo tasks (--repo owner/name)")
			}
			if len(args) != 1 {
				return errors.New("a bundled bug takes exactly one id; use --repo owner/name to describe a task in your own repo")
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
	c.Flags().StringVar(&repo, "repo", "", "GitHub repo, owner/name (see: patchloop repos)")
	c.Flags().StringVar(&taskType, "type", "", "task type: "+strings.Join(taskTypes, "|")+" (default auto)")
	c.Flags().StringSliceVar(&strict, "strict", nil, "advisory criterion ids to promote to hard gates (comma separated)")
	c.Flags().StringVar(&limitsStr, "limits", "", "swarm caps, e.g. workers=4,tokens=500000,wall=600 (the server clamps them)")
	c.Flags().StringVar(&branch, "branch", "", "base branch (default: the repo's default branch)")
	c.Flags().BoolVar(&noPR, "no-pr", false, "do not open a pull request automatically (open later with: patchloop pr <run>)")
	c.Flags().BoolVar(&jsonOut, "json", false, "print raw events, one JSON object per line")
	if name == "fix" {
		c.Flags().StringVar(&engine, "engine", "", "bundled bugs: search engine, graph or loop (default: server's)")
		c.Flags().BoolVar(&replay, "replay", false, "bundled bugs: replay a recorded real run (no LLM/sandbox cost)")
	}
	return c
}
