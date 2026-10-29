package service

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"strings"
	"time"

	"patchloop-backend/internal/models"
	"patchloop-backend/internal/observability"
	"patchloop-backend/internal/repository"

	"github.com/newrelic/go-agent/v3/newrelic"
)

var (
	ErrInvalidBugID   = errors.New("invalid bugId")
	ErrInvalidEngine  = errors.New(`engine must be "loop" or "graph"`)
	ErrRunNotFound    = errors.New("run not found")
	ErrRunNotReady    = errors.New("run has no agent run yet")
	ErrInvalidRepo    = errors.New(`repo must look like "owner/name"`)
	ErrInvalidBranch  = errors.New("invalid branch name")
	ErrInvalidTask    = errors.New("task must be 1 to 4000 characters")
	ErrRepoNotGranted = errors.New("that repository is not granted to the PatchLoop GitHub App: add it on GitHub, then retry")
	ErrNoPR           = errors.New("this run has no pull request to update")
	ErrFollowupLimit  = errors.New("follow-up limit reached for this pull request (5)")
	ErrRunNotDone     = errors.New("the run has not finished yet")
)

const maxFollowups = 5

var bugIDPattern = regexp.MustCompile(`^[A-Za-z0-9_.-]{1,64}$`)

// RunObserver gets told about repo runs so Slack can thread updates.
type RunObserver interface {
	RunStarted(run *models.Run)
	RunCompleted(ctx context.Context, run *models.Run)
}

type RunService struct {
	runs          RunStore
	agent         *AgentClient
	slack         *SlackNotifier // global/per-user incoming webhook
	nr            *newrelic.Application
	github        *GitHubService
	notifications NotificationStore
	observer      RunObserver
	userWebhook   func(ctx context.Context, userID string) string

	livePerDay int
	publicURL  string
	now        func() time.Time
}

type RunServiceConfig struct {
	LiveRunsPerUserPerDay int
	PublicAppURL          string
}

func NewRunService(runs RunStore, agent *AgentClient, slack *SlackNotifier, nr *newrelic.Application, cfg RunServiceConfig) *RunService {
	return &RunService{runs: runs, agent: agent, slack: slack, nr: nr, livePerDay: cfg.LiveRunsPerUserPerDay,
		publicURL: strings.TrimRight(cfg.PublicAppURL, "/"), now: time.Now}
}

func (s *RunService) Agent() *AgentClient { return s.agent }

// Wire optional collaborators (kept out of the constructor so tests stay small).
func (s *RunService) SetGitHub(g *GitHubService)                            { s.github = g }
func (s *RunService) SetNotifications(n NotificationStore)                  { s.notifications = n }
func (s *RunService) SetObserver(o RunObserver)                             { s.observer = o }
func (s *RunService) SetUserWebhook(f func(context.Context, string) string) { s.userWebhook = f }

// RunURL is the public page of a run.
func (s *RunService) RunURL(run *models.Run) string {
	return fmt.Sprintf("%s/runs/%s", s.publicURL, run.ID.Hex())
}

func normalize(r *models.Run) *models.Run {
	if r.Kind == "" {
		r.Kind = models.RunKindBug
	}
	if r.Source == "" {
		r.Source = models.SourceWeb
	}
	return r
}

type CreateRunInput struct {
	UserID string // empty for guests
	BugID  string
	Engine string
	Replay bool
	Guest  bool
	IPHash string
}

func (s *RunService) ListBugs(ctx context.Context) ([]AgentBug, error) {
	return s.agent.ListBugs(ctx)
}

