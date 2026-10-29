package repository

import (
	"context"
	"errors"
	"time"

	"patchloop-backend/internal/models"

	"go.mongodb.org/mongo-driver/v2/bson"
	"go.mongodb.org/mongo-driver/v2/mongo"
	"go.mongodb.org/mongo-driver/v2/mongo/options"
)

type RunRepository struct {
	col *mongo.Collection
}

func NewRunRepository(db *mongo.Database) *RunRepository {
	// Nodes/usage are free-form; decode nested documents as plain maps so
	// they serialise to natural JSON.
	opts := options.Collection().SetBSONOptions(&options.BSONOptions{DefaultDocumentMap: true})
	return &RunRepository{col: db.Collection("runs", opts)}
}

func oid(id string) (bson.ObjectID, error) {
	o, err := bson.ObjectIDFromHex(id)
	if err != nil {
		return o, ErrNotFound
	}
	return o, nil
}

func (r *RunRepository) Create(ctx context.Context, run *models.Run) error {
	run.CreatedAt = time.Now().UTC()
	res, err := r.col.InsertOne(ctx, run)
	if err != nil {
		return err
	}
	run.ID = res.InsertedID.(bson.ObjectID)
	return nil
}

func (r *RunRepository) findOne(ctx context.Context, filter bson.M) (*models.Run, error) {
	var run models.Run
	if err := r.col.FindOne(ctx, filter).Decode(&run); err != nil {
		if errors.Is(err, mongo.ErrNoDocuments) {
			return nil, ErrNotFound
		}
		return nil, err
	}
	return &run, nil
}

func (r *RunRepository) FindByID(ctx context.Context, id string) (*models.Run, error) {
	o, err := oid(id)
	if err != nil {
		return nil, err
	}
	return r.findOne(ctx, bson.M{"_id": o})
}

func (r *RunRepository) ListByUser(ctx context.Context, userID string, limit int64) ([]models.Run, error) {
	opts := options.Find().SetSort(bson.D{{Key: "created_at", Value: -1}}).SetLimit(limit).
		SetProjection(bson.M{"nodes": 0})
	cur, err := r.col.Find(ctx, bson.M{"user_id": userID}, opts)
	if err != nil {
		return nil, err
	}
	runs := []models.Run{}
	if err := cur.All(ctx, &runs); err != nil {
		return nil, err
	}
	return runs, nil
}

// CountLiveSince counts the user's live-requested runs created after since.
func (r *RunRepository) CountLiveSince(ctx context.Context, userID string, since time.Time) (int64, error) {
	return r.col.CountDocuments(ctx, bson.M{
		"user_id":    userID,
		"live":       true,
		"created_at": bson.M{"$gte": since},
	})
}

func (r *RunRepository) set(ctx context.Context, id string, set bson.M) error {
	o, err := oid(id)
	if err != nil {
		return err
	}
	_, err = r.col.UpdateOne(ctx, bson.M{"_id": o}, bson.M{"$set": set})
	return err
}

func (r *RunRepository) SetAgentRun(ctx context.Context, id string, agentRunID, mode, engine, traceID string) error {
	set := bson.M{"agent_run_id": agentRunID, "mode": mode, "engine": engine}
	if traceID != "" {
		set["trace_id"] = traceID
	}
	return r.set(ctx, id, set)
}

func (r *RunRepository) SetStatus(ctx context.Context, id string, status string) error {
	return r.set(ctx, id, bson.M{"status": status})
}

func (r *RunRepository) SetPR(ctx context.Context, id string, url string, number int, branch string) error {
	set := bson.M{"pr_url": url}
	if number > 0 {
		set["pr_number"] = number
	}
	if branch != "" {
		set["pr_branch"] = branch
	}
	return r.set(ctx, id, set)
}

func (r *RunRepository) SetMerged(ctx context.Context, id string, by string, at time.Time) error {
	return r.set(ctx, id, bson.M{"merged": models.Merged{By: by, At: at}})
}

func (r *RunRepository) SetSlackSent(ctx context.Context, id string) error {
	return r.set(ctx, id, bson.M{"slack_sent": true})
}

func (r *RunRepository) SetSlackRoot(ctx context.Context, id string, rootTS string) error {
	return r.set(ctx, id, bson.M{"slack.root_ts": rootTS})
}

