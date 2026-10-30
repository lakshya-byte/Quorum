package service

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"patchloop-backend/internal/models"
	"patchloop-backend/internal/observability"
)

// MergeRefusedError carries the human-readable reason a merge was refused.
type MergeRefusedError struct{ Reason string }

func (e *MergeRefusedError) Error() string { return e.Reason }

// PRInfo is GET /api/runs/:id/pr.
type PRInfo struct {
	URL          string         `json:"url"`
	Number       int            `json:"number"`
	State        string         `json:"state"` // open | closed | merged
	Mergeable    *bool          `json:"mergeable"`
	Checks       ChecksSummary  `json:"checks"`
	MergeAllowed bool           `json:"mergeAllowed"`
	Reason       string         `json:"reason"`
	Warning      string         `json:"warning,omitempty"`
	Fake         bool           `json:"fake,omitempty"`
	Merged       *models.Merged `json:"merged,omitempty"`
	headSHA      string         // sha the checks were evaluated for; Merge pins to it
}

// MergeResult is the answer of a successful merge.
type MergeResult struct {
	Merged  bool   `json:"merged"`
	URL     string `json:"url"`
	Method  string `json:"method"`
	By      string `json:"by"`
	Warning string `json:"warning,omitempty"`
	Fake    bool   `json:"fake,omitempty"`
}

// MergeService is the ONLY place in the system that merges a pull request.
// It always acts with the human user's own GitHub token, and only when the PR
// is open, mergeable and its checks are green. The web handler, the Slack
// button and the CLI all call Merge.
type MergeService struct {
	github *GitHubService
	runs   RunStore
	svc    *RunService
	// DemoChecksDelay makes the fake CI of demo PRs report "pending" for this
	// long after the run finished, so the merge gate is visible in demos.
	DemoChecksDelay time.Duration
}

func NewMergeService(github *GitHubService, runs RunStore, svc *RunService) *MergeService {
	return &MergeService{github: github, runs: runs, svc: svc}
}

func evaluate(info *PRInfo) {
	info.MergeAllowed = false
	switch {
	case info.State == "merged":
		info.Reason = "pull request is already merged"
	case info.State != "open":
		info.Reason = "pull request is closed"
	case info.Mergeable == nil:
		info.Reason = "GitHub is still computing whether the pull request is mergeable; retry in a few seconds"
	case !*info.Mergeable:
		info.Reason = "pull request has conflicts or is otherwise not mergeable"
	case info.Checks.State == "failure":
		info.Reason = "checks are failing: " + strings.Join(info.Checks.Failing, ", ")
	case info.Checks.State == "pending":
		info.Reason = "checks are still running"
	case info.Checks.State == "none":
		info.MergeAllowed, info.Reason, info.Warning = true, "", "no checks configured"
	case info.Checks.State == "success":
		info.MergeAllowed, info.Reason = true, ""
	default: // fail closed on anything we do not understand
		info.Reason = "could not determine the state of the checks"
	}
}

// PartialWarning is attached to merge info/results of partial runs.
const PartialWarning = "partial result: some criteria had no executable verifier or only some units landed; review the pull request carefully"

// partialWarning adds the partial-outcome warning (merge stays allowed per
// the v2 rules; it only informs the human).
func partialWarning(info *PRInfo, run *models.Run) {
	if run.Outcome != models.OutcomePartial {
		return
	}
	if info.Warning == "" {
		info.Warning = PartialWarning
	} else {
		info.Warning += "; " + PartialWarning
	}
}