// CreateRun validates the request, applies the daily live cap (falling back
// to a replay, explained in Run.Notice), stores the run and starts it on the
// agent. This is the bundled-bug flow (web demo and guests).
func (s *RunService) CreateRun(ctx context.Context, in CreateRunInput) (*models.Run, error) {
	if !bugIDPattern.MatchString(in.BugID) {
		return nil, ErrInvalidBugID
	}
	if in.Engine != "" && in.Engine != "loop" && in.Engine != "graph" {
		return nil, ErrInvalidEngine
	}

	replay := in.Replay
	notice := ""
	if in.Guest {
		replay = true // guests never spend live budget
	} else if !replay && s.livePerDay >= 0 {
		n, err := s.runs.CountLiveSince(ctx, in.UserID, s.now().Add(-24*time.Hour))
		if err != nil {
			return nil, err
		}
		if n >= int64(s.livePerDay) {
			replay = true
			notice = fmt.Sprintf("daily live run limit reached (%d per 24h): running a replay of a recorded real run instead (or a fake run if none is recorded)", s.livePerDay)
		}
	}

	run := &models.Run{
		UserID: in.UserID,
		BugID:  in.BugID,
		Engine: in.Engine,
		Kind:   models.RunKindBug,
		Source: models.SourceWeb,
		Status: models.RunStatusRunning,
		Notice: notice,
		Guest:  in.Guest,
		IPHash: in.IPHash,
		Live:   !replay,
		Nodes:  []any{},
	}
	if err := s.runs.Create(ctx, run); err != nil {
		return nil, err
	}
	ctx = observability.WithRunID(ctx, run.ID.Hex())

	resp, err := s.agent.CreateRun(ctx, AgentCreateRunRequest{
		BugID:  in.BugID,
		UserID: in.UserID,
		Engine: in.Engine,
		Replay: replay,
	})
	if err != nil {
		_ = s.runs.SetStatus(ctx, run.ID.Hex(), "failed")
		observability.L(ctx).Error("agent create run failed", "error", err.Error())
		return nil, err
	}
	engine := resp.Engine
	if engine == "" {
		engine = in.Engine
	}
	if engine == "" {
		engine = "graph" // the agent's default engine (CONTRACT)
	}
	if err := s.runs.SetAgentRun(ctx, run.ID.Hex(), resp.RunID, resp.Mode, engine, ""); err != nil {
		return nil, err
	}
	run.AgentRunID, run.Mode, run.Engine = resp.RunID, resp.Mode, engine

	observability.RecordEvent(ctx, s.nr, "RunRequested", map[string]any{
		"runId": run.ID.Hex(), "agentRunId": resp.RunID, "bugId": in.BugID, "engine": engine,
		"mode": resp.Mode, "guest": in.Guest, "replayRequested": in.Replay, "capped": notice != "",
	})
	return run, nil
}

// RepoRunInput starts a fix on a GitHub repo, whichever entry point asked
// (web, CLI, Slack, GitHub issue).
type RepoRunInput struct {
	UserID   string
	Repo     string
	Branch   string // empty = the repo's default branch
	Task     string
	Source   string
	Engine   string
	AutoPR   bool
	Slack    *models.SlackRef
	Issue    *models.IssueRef
	Parent   *models.Run // set for follow-ups
	Followup string      // the "ask for changes" message
}

// redact removes secrets from an error before it is logged or returned.
func redact(err error, secrets ...string) error {
	if err == nil {
		return nil
	}
	msg := err.Error()
	changed := false
	for _, sec := range secrets {
		if sec != "" && strings.Contains(msg, sec) {
			msg = strings.ReplaceAll(msg, sec, "[redacted]")
			changed = true
		}
	}
	if !changed {
		return err
	}
	var ae *AgentError
	if errors.As(err, &ae) {
		return &AgentError{Status: ae.Status, Message: strings.ReplaceAll(ae.Message, strings.TrimSpace(secrets[0]), "[redacted]")}
	}
	return errors.New(msg)
}

