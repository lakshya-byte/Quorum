package models

import (
	"time"

	"go.mongodb.org/mongo-driver/v2/bson"
)

const (
	RunStatusRunning   = "running"
	RunStatusCompleted = "completed"

	RunKindBug  = "bug"
	RunKindRepo = "repo"

	// Task types (CONTRACT-V3 §4). "auto" lets the planner choose.
	TaskTypeAuto      = "auto"
	TaskTypeBugfix    = "bugfix"
	TaskTypeFeature   = "feature"
	TaskTypeRefactor  = "refactor"
	TaskTypeUI        = "ui"
	TaskTypeTests     = "tests"
	TaskTypePerf      = "perf"
	TaskTypeDeps      = "deps"
	TaskTypeDocs      = "docs"
	TaskTypeMigration = "migration"
	TaskTypeOther     = "other"

	// Outcomes (CONTRACT-V3 §1).
	OutcomeComplete   = "complete"
	OutcomePartial    = "partial"
	OutcomeFailed     = "failed"
	OutcomeNeedsInput = "needs_input"
	OutcomeBlocked    = "blocked"

	SourceWeb    = "web"
	SourceCLI    = "cli"
	SourceSlack  = "slack"
	SourceGitHub = "github"
)

// SlackRef is where a Slack-started run reports: the channel, the thread it
// lives in and the root message it edits.
type SlackRef struct {
	Channel  string `bson:"channel" json:"channel"`
	ThreadTS string `bson:"thread_ts" json:"threadTs"`
	RootTS   string `bson:"root_ts" json:"rootTs"`
}

// IssueRef is the GitHub issue a run was triggered from.
type IssueRef struct {
	Number int `bson:"number" json:"number"`
}

// Merged records the human who merged the PR.
type Merged struct {
	By string    `bson:"by" json:"by"`
	At time.Time `bson:"at" json:"at"`
}

// Cost is what the run spent.
type Cost struct {
	Tokens int64   `bson:"tokens" json:"tokens"`
	USD    float64 `bson:"usd,omitempty" json:"usd,omitempty"`
}

// TaskTypes is the validated enum of task types, in display order.
var TaskTypes = []string{TaskTypeAuto, TaskTypeBugfix, TaskTypeFeature, TaskTypeRefactor, TaskTypeUI,
	TaskTypeTests, TaskTypePerf, TaskTypeDeps, TaskTypeDocs, TaskTypeMigration, TaskTypeOther}

// ValidTaskType reports whether t is a known task type.
func ValidTaskType(t string) bool {
	for _, v := range TaskTypes {
		if v == t {
			return true
		}
	}
	return false
}

// ValidOutcome reports whether o is a known outcome.
func ValidOutcome(o string) bool {
	switch o {
	case OutcomeComplete, OutcomePartial, OutcomeFailed, OutcomeNeedsInput, OutcomeBlocked:
		return true
	}
	return false
}

// Limits are the per-run swarm budgets the user asked for (already clamped).
type Limits struct {
	MaxWorkers int   `bson:"max_workers,omitempty" json:"maxWorkers,omitempty"`
	MaxTokens  int64 `bson:"max_tokens,omitempty" json:"maxTokens,omitempty"`
	MaxWallS   int   `bson:"max_wall_s,omitempty" json:"maxWallS,omitempty"`
}

// CriteriaSummary is the agent's verdict over the plan's criteria: hard gates
// passed/total and the advisory notes (score + rationale), as emitted.
type CriteriaSummary struct {
	HardPass  int   `bson:"hard_pass" json:"hardPass"`
	HardTotal int   `bson:"hard_total" json:"hardTotal"`
	Advisory  []any `bson:"advisory" json:"advisory"`
}

