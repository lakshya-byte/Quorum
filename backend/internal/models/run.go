package models

import (
	"time"

	"go.mongodb.org/mongo-driver/v2/bson"
)

const (
	RunStatusRunning   = "running"
	RunStatusCompleted = "completed"
)

// Run is one debugging run. Nodes and Usage are stored as the agent reported
// them (free-form JSON). Guest runs have an empty UserID, Guest=true and a
// salted hash of the caller's IP (never the raw IP).
type Run struct {
	ID          bson.ObjectID  `bson:"_id,omitempty" json:"id"`
	UserID      string         `bson:"user_id" json:"userId"`
	BugID       string         `bson:"bug_id" json:"bugId"`
	AgentRunID  string         `bson:"agent_run_id" json:"agentRunId"`
	Mode        string         `bson:"mode" json:"mode"`
	Engine      string         `bson:"engine" json:"engine"`
	Status      string         `bson:"status" json:"status"`
	Solved      bool           `bson:"solved" json:"solved"`
	BestNodeID  any            `bson:"best_node_id" json:"bestNodeId"`
	Nodes       []any          `bson:"nodes" json:"nodes"`
	Usage       map[string]any `bson:"usage" json:"usage"`
	LatencyMs   int64          `bson:"latency_ms" json:"latencyMs"`
	PRURL       string         `bson:"pr_url" json:"prUrl"`
	Notice      string         `bson:"notice,omitempty" json:"notice,omitempty"`
	Guest       bool           `bson:"guest" json:"guest"`
	IPHash      string         `bson:"ip_hash,omitempty" json:"-"`
	Live        bool           `bson:"live" json:"-"` // requested live, counted against the daily cap
	CreatedAt   time.Time      `bson:"created_at" json:"createdAt"`
	CompletedAt *time.Time     `bson:"completed_at" json:"completedAt"`
}