func (s *RunService) StartRepoRun(ctx context.Context, in RepoRunInput) (*models.Run, error) {
	task := strings.TrimSpace(in.Task)
	if task == "" || len([]rune(task)) > 4000 {
		return nil, ErrInvalidTask
	}
	if !ValidRepoName(in.Repo) {
		return nil, ErrInvalidRepo
	}
	if in.Branch != "" && !ValidBranch(in.Branch) {
		return nil, ErrInvalidBranch
	}
	if in.Engine != "" && in.Engine != "loop" && in.Engine != "graph" {
		return nil, ErrInvalidEngine
	}
	if s.github == nil {
		return nil, ErrGitHubNotConnected
	}
	auth, err := s.github.AgentToken(ctx, in.UserID)
	if err != nil {
		return nil, err
	}
	branch := in.Branch
	if IsDemoRepo(in.Repo) {
		auth.Token = "" // bundled repos never need a token
		if branch == "" {
			branch = "main"
		}
	} else {
		if auth.Demo {
			return nil, errors.New("the demo account only has the bundled demo repos (demo/...)")
		}
		repos, err := s.github.Repos(ctx, in.UserID, "")
		if err != nil {
			return nil, err
		}
		found := false
		for _, r := range repos {
			if strings.EqualFold(r.FullName, in.Repo) {
				found = true
				if branch == "" {
					branch = r.DefaultBranch
				}
			}
		}
		if !found {
			return nil, ErrRepoNotGranted
		}
	}
	if branch == "" {
		branch = "main"
	}

	run := &models.Run{
		UserID: in.UserID, Kind: models.RunKindRepo, Source: in.Source, Engine: in.Engine,
		Repo: in.Repo, Branch: branch, Task: task, AutoPR: in.AutoPR, Slack: in.Slack, Issue: in.Issue,
		BugID: in.Repo, Status: models.RunStatusRunning, Nodes: []any{},
	}
	if run.Source == "" {
		run.Source = models.SourceWeb
	}
	req := AgentRepoRunRequest{
		Task: task, Repo: AgentRepoRef{FullName: in.Repo, Branch: branch}, UserID: in.UserID,
		Engine: in.Engine, AutoPR: in.AutoPR, Source: run.Source,
	}
	if auth.Token != "" {
		t := auth.Token
		req.GitHubToken = &t
	}
	if in.Issue != nil {
		n := in.Issue.Number
		req.IssueRef = &n
	}
	if in.Parent != nil {
		root := in.Parent.ParentRunID
		if root == "" {
			root = in.Parent.ID.Hex()
		}
		n, err := s.runs.CountChildren(ctx, root)
		if err != nil {
			return nil, err
		}
		if n >= maxFollowups {
			return nil, ErrFollowupLimit
		}
		if in.Parent.PRNumber == 0 || in.Parent.PRBranch == "" {
			return nil, ErrNoPR
		}
		run.ParentRunID = root
		run.Branch = in.Parent.Branch
		run.PRURL, run.PRNumber, run.PRBranch = in.Parent.PRURL, in.Parent.PRNumber, in.Parent.PRBranch
		run.Task = in.Parent.Task
		req.Task = in.Parent.Task
		req.Repo.Branch = in.Parent.Branch
		req.Followup = &AgentFollowup{PRBranch: in.Parent.PRBranch, PRNumber: in.Parent.PRNumber,
			Message: in.Followup, PreviousFiles: BestFiles(in.Parent)}
	}
	if err := s.runs.Create(ctx, run); err != nil {
		return nil, err
	}
	ctx = observability.WithRunID(ctx, run.ID.Hex())
	req.RunURL = s.RunURL(run)

	resp, err := s.agent.CreateRepoRun(ctx, req)
	if err != nil {
		_ = s.runs.SetStatus(ctx, run.ID.Hex(), "failed")
		err = redact(err, auth.Token)
		observability.L(ctx).Error("agent create repo run failed", "error", err.Error())
		return nil, err
	}
	engine := resp.Engine
	if engine == "" {
		engine = in.Engine
	}
	if engine == "" {
		engine = "graph"
	}
	if err := s.runs.SetAgentRun(ctx, run.ID.Hex(), resp.RunID, resp.Mode, engine, resp.TraceID); err != nil {
		return nil, err
	}
	run.AgentRunID, run.Mode, run.Engine, run.TraceID = resp.RunID, resp.Mode, engine, resp.TraceID

	observability.RecordEvent(ctx, s.nr, "RepoRunRequested", map[string]any{
		"runId": run.ID.Hex(), "agentRunId": resp.RunID, "repo": in.Repo, "source": run.Source,
		"mode": resp.Mode, "engine": engine, "followup": in.Parent != nil,
	})
	if s.observer != nil && run.Slack != nil {
		s.observer.RunStarted(run)
	}
	return run, nil
}

