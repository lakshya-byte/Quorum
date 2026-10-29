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

type SlackRepository struct {
	settings *mongo.Collection
	links    *mongo.Collection
	codes    *mongo.Collection
}

func NewSlackRepository(db *mongo.Database) *SlackRepository {
	return &SlackRepository{
		settings: db.Collection("slack_settings"),
		links:    db.Collection("slack_links"),
		codes:    db.Collection("slack_link_codes"),
	}
}

func (r *SlackRepository) GetSettings(ctx context.Context, userID string) (*models.SlackSettings, error) {
	var s models.SlackSettings
	if err := r.settings.FindOne(ctx, bson.M{"user_id": userID}).Decode(&s); err != nil {
		if errors.Is(err, mongo.ErrNoDocuments) {
			return nil, ErrNotFound
		}
		return nil, err
	}
	return &s, nil
}

func (r *SlackRepository) PutSettings(ctx context.Context, s *models.SlackSettings) error {
	s.UpdatedAt = time.Now().UTC()
	_, err := r.settings.ReplaceOne(ctx, bson.M{"user_id": s.UserID}, s, options.Replace().SetUpsert(true))
	return err
}

func (r *SlackRepository) DeleteWebhook(ctx context.Context, userID string) error {
	_, err := r.settings.UpdateOne(ctx, bson.M{"user_id": userID}, bson.M{"$unset": bson.M{"enc_webhook": ""}})
	return err
}

func (r *SlackRepository) PutLink(ctx context.Context, l *models.SlackLink) error {
	l.CreatedAt = time.Now().UTC()
	// One Slack user maps to one PatchLoop user and vice versa.
	if _, err := r.links.DeleteMany(ctx, bson.M{"user_id": l.UserID}); err != nil {
		return err
	}
	_, err := r.links.ReplaceOne(ctx, bson.M{"slack_user_id": l.SlackUserID}, l, options.Replace().SetUpsert(true))
	return err
}

func (r *SlackRepository) UserForSlack(ctx context.Context, slackUserID string) (string, error) {
	var l models.SlackLink
	if err := r.links.FindOne(ctx, bson.M{"slack_user_id": slackUserID}).Decode(&l); err != nil {
		if errors.Is(err, mongo.ErrNoDocuments) {
			return "", ErrNotFound
		}
		return "", err
	}
	return l.UserID, nil
}

func (r *SlackRepository) SlackForUser(ctx context.Context, userID string) (string, error) {
	var l models.SlackLink
	if err := r.links.FindOne(ctx, bson.M{"user_id": userID}).Decode(&l); err != nil {
		if errors.Is(err, mongo.ErrNoDocuments) {
			return "", ErrNotFound
		}
		return "", err
	}
	return l.SlackUserID, nil
}

func (r *SlackRepository) PutCode(ctx context.Context, c *models.SlackLinkCode) error {
	_, err := r.codes.InsertOne(ctx, c)
	return err
}

func (r *SlackRepository) TakeCode(ctx context.Context, code string, now time.Time) (string, error) {
	var c models.SlackLinkCode
	err := r.codes.FindOneAndDelete(ctx, bson.M{"code": code, "expires_at": bson.M{"$gt": now}}).Decode(&c)
	if err != nil {
		if errors.Is(err, mongo.ErrNoDocuments) {
			return "", ErrNotFound
		}
		return "", err
	}
	return c.UserID, nil
}