// Info reads the live PR state and applies the merge gate.
func (m *MergeService) Info(ctx context.Context, run *models.Run) (*PRInfo, error) {
	if run.Kind != models.RunKindRepo || run.PRNumber == 0 || run.PRURL == "" {
		return nil, ErrNoPR
	}
	if IsDemoRepo(run.Repo) || m.github.IsDemo(ctx, run.UserID) {
		info := &PRInfo{URL: run.PRURL, Number: run.PRNumber, State: "open", Fake: true}
		t := true
		info.Mergeable = &t
		info.Checks = ChecksSummary{State: "success", Failing: []string{}}
		if m.DemoChecksDelay > 0 && run.Merged == nil {
			since := run.CreatedAt
			if run.CompletedAt != nil {
				since = *run.CompletedAt
			}
			if m.svc.now().Sub(since) < m.DemoChecksDelay {
				info.Checks = ChecksSummary{State: "pending", Failing: []string{}}
			}
		}
		if run.Merged != nil {
			info.State = "merged"
		}
		evaluate(info)
		partialWarning(info, run)
		info.Merged = run.Merged
		return info, nil
	}
	auth, err := m.github.AgentToken(ctx, run.UserID)
	if err != nil {
		return nil, err
	}
	api := m.github.API()
	pr, err := api.GetPull(ctx, auth.Token, run.Repo, run.PRNumber)
	if err != nil {
		return nil, err
	}
	info := &PRInfo{URL: run.PRURL, Number: run.PRNumber, State: pr.State, Mergeable: pr.Mergeable, headSHA: pr.HeadSHA}
	if pr.Merged {
		info.State = "merged"
	}
	if run.Merged != nil {
		info.State = "merged"
	}
	if info.State == "open" {
		sum, err := api.Checks(ctx, auth.Token, run.Repo, pr.HeadSHA)
		if err != nil {
			return nil, err
		}
		info.Checks = *sum
	} else {
		info.Checks = ChecksSummary{State: "none", Failing: []string{}}
	}
	evaluate(info)
	partialWarning(info, run)
	info.Merged = run.Merged
	return info, nil
}

// Merge merges run's PR as userID (who must already be authorised on the run
// by the caller).
func (m *MergeService) Merge(ctx context.Context, run *models.Run, userID, method string) (*MergeResult, error) {
	if method == "" {
		method = "squash"
	}
	if method != "squash" && method != "merge" && method != "rebase" {
		return nil, &MergeRefusedError{Reason: `method must be "squash", "merge" or "rebase"`}
	}
	info, err := m.Info(ctx, run)
	if err != nil {
		return nil, err
	}
	if !info.MergeAllowed {
		return nil, &MergeRefusedError{Reason: info.Reason}
	}
	res := &MergeResult{Merged: true, URL: run.PRURL, Method: method, Warning: info.Warning, Fake: info.Fake}
	by := userID
	if conn, err := m.github.store.Get(ctx, userID); err == nil && conn.Login != "" {
		by = conn.Login
	}
	res.By = by
	if !info.Fake {
		userToken, err := m.github.UserToken(ctx, userID)
		if err != nil {
			if errors.Is(err, ErrNeedUserAuth) {
				return nil, &MergeRefusedError{Reason: ErrNeedUserAuth.Error()}
			}
			return nil, err
		}
		// Pin to the head sha the gate evaluated: if the branch moved since, GitHub refuses (409).
		if info.headSHA == "" {
			return nil, &MergeRefusedError{Reason: "could not determine the pull request head commit"}
		}
		if err := m.github.API().MergePull(ctx, userToken, run.Repo, run.PRNumber, method, info.headSHA); err != nil {
			var ge *GitHubAPIError
			if errors.As(err, &ge) && (ge.Status == 403 || ge.Status == 404 || ge.Status == 405 || ge.Status == 409 || ge.Status == 422) {
				reason := fmt.Sprintf("GitHub refused the merge: %s", ge.Message)
				if ge.Status == 409 || ge.Status == 422 {
					reason += " (the pull request may have changed since the checks were read; refresh and try again)"
				}
				return nil, &MergeRefusedError{Reason: reason}
			}
			return nil, err
		}
	}
	at := m.svc.now().UTC()
	if err := m.runs.SetMerged(ctx, run.ID.Hex(), by, at); err != nil {
		return nil, err
	}
	// The PR is one object: its other runs (the original and every follow-up) show it as merged too.
	if run.PRNumber > 0 {
		// The merge already happened on GitHub: a bookkeeping failure must not turn it into an error.
		if err := m.runs.SetMergedForPR(ctx, run.UserID, run.Repo, run.PRBranch, run.PRNumber, by, at); err != nil {
			slog.Warn("could not mark the PR's other runs merged", "run", run.ID.Hex(), "error", err.Error())
		}
	}
	run.Merged = &models.Merged{By: by, At: at}
	observability.RecordEvent(ctx, m.svc.nr, "PRMerged", map[string]any{"runId": run.ID.Hex(), "by": by, "method": method, "fake": res.Fake})
	m.svc.NotifyMerged(ctx, run)
	return res, nil
}