// BestFiles returns the winning candidate's files (path -> content).
func BestFiles(run *models.Run) map[string]string {
	best := fmt.Sprint(run.BestNodeID)
	for _, n := range run.Nodes {
		m, ok := n.(map[string]any)
		if !ok || fmt.Sprint(m["id"]) != best {
			continue
		}
		files, _ := m["files"].(map[string]any)
		out := map[string]string{}
		for p, c := range files {
			if str, ok := c.(string); ok {
				out[p] = str
			}
		}
		return out
	}
	return nil
}

func (s *RunService) Get(ctx context.Context, id string) (*models.Run, error) {
	run, err := s.runs.FindByID(ctx, id)
	if err != nil {
		if errors.Is(err, repository.ErrNotFound) {
			return nil, ErrRunNotFound
		}
		return nil, err
	}
	return normalize(run), nil
}

// GetOwned returns the run only if userID owns it (404 otherwise, to avoid
// leaking which ids exist).
func (s *RunService) GetOwned(ctx context.Context, id, userID string) (*models.Run, error) {
	run, err := s.Get(ctx, id)
	if err != nil {
		return nil, err
	}
	if run.Guest || run.UserID == "" || run.UserID != userID {
		return nil, ErrRunNotFound
	}
	return run, nil
}

func (s *RunService) ListMine(ctx context.Context, userID string) ([]models.Run, error) {
	runs, err := s.runs.ListByUser(ctx, userID, 100)
	for i := range runs {
		normalize(&runs[i])
	}
	return runs, err
}

// FindByPR finds the most recent run that owns a PR.
func (s *RunService) FindByPR(ctx context.Context, repo string, number int) (*models.Run, error) {
	run, err := s.runs.FindByPR(ctx, repo, number)
	if err != nil {
		if errors.Is(err, repository.ErrNotFound) {
			return nil, ErrRunNotFound
		}
		return nil, err
	}
	return normalize(run), nil
}

// FindBySlackThread finds the most recent run living in a Slack thread.
func (s *RunService) FindBySlackThread(ctx context.Context, channel, threadTS string) (*models.Run, error) {
	run, err := s.runs.FindBySlackThread(ctx, channel, threadTS)
	if err != nil {
		if errors.Is(err, repository.ErrNotFound) {
			return nil, ErrRunNotFound
		}
		return nil, err
	}
	return normalize(run), nil
}

// Followup starts a child run that pushes one more commit to run's PR branch.
func (s *RunService) Followup(ctx context.Context, run *models.Run, source, message string, slack *models.SlackRef) (*models.Run, error) {
	message = strings.TrimSpace(message)
	if message == "" || len([]rune(message)) > 2000 {
		return nil, errors.New("message must be 1 to 2000 characters")
	}
	if run.Kind != models.RunKindRepo {
		return nil, ErrNoPR
	}
	if run.Status != models.RunStatusCompleted {
		return nil, ErrRunNotDone
	}
	if slack == nil {
		slack = run.Slack
	}
	return s.StartRepoRun(ctx, RepoRunInput{
		UserID: run.UserID, Repo: run.Repo, Branch: run.Branch, Task: run.Task, Source: source,
		Slack: slack, Issue: run.Issue, Parent: run, Followup: message, AutoPR: true,
	})
}

// OpenPR opens the PR of a solved run whose auto_pr was off.
func (s *RunService) OpenPR(ctx context.Context, run *models.Run) (string, error) {
	if run.AgentRunID == "" {
		return "", ErrRunNotReady
	}
	if run.PRURL != "" {
		return run.PRURL, nil
	}
	token := ""
	if run.Kind == models.RunKindRepo && s.github != nil {
		auth, err := s.github.AgentToken(ctx, run.UserID)
		if err != nil {
			return "", err
		}
		token = auth.Token
	}
	pr, err := s.agent.OpenPR(ctx, run.AgentRunID, token)
	if err != nil {
		return "", redact(err, token)
	}
	if err := s.runs.SetPR(ctx, run.ID.Hex(), pr.URL, pr.Number, pr.Branch); err != nil {
		return "", err
	}
	run.PRURL, run.PRNumber, run.PRBranch = pr.URL, pr.Number, pr.Branch
	if run.Solved {
		s.notify(ctx, run, "pr_opened", "Pull request opened", fmt.Sprintf("%s: %s", run.Repo, pr.URL))
		s.notifySlack(ctx, run, "pr_opened")
	}
	return pr.URL, nil
}

