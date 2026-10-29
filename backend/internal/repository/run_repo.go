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

func (r *RunRepository) Create(ctx context.Context, run *models.Run) error {
	run.CreatedAt = time.Now().UTC()
	res, err := r.col.InsertOne(ctx, run)
	if err != nil {
		return err
	}
	run.ID = res.InsertedID.(bson.ObjectID)
	return nil
}

func (r *RunRepository) FindByID(ctx context.Context, id bson.ObjectID) (*models.Run, error) {
	var run models.Run
	if err := r.col.FindOne(ctx, bson.M{"_id": id}).Decode(&run); err != nil {
		if errors.Is(err, mongo.ErrNoDocuments) {
			return nil, ErrNotFound
		}
		return nil, err
	}
	return &run, nil
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

func (r *RunRepository) SetAgentRun(ctx context.Context, id bson.ObjectID, agentRunID, mode, engine string) error {
	_, err := r.col.UpdateOne(ctx, bson.M{"_id": id}, bson.M{"$set": bson.M{
		"agent_run_id": agentRunID, "mode": mode, "engine": engine,
	}})
	return err
}

func (r *RunRepository) SetStatus(ctx context.Context, id bson.ObjectID, status string) error {
	_, err := r.col.UpdateOne(ctx, bson.M{"_id": id}, bson.M{"$set": bson.M{"status": status}})
	return err
}

func (r *RunRepository) SetPRURL(ctx context.Context, id bson.ObjectID, url string) error {
	_, err := r.col.UpdateOne(ctx, bson.M{"_id": id}, bson.M{"$set": bson.M{"pr_url": url}})
	return err
}

// RunCompletion is what the agent reports when a run finishes.
type RunCompletion struct {
	Mode       string
	Engine     string
	Solved     bool
	BestNodeID any
	Nodes      []any
	Usage      map[string]any
	LatencyMs  int64
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
	var prev models.Run
	err = r.col.FindOneAndUpdate(ctx, bson.M{"agent_run_id": agentRunID}, bson.M{"$set": set},
		options.FindOneAndUpdate().SetReturnDocument(options.Before)).Decode(&prev)
	if err != nil {
		if errors.Is(err, mongo.ErrNoDocuments) {
			return nil, nil, ErrNotFound
		}
		return nil, nil, err
	}
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
	return &prev, &cur, nil
}
