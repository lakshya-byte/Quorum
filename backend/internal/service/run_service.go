package service

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"time"

	"patchloop-backend/internal/models"
	"patchloop-backend/internal/observability"
	"patchloop-backend/internal/repository"

	"github.com/newrelic/go-agent/v3/newrelic"
	"go.mongodb.org/mongo-driver/v2/bson"
)

var (
	ErrInvalidBugID  = errors.New("invalid bugId")
	ErrInvalidEngine = errors.New(`engine must be "loop" or "graph"`)
	ErrRunNotFound   = errors.New("run not found")
	ErrRunNotReady   = errors.New("run has no agent run yet")
)

var bugIDPattern = regexp.MustCompile(`^[A-Za-z0-9_.-]{1,64}$`)

type RunService struct {
	runs  *repository.RunRepository
	agent *AgentClient
	slack *SlackNotifier
	nr    *newrelic.Application

	livePerDay int
	now        func() time.Time
}

type RunServiceConfig struct {
	LiveRunsPerUserPerDay int
}

func NewRunService(runs *repository.RunRepository, agent *AgentClient, slack *SlackNotifier, nr *newrelic.Application, cfg RunServiceConfig) *RunService {
	return &RunService{runs: runs, agent: agent, slack: slack, nr: nr, livePerDay: cfg.LiveRunsPerUserPerDay, now: time.Now}
}

func (s *RunService) Agent() *AgentClient { return s.agent }

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
// agent.
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
		_ = s.runs.SetStatus(ctx, run.ID, "failed")
		observability.L(ctx).Error("agent create run failed", "error", err.Error())
		return nil, err
	}
	engine := resp.Engine
	if engine == "" {
		engine = in.Engine
	}
	if engine == "" {
		engine = "loop"
	}
	if err := s.runs.SetAgentRun(ctx, run.ID, resp.RunID, resp.Mode, engine); err != nil {
		return nil, err
	}
	run.AgentRunID, run.Mode, run.Engine = resp.RunID, resp.Mode, engine

	observability.RecordEvent(ctx, s.nr, "RunRequested", map[string]any{
		"runId": run.ID.Hex(), "agentRunId": resp.RunID, "bugId": in.BugID, "engine": engine,
		"mode": resp.Mode, "guest": in.Guest, "replayRequested": in.Replay, "capped": notice != "",
	})
	return run, nil
}

func (s *RunService) Get(ctx context.Context, id string) (*models.Run, error) {
	oid, err := bson.ObjectIDFromHex(id)
	if err != nil {
		return nil, ErrRunNotFound
	}
	run, err := s.runs.FindByID(ctx, oid)
	if err != nil {
		if err == repository.ErrNotFound {
			return nil, ErrRunNotFound
		}
		return nil, err
	}
	return run, nil
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
	return s.runs.ListByUser(ctx, userID, 100)
}

func (s *RunService) OpenPR(ctx context.Context, run *models.Run) (string, error) {
	if run.AgentRunID == "" {
		return "", ErrRunNotReady
	}
	if run.PRURL != "" {
		return run.PRURL, nil
	}
	url, err := s.agent.OpenPR(ctx, run.AgentRunID)
	if err != nil {
		return "", err
	}
	if err := s.runs.SetPRURL(ctx, run.ID, url); err != nil {
		return "", err
	}
	run.PRURL = url
	if run.Solved {
		s.notifySlack(ctx, run, "pr_opened")
	}
	return url, nil
}

// CompletePayload is the agent's completion callback body (CONTRACT).
type CompletePayload struct {
	RunID      string         `json:"run_id"`
	UserID     string         `json:"user_id"`
	BugID      string         `json:"bug_id"`
	Mode       string         `json:"mode"`
	Engine     string         `json:"engine"`
	Solved     bool           `json:"solved"`
	BestNodeID any            `json:"best_node_id"`
	Nodes      []any          `json:"nodes"`
	Usage      map[string]any `json:"usage"`
	LatencyMs  float64        `json:"latency_ms"`
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
		})
		if err != repository.ErrNotFound {
			break
		}
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(100 * time.Millisecond):
		}
	}
	if err != nil {
		if err == repository.ErrNotFound {
			return nil, ErrRunNotFound
		}
		return nil, err
	}

	attrs := map[string]any{
		"runId": after.ID.Hex(), "agentRunId": agentRunID, "bugId": after.BugID, "engine": after.Engine,
		"mode": after.Mode, "solved": after.Solved, "latencyMs": after.LatencyMs, "nodes": len(after.Nodes),
		"guest": after.Guest,
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

	// Notify once, only for solved runs of real users.
	if after.Solved && before.Status != models.RunStatusCompleted && !after.Guest {
		s.notifySlack(ctx, after, "solved")
	}
	return after, nil
}

// notifySlack posts asynchronously; failures are logged, never returned.
func (s *RunService) notifySlack(ctx context.Context, run *models.Run, reason string) {
	if !s.slack.Enabled() {
		return
	}
	payload := s.slack.BuildRunMessage(run)
	runID := run.ID.Hex()
	trace, _ := observability.TraceFrom(ctx)
	go func() {
		bg := observability.WithRunID(observability.WithTrace(context.Background(), trace), runID)
		cctx, cancel := context.WithTimeout(bg, 6*time.Second)
		defer cancel()
		status, err := s.slack.Post(cctx, payload)
		attrs := map[string]any{"runId": runID, "reason": reason, "ok": err == nil, "statusCode": status}
		if err != nil {
			attrs["error"] = err.Error()
		}
		observability.RecordEvent(bg, s.nr, "SlackNotified", attrs)
	}()
}
