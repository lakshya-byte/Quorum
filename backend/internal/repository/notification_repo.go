package repository

import (
	"context"
	"time"

	"patchloop-backend/internal/models"

	"go.mongodb.org/mongo-driver/v2/bson"
	"go.mongodb.org/mongo-driver/v2/mongo"
	"go.mongodb.org/mongo-driver/v2/mongo/options"
)

type NotificationRepository struct{ col *mongo.Collection }

func NewNotificationRepository(db *mongo.Database) *NotificationRepository {
	return &NotificationRepository{col: db.Collection("notifications")}
}

func (r *NotificationRepository) Create(ctx context.Context, n *models.Notification) error {
	n.CreatedAt = time.Now().UTC()
	res, err := r.col.InsertOne(ctx, n)
	if err != nil {
		return err
	}
	n.ID = res.InsertedID.(bson.ObjectID)
	return nil
}

func (r *NotificationRepository) ListByUser(ctx context.Context, userID string, limit int64) ([]models.Notification, error) {
	cur, err := r.col.Find(ctx, bson.M{"user_id": userID},
		options.Find().SetSort(bson.D{{Key: "created_at", Value: -1}}).SetLimit(limit))
	if err != nil {
		return nil, err
	}
	out := []models.Notification{}
	if err := cur.All(ctx, &out); err != nil {
		return nil, err
	}
	return out, nil
}

func (r *NotificationRepository) MarkRead(ctx context.Context, userID, id string) error {
	o, err := oid(id)
	if err != nil {
		return err
	}
	res, err := r.col.UpdateOne(ctx, bson.M{"_id": o, "user_id": userID}, bson.M{"$set": bson.M{"read": true}})
	if err != nil {
		return err
	}
	if res.MatchedCount == 0 {
		return ErrNotFound
	}
	return nil
}

// DedupeRepository remembers delivery ids for 24h (TTL index on created_at).
type DedupeRepository struct{ col *mongo.Collection }

func NewDedupeRepository(db *mongo.Database) *DedupeRepository {
	return &DedupeRepository{col: db.Collection("webhook_dedupe")}
}

// Seen records key and reports whether it was already recorded.
func (r *DedupeRepository) Seen(ctx context.Context, key string) (bool, error) {
	_, err := r.col.InsertOne(ctx, bson.M{"_id": key, "created_at": time.Now().UTC()})
	if err != nil {
		if mongo.IsDuplicateKeyError(err) {
			return true, nil
		}
		return false, err
	}
	return false, nil
}
