package repository

import (
	"context"
	"errors"
	"time"

	"patchloop-backend/internal/models"

	"go.mongodb.org/mongo-driver/v2/bson"
	"go.mongodb.org/mongo-driver/v2/mongo"
)

type TokenRepository struct {
	col *mongo.Collection
}

func NewTokenRepository(db *mongo.Database) *TokenRepository {
	return &TokenRepository{col: db.Collection("refresh_tokens")}
}

func (r *TokenRepository) Create(ctx context.Context, rt *models.RefreshToken) error {
	rt.CreatedAt = time.Now().UTC()
	res, err := r.col.InsertOne(ctx, rt)
	if err != nil {
		return err
	}
	rt.ID = res.InsertedID.(bson.ObjectID)
	return nil
}

func (r *TokenRepository) FindValidByHash(ctx context.Context, tokenHash string) (*models.RefreshToken, error) {
	var rt models.RefreshToken
	err := r.col.FindOne(ctx, bson.M{
		"token_hash": tokenHash,
		"revoked":    false,
		"expires_at": bson.M{"$gt": time.Now().UTC()},
	}).Decode(&rt)
	if err != nil {
		if errors.Is(err, mongo.ErrNoDocuments) {
			return nil, ErrNotFound
		}
		return nil, err
	}
	return &rt, nil
}

func (r *TokenRepository) Revoke(ctx context.Context, id bson.ObjectID) error {
	_, err := r.col.UpdateOne(ctx, bson.M{"_id": id}, bson.M{"$set": bson.M{"revoked": true}})
	return err
}

func (r *TokenRepository) RevokeByHash(ctx context.Context, tokenHash string) error {
	_, err := r.col.UpdateOne(ctx, bson.M{"token_hash": tokenHash}, bson.M{"$set": bson.M{"revoked": true}})
	return err
}