// Run is one debugging run. Nodes and Usage are stored as the agent reported
// them (free-form JSON). Guest runs have an empty UserID, Guest=true and a
// salted hash of the caller's IP (never the raw IP).
type Run struct {
	ID         bson.ObjectID  `bson:"_id,omitempty" json:"id"`
	UserID     string         `bson:"user_id" json:"userId"`
	BugID      string         `bson:"bug_id" json:"bugId"`
	AgentRunID string         `bson:"agent_run_id" json:"agentRunId"`
	Mode       string         `bson:"mode" json:"mode"`
	Engine     string         `bson:"engine" json:"engine"`
	Status     string         `bson:"status" json:"status"`
	Solved     bool           `bson:"solved" json:"solved"`
	BestNodeID any            `bson:"best_node_id" json:"bestNodeId"`
	Nodes      []any          `bson:"nodes" json:"nodes"`
	Usage      map[string]any `bson:"usage" json:"usage"`
	LatencyMs  int64          `bson:"latency_ms" json:"latencyMs"`
	PRURL      string         `bson:"pr_url" json:"prUrl"`
	PRNumber   int            `bson:"pr_number" json:"prNumber"`
	PRBranch   string         `bson:"pr_branch" json:"prBranch"`
	Kind       string         `bson:"kind" json:"kind"` // "bug" (bundled bug) or "repo" (GitHub repo task)
	Source     string         `bson:"source" json:"source"`
	Repo       string         `bson:"repo,omitempty" json:"repo"`
	Branch     string         `bson:"branch,omitempty" json:"branch"`
	Task       string         `bson:"task,omitempty" json:"task"`
	AutoPR     bool           `bson:"auto_pr" json:"autoPr"`
	// Swarm fields (CONTRACT-V3). TaskType is what the user asked for until the
	// agent reports the resolved type; TaskTypeSource says who chose it.
	TaskType        string           `bson:"task_type,omitempty" json:"taskType"`
	TaskTypeSource  string           `bson:"task_type_source,omitempty" json:"taskTypeSource"`
	Strict          []string         `bson:"strict,omitempty" json:"strict,omitempty"`
	Limits          *Limits          `bson:"limits,omitempty" json:"limits,omitempty"`
	Outcome         string           `bson:"outcome,omitempty" json:"outcome"`
	Plan            map[string]any   `bson:"plan,omitempty" json:"plan,omitempty"`
	CriteriaSummary *CriteriaSummary `bson:"criteria_summary,omitempty" json:"criteriaSummary,omitempty"`
	AgentsSpawned   int              `bson:"agents_spawned,omitempty" json:"agentsSpawned"`
	PeakParallel    int              `bson:"peak_parallel,omitempty" json:"peakParallel"`
	Artifacts       []any            `bson:"artifacts,omitempty" json:"artifacts"`
	Questions       []any            `bson:"questions,omitempty" json:"questions,omitempty"`
	ParentRunID     string           `bson:"parent_run_id,omitempty" json:"parentRunId"`
	Slack           *SlackRef        `bson:"slack,omitempty" json:"slack"`
	Issue           *IssueRef        `bson:"issue,omitempty" json:"issue"`
	Merged          *Merged          `bson:"merged,omitempty" json:"merged"`
	Cost            *Cost            `bson:"cost,omitempty" json:"cost"`
	Safety          map[string]any   `bson:"safety,omitempty" json:"safety"`
	TraceID         string           `bson:"trace_id,omitempty" json:"traceId"`
	LangsmithURL    string           `bson:"langsmith_url,omitempty" json:"langsmithUrl,omitempty"`
	FilesChanged    int              `bson:"files_changed,omitempty" json:"filesChanged"` // number of files the fix changes
	BestPassed      int              `bson:"best_passed,omitempty" json:"bestPassed"`     // tests the winning (or best) candidate passes; kept so lists need no nodes
	BestTotal       int              `bson:"best_total,omitempty" json:"bestTotal"`
	SlackSent       bool             `bson:"slack_sent" json:"slackSent"`
	Notice          string           `bson:"notice,omitempty" json:"notice,omitempty"`
	Guest           bool             `bson:"guest" json:"guest"`
	IPHash          string           `bson:"ip_hash,omitempty" json:"-"`
	Live            bool             `bson:"live" json:"-"` // requested live, counted against the daily cap
	CreatedAt       time.Time        `bson:"created_at" json:"createdAt"`
	CompletedAt     *time.Time       `bson:"completed_at" json:"completedAt"`
}

// HasPatch reports whether the run produced a change a human may review and
// merge: outcome complete, or partial (merge then carries a warning). Legacy
// runs without an outcome fall back to Solved.
func (r *Run) HasPatch() bool {
	switch r.Outcome {
	case OutcomeComplete, OutcomePartial:
		return true
	case "":
		return r.Solved
	}
	return false
}