func (r *RunRepository) FindBySlackThread(ctx context.Context, channel, threadTS string) (*models.Run, error) {
	// Newest first: a follow-up child shares its parent's thread.
	var run models.Run
	err := r.col.FindOne(ctx, bson.M{"slack.channel": channel, "slack.thread_ts": threadTS},
		options.FindOne().SetSort(bson.D{{Key: "created_at", Value: -1}})).Decode(&run)
	if err != nil {
		if errors.Is(err, mongo.ErrNoDocuments) {
			return nil, ErrNotFound
		}
		return nil, err
	}
	return &run, nil
}

func (r *RunRepository) FindByPR(ctx context.Context, repo string, number int) (*models.Run, error) {
	var run models.Run
	err := r.col.FindOne(ctx, bson.M{"repo": repo, "pr_number": number},
		options.FindOne().SetSort(bson.D{{Key: "created_at", Value: -1}})).Decode(&run)
	if err != nil {
		if errors.Is(err, mongo.ErrNoDocuments) {
			return nil, ErrNotFound
		}
		return nil, err
	}
	return &run, nil
}

func (r *RunRepository) CountChildren(ctx context.Context, parentID string) (int64, error) {
	return r.col.CountDocuments(ctx, bson.M{"parent_run_id": parentID})
}

// RunCompletion is what the agent reports when a run finishes. Optional
// fields are only written when non-empty.
type RunCompletion struct {
	Mode         string
	Engine       string
	Solved       bool
	BestNodeID   any
	Nodes        []any
	Usage        map[string]any
	LatencyMs    int64
	PRURL        string
	PRNumber     int
	PRBranch     string
	FilesChanged int
	Safety       map[string]any
	Cost         *models.Cost
	LangsmithURL string
}

// Complete marks the run with the given agent run id as completed and
// returns the run as it was before the update (to detect repeat callbacks).
func (r *RunRepository) Complete(ctx context.Context, agentRunID string, c RunCompletion) (before *models.Run, after *models.Run, err error) {
	now := time.Now().UTC()
	set := bson.M{
		"status":       models.RunStatusCompleted,
		"solved":       c.Solved,
		"best_node_id": c.BestNodeID,
		"nodes":        c.Nodes,
		"usage":        c.Usage,
		"latency_ms":   c.LatencyMs,
		"completed_at": now,
	}
	if c.Mode != "" {
		set["mode"] = c.Mode
	}
	if c.Engine != "" {
		set["engine"] = c.Engine
	}
	if c.PRURL != "" {
		set["pr_url"] = c.PRURL
	}
	if c.PRNumber > 0 {
		set["pr_number"] = c.PRNumber
	}
	if c.PRBranch != "" {
		set["pr_branch"] = c.PRBranch
	}
	if c.FilesChanged > 0 {
		set["files_changed"] = c.FilesChanged
	}
	if c.Safety != nil {
		set["safety"] = c.Safety
	}
	if c.Cost != nil {
		set["cost"] = c.Cost
	}
	if c.LangsmithURL != "" {
		set["langsmith_url"] = c.LangsmithURL
	}
	var prev models.Run
	err = r.col.FindOneAndUpdate(ctx, bson.M{"agent_run_id": agentRunID}, bson.M{"$set": set},
		options.FindOneAndUpdate().SetReturnDocument(options.Before)).Decode(&prev)
	if err != nil {
		if errors.Is(err, mongo.ErrNoDocuments) {
			return nil, nil, ErrNotFound
		}
		return nil, nil, err
	}
	return &prev, ApplyCompletion(prev, c, now), nil
}

// ApplyCompletion returns run with a completion merged in (shared by the
// Mongo and in-memory stores so both behave identically).
func ApplyCompletion(prev models.Run, c RunCompletion, now time.Time) *models.Run {
	cur := prev
	cur.Status = models.RunStatusCompleted
	cur.Solved = c.Solved
	cur.BestNodeID = c.BestNodeID
	cur.Nodes = c.Nodes
	cur.Usage = c.Usage
	cur.LatencyMs = c.LatencyMs
	cur.CompletedAt = &now
	if c.Mode != "" {
		cur.Mode = c.Mode
	}
	if c.Engine != "" {
		cur.Engine = c.Engine
	}
	if c.PRURL != "" {
		cur.PRURL = c.PRURL
	}
	if c.PRNumber > 0 {
		cur.PRNumber = c.PRNumber
	}
	if c.PRBranch != "" {
		cur.PRBranch = c.PRBranch
	}
	if c.FilesChanged > 0 {
		cur.FilesChanged = c.FilesChanged
	}
	if c.Safety != nil {
		cur.Safety = c.Safety
	}
	if c.Cost != nil {
		cur.Cost = c.Cost
	}
	if c.LangsmithURL != "" {
		cur.LangsmithURL = c.LangsmithURL
	}
	return &cur
}
