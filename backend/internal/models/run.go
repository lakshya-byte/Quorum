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

// Run is one debugging run. Nodes and Usage are stored as the agent reported
// them (free-form JSON). Guest runs have an empty UserID, Guest=true and a
// salted hash of the caller's IP (never the raw IP).
type Run struct {
	ID           bson.ObjectID  `bson:"_id,omitempty" json:"id"`
	UserID       string         `bson:"user_id" json:"userId"`
	BugID        string         `bson:"bug_id" json:"bugId"`
	AgentRunID   string         `bson:"agent_run_id" json:"agentRunId"`
	Mode         string         `bson:"mode" json:"mode"`
	Engine       string         `bson:"engine" json:"engine"`
	Status       string         `bson:"status" json:"status"`
	Solved       bool           `bson:"solved" json:"solved"`
	BestNodeID   any            `bson:"best_node_id" json:"bestNodeId"`
	Nodes        []any          `bson:"nodes" json:"nodes"`
	Usage        map[string]any `bson:"usage" json:"usage"`
	LatencyMs    int64          `bson:"latency_ms" json:"latencyMs"`
	PRURL        string         `bson:"pr_url" json:"prUrl"`
	PRNumber     int            `bson:"pr_number" json:"prNumber"`
	PRBranch     string         `bson:"pr_branch" json:"prBranch"`
	Kind         string         `bson:"kind" json:"kind"` // "bug" (bundled bug) or "repo" (GitHub repo task)
	Source       string         `bson:"source" json:"source"`
	Repo         string         `bson:"repo,omitempty" json:"repo"`
	Branch       string         `bson:"branch,omitempty" json:"branch"`
	Task         string         `bson:"task,omitempty" json:"task"`
	AutoPR       bool           `bson:"auto_pr" json:"autoPr"`
	ParentRunID  string         `bson:"parent_run_id,omitempty" json:"parentRunId"`
	Slack        *SlackRef      `bson:"slack,omitempty" json:"slack"`
	Issue        *IssueRef      `bson:"issue,omitempty" json:"issue"`
	Merged       *Merged        `bson:"merged,omitempty" json:"merged"`
	Cost         *Cost          `bson:"cost,omitempty" json:"cost"`
	Safety       map[string]any `bson:"safety,omitempty" json:"safety"`
	TraceID      string         `bson:"trace_id,omitempty" json:"traceId"`
	LangsmithURL string         `bson:"langsmith_url,omitempty" json:"langsmithUrl,omitempty"`
	FilesChanged int            `bson:"files_changed,omitempty" json:"filesChanged"` // number of files the fix changes
	BestPassed   int            `bson:"best_passed,omitempty" json:"bestPassed"`     // tests the winning (or best) candidate passes; kept so lists need no nodes
	BestTotal    int            `bson:"best_total,omitempty" json:"bestTotal"`
	SlackSent    bool           `bson:"slack_sent" json:"slackSent"`
	Notice       string         `bson:"notice,omitempty" json:"notice,omitempty"`
	Guest        bool           `bson:"guest" json:"guest"`
	IPHash       string         `bson:"ip_hash,omitempty" json:"-"`
	Live         bool           `bson:"live" json:"-"` // requested live, counted against the daily cap
	CreatedAt    time.Time      `bson:"created_at" json:"createdAt"`
	CompletedAt  *time.Time     `bson:"completed_at" json:"completedAt"`
}
