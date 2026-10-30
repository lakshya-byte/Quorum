package app_test

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"patchloop-backend/internal/memstore"
	"patchloop-backend/internal/models"
	"patchloop-backend/internal/repository"
)

// The Mongo run repository and the in-memory store must persist and return
// the swarm fields identically.
func TestSwarmFieldsPersistInMongoAndMemstore(t *testing.T) {
	db := testDatabase(t)
	ctx := context.Background()
	mongoRepo := repository.NewRunRepository(db)
	mem := memstore.New()

	completion := repository.RunCompletion{
		Mode: "fake", Engine: "graph", Solved: false, BestNodeID: 0.0, Nodes: []any{map[string]any{"id": 0, "passed": 8, "total": 9}},
		Outcome: models.OutcomePartial, TaskType: models.TaskTypeUI, TaskTypeSource: "auto",
		Plan:            map[string]any{"task_type": "ui", "criteria": []any{map[string]any{"id": "build", "hard": true}}, "units": []any{map[string]any{"id": "u1"}}},
		CriteriaSummary: &models.CriteriaSummary{HardPass: 8, HardTotal: 9, Advisory: []any{map[string]any{"criterion_id": "vision_rubric", "score": 0.8}}},
		AgentsSpawned:   7, PeakParallel: 3,
		Artifacts: []any{map[string]any{"id": "shot-after-375", "mime": "image/png", "size": 100}},
		Questions: []any{map[string]any{"id": "q1", "text": "which?"}},
	}
	type store interface {
		Create(context.Context, *models.Run) error
		SetAgentRun(ctx context.Context, id string, agentRunID, mode, engine, traceID string) error
		FindByID(context.Context, string) (*models.Run, error)
		ListByUser(context.Context, string, int64) ([]models.Run, error)
		Complete(context.Context, string, repository.RunCompletion) (*models.Run, *models.Run, error)
	}
	var results []map[string]any
	for name, s := range map[string]store{"mongo": mongoRepo, "mem": mem} {
		run := &models.Run{UserID: "u-swarm-" + name, Kind: models.RunKindRepo, Repo: "o/n", Status: models.RunStatusRunning,
			TaskType: models.TaskTypeAuto, TaskTypeSource: "auto", Strict: []string{"vision_rubric"},
			Limits: &models.Limits{MaxWorkers: 4, MaxTokens: 1000, MaxWallS: 60}, Nodes: []any{}}
		if err := s.Create(ctx, run); err != nil {
			t.Fatal(name, err)
		}
		agentID := "agent-" + name + "-" + time.Now().Format("150405.000000")
		if err := s.SetAgentRun(ctx, run.ID.Hex(), agentID, "fake", "graph", ""); err != nil {
			t.Fatal(name, err)
		}
		if _, _, err := s.Complete(ctx, agentID, completion); err != nil {
			t.Fatal(name, err)
		}
		got, err := s.FindByID(ctx, run.ID.Hex())
		if err != nil {
			t.Fatal(name, err)
		}
		if got.Outcome != "partial" || got.TaskType != "ui" || got.TaskTypeSource != "auto" || got.AgentsSpawned != 7 || got.PeakParallel != 3 ||
			got.CriteriaSummary == nil || got.CriteriaSummary.HardPass != 8 || len(got.Artifacts) != 1 || len(got.Questions) != 1 ||
			got.Limits == nil || got.Limits.MaxWorkers != 4 || len(got.Strict) != 1 || got.Plan["task_type"] != "ui" {
			t.Fatalf("%s: swarm fields lost: %+v", name, got)
		}
		// Nested arrays come back as bson.A from Mongo: they must serialise to the same JSON.
		pj, _ := json.Marshal(got.Plan)
		if string(pj) != `{"criteria":[{"hard":true,"id":"build"}],"task_type":"ui","units":[{"id":"u1"}]}` {
			t.Fatalf("%s: plan JSON: %s", name, pj)
		}
		list, err := s.ListByUser(ctx, run.UserID, 10)
		if err != nil || len(list) != 1 || list[0].Plan != nil || list[0].Nodes != nil || list[0].Outcome != "partial" {
			t.Fatalf("%s list: plan and nodes are left out of lists: %v %+v", name, err, list)
		}
		b, _ := json.Marshal(got)
		var m map[string]any
		_ = json.Unmarshal(b, &m)
		results = append(results, m)
	}
	for _, k := range []string{"taskType", "taskTypeSource", "outcome", "criteriaSummary", "agentsSpawned", "peakParallel", "artifacts", "questions", "limits", "strict"} {
		a, _ := json.Marshal(results[0][k])
		b, _ := json.Marshal(results[1][k])
		if string(a) != string(b) {
			t.Errorf("JSON field %q differs between stores: %s vs %s", k, a, b)
		}
	}
}

func TestSwarmIndexesExist(t *testing.T) {
	db := testDatabase(t)
	cur, err := db.Collection("runs").Indexes().List(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	var idx []map[string]any
	if err := cur.All(context.Background(), &idx); err != nil {
		t.Fatal(err)
	}
	b, _ := json.Marshal(idx)
	for _, want := range []string{"task_type", "outcome"} {
		if !contains(string(b), want) {
			t.Errorf("no index on %s: %s", want, b)
		}
	}
}

func contains(s, sub string) bool {
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return true
		}
	}
	return false
}