// CompletePayload is the agent's completion callback body (CONTRACT).
type CompletePayload struct {
	RunID        string         `json:"run_id"`
	UserID       string         `json:"user_id"`
	BugID        string         `json:"bug_id"`
	Kind         string         `json:"kind"`
	Repo         string         `json:"repo"`
	Branch       string         `json:"branch"`
	Task         string         `json:"task"`
	Mode         string         `json:"mode"`
	Engine       string         `json:"engine"`
	Solved       bool           `json:"solved"`
	BestNodeID   any            `json:"best_node_id"`
	Nodes        []any          `json:"nodes"`
	Usage        map[string]any `json:"usage"`
	LatencyMs    float64        `json:"latency_ms"`
	PRURL        string         `json:"pr_url"`
	PRNumber     int            `json:"pr_number"`
	PRBranch     string         `json:"pr_branch"`
	FilesChanged any            `json:"files_changed"`
	Safety       map[string]any `json:"safety"`
	LangsmithURL string         `json:"langsmith_url"`
}

func costFromUsage(u map[string]any) *models.Cost {
	if u == nil {
		return nil
	}
	pt, _ := toInt(u["prompt_tokens"])
	ct, _ := toInt(u["completion_tokens"])
	c := &models.Cost{Tokens: int64(pt + ct)}
	for _, k := range []string{"cost_usd", "usd"} {
		if f, ok := u[k].(float64); ok {
			c.USD = f
		}
	}
	if c.Tokens == 0 && c.USD == 0 {
		return nil
	}
	return c
}

// Complete stores the agent's result for agentRunID. The agent may call back
// before CreateRun has saved the agent run id, so the lookup retries briefly.
func (s *RunService) Complete(ctx context.Context, agentRunID string, p CompletePayload) (*models.Run, error) {
	ctx = observability.WithRunID(ctx, agentRunID)
	if p.Nodes == nil {
		p.Nodes = []any{}
	}
	var (
		before, after *models.Run
		err           error
	)
	for attempt := 0; attempt < 20; attempt++ {
		before, after, err = s.runs.Complete(ctx, agentRunID, repository.RunCompletion{
			Mode: p.Mode, Engine: p.Engine, Solved: p.Solved, BestNodeID: p.BestNodeID,
			Nodes: p.Nodes, Usage: p.Usage, LatencyMs: int64(p.LatencyMs),
			PRURL: p.PRURL, PRNumber: p.PRNumber, PRBranch: p.PRBranch, FilesChanged: p.FilesChanged,
			Safety: p.Safety, Cost: costFromUsage(p.Usage), LangsmithURL: p.LangsmithURL,
		})
		if !errors.Is(err, repository.ErrNotFound) {
			break
		}
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(100 * time.Millisecond):
		}
	}
	if err != nil {
		if errors.Is(err, repository.ErrNotFound) {
			return nil, ErrRunNotFound
		}
		return nil, err
	}
	normalize(before)
	normalize(after)

	attrs := map[string]any{
		"runId": after.ID.Hex(), "agentRunId": agentRunID, "bugId": after.BugID, "engine": after.Engine,
		"mode": after.Mode, "solved": after.Solved, "latencyMs": after.LatencyMs, "nodes": len(after.Nodes),
		"guest": after.Guest, "kind": after.Kind, "source": after.Source,
	}
	if after.Usage != nil {
		if v, ok := toInt(after.Usage["prompt_tokens"]); ok {
			attrs["promptTokens"] = v
		}
		if v, ok := toInt(after.Usage["completion_tokens"]); ok {
			attrs["completionTokens"] = v
		}
	}
	observability.RecordEvent(ctx, s.nr, "RunCompleted", attrs)

	first := before.Status != models.RunStatusCompleted
	if !first || after.Guest {
		return after, nil
	}
	if after.Kind == models.RunKindRepo {
		s.afterRepoRun(ctx, after, before)
	} else if after.Solved {
		// Bundled-bug runs: notify once, only for solved runs of real users.
		s.notifySlack(ctx, after, "solved")
	}
	return after, nil
}

