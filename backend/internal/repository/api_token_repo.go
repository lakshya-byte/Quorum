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

type ApiTokenRepository struct {
	col *mongo.Collection
}

func NewApiTokenRepository(db *mongo.Database) *ApiTokenRepository {
	return &ApiTokenRepository{col: db.Collection("apiTokens")}
}

func (r *ApiTokenRepository) Create(ctx context.Context, t *models.ApiToken) error {
	t.CreatedAt = time.Now().UTC()
	res, err := r.col.InsertOne(ctx, t)
	if err != nil {
		return err
	}
	t.ID = res.InsertedID.(bson.ObjectID)
	return nil
}

func (r *ApiTokenRepository) FindByHash(ctx context.Context, tokenHash string) (*models.ApiToken, error) {
	var t models.ApiToken
	if err := r.col.FindOne(ctx, bson.M{"token_hash": tokenHash}).Decode(&t); err != nil {
		if errors.Is(err, mongo.ErrNoDocuments) {
			return nil, ErrNotFound
		}
		return nil, err
	}
	return &t, nil
}

func (r *ApiTokenRepository) ListByUser(ctx context.Context, userID bson.ObjectID) ([]models.ApiToken, error) {
	cur, err := r.col.Find(ctx, bson.M{"user_id": userID}, options.Find().SetSort(bson.D{{Key: "created_at", Value: -1}}))
	if err != nil {
		return nil, err
	}
	out := []models.ApiToken{}
	if err := cur.All(ctx, &out); err != nil {
		return nil, err
	}
	return out, nil
}

// Delete removes a token only if it belongs to userID.
func (r *ApiTokenRepository) Delete(ctx context.Context, userID, id bson.ObjectID) error {
	res, err := r.col.DeleteOne(ctx, bson.M{"_id": id, "user_id": userID})
	if err != nil {
		return err
	}
	if res.DeletedCount == 0 {
		return ErrNotFound
	}
	return nil
}

func (r *ApiTokenRepository) TouchLastUsed(ctx context.Context, id bson.ObjectID) error {
	_, err := r.col.UpdateOne(ctx, bson.M{"_id": id}, bson.M{"$set": bson.M{"last_used_at": time.Now().UTC()}})
	return err
}