// afterRepoRun fans a finished repo run out to in-app notifications, Slack
// and (for issue-triggered runs) a GitHub comment.
func (s *RunService) afterRepoRun(ctx context.Context, run, before *models.Run) {
	switch {
	case run.PRURL != "" && run.Solved && run.ParentRunID != "":
		s.notify(ctx, run, "pr_updated", "Pull request updated", fmt.Sprintf("%s: new commit pushed to %s", run.Repo, run.PRURL))
	case run.PRURL != "" && run.Solved:
		s.notify(ctx, run, "pr_opened", "Pull request opened", fmt.Sprintf("%s: %s", run.Repo, run.PRURL))
	case !run.Solved:
		s.notify(ctx, run, "failed", "No passing fix found", fmt.Sprintf("%s: PatchLoop could not produce a fix that passes the tests", run.Repo))
	}
	if s.observer != nil && run.Slack != nil {
		s.observer.RunCompleted(ctx, run)
	} else {
		s.notifySlack(ctx, run, "completed")
	}
	if run.Source == models.SourceGitHub && run.Issue != nil && s.github != nil && run.PRURL != "" && !IsDemoRepo(run.Repo) {
		go s.commentIssue(run)
	}
}

func (s *RunService) commentIssue(run *models.Run) {
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	auth, err := s.github.AgentToken(ctx, run.UserID)
	if err != nil || auth.Token == "" {
		return
	}
	body := fmt.Sprintf("PatchLoop opened a pull request for this issue: %s\n\nA human must review and merge it. Run: %s", run.PRURL, s.RunURL(run))
	if err := s.github.API().CommentIssue(ctx, auth.Token, run.Repo, run.Issue.Number, body); err != nil {
		observability.L(ctx).Error("issue comment failed", "error", redact(err, auth.Token).Error())
	}
}

// Notify creates an in-app notification (best effort).
func (s *RunService) notify(ctx context.Context, run *models.Run, kind, title, body string) {
	if s.notifications == nil || run.UserID == "" {
		return
	}
	n := &models.Notification{UserID: run.UserID, Kind: kind, RunID: run.ID.Hex(), Title: title, Body: body}
	if err := s.notifications.Create(ctx, n); err != nil {
		observability.L(ctx).Error("notification failed", "error", err.Error())
	}
}

// NotifyMerged is called by the merge service.
func (s *RunService) NotifyMerged(ctx context.Context, run *models.Run) {
	s.notify(ctx, run, "merged", "Pull request merged", fmt.Sprintf("%s: %s", run.Repo, run.PRURL))
}

// notifySlack posts a webhook message asynchronously; failures are logged,
// never returned. Destination: the owner's webhook, else the global one.
func (s *RunService) notifySlack(ctx context.Context, run *models.Run, reason string) {
	runID := run.ID.Hex()
	trace, _ := observability.TraceFrom(ctx)
	copyRun := *run
	go func() {
		bg := observability.WithRunID(observability.WithTrace(context.Background(), trace), runID)
		hook := ""
		if s.userWebhook != nil && copyRun.UserID != "" {
			hook = s.userWebhook(bg, copyRun.UserID)
		}
		if hook == "" && s.slack != nil {
			hook = s.slack.WebhookURL
		}
		if hook == "" {
			return
		}
		var payload map[string]any
		if copyRun.Kind == models.RunKindRepo {
			payload = s.slack.BuildRepoRunMessage(&copyRun, s.RunURL(&copyRun))
		} else {
			payload = s.slack.BuildRunMessage(&copyRun)
		}
		cctx, cancel := context.WithTimeout(bg, 6*time.Second)
		defer cancel()
		status, err := s.slack.PostTo(cctx, hook, payload)
		attrs := map[string]any{"runId": runID, "reason": reason, "ok": err == nil, "statusCode": status}
		if err != nil {
			attrs["error"] = err.Error()
		} else {
			_ = s.runs.SetSlackSent(bg, runID)
		}
		observability.RecordEvent(bg, s.nr, "SlackNotified", attrs)
	}()
}
