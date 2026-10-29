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

type GitHubRepository struct{ col *mongo.Collection }

func NewGitHubRepository(db *mongo.Database) *GitHubRepository {
	return &GitHubRepository{col: db.Collection("github_connections")}
}

func (r *GitHubRepository) find(ctx context.Context, filter bson.M) (*models.GitHubConnection, error) {
	var c models.GitHubConnection
	if err := r.col.FindOne(ctx, filter).Decode(&c); err != nil {
		if errors.Is(err, mongo.ErrNoDocuments) {
			return nil, ErrNotFound
		}
		return nil, err
	}
	return &c, nil
}

func (r *GitHubRepository) Get(ctx context.Context, userID string) (*models.GitHubConnection, error) {
	return r.find(ctx, bson.M{"user_id": userID})
}

func (r *GitHubRepository) FindByInstallation(ctx context.Context, id int64) (*models.GitHubConnection, error) {
	return r.find(ctx, bson.M{"installation_id": id, "mode": models.GitHubModeApp})
}

func (r *GitHubRepository) FindByLogin(ctx context.Context, login string) (*models.GitHubConnection, error) {
	return r.find(ctx, bson.M{"login": login, "mode": models.GitHubModeApp})
}

// Put replaces the user's connection.
func (r *GitHubRepository) Put(ctx context.Context, c *models.GitHubConnection) error {
	if c.CreatedAt.IsZero() {
		c.CreatedAt = time.Now().UTC()
	}
	_, err := r.col.ReplaceOne(ctx, bson.M{"user_id": c.UserID}, c, options.Replace().SetUpsert(true))
	return err
}

func (r *GitHubRepository) Delete(ctx context.Context, userID string) error {
	_, err := r.col.DeleteOne(ctx, bson.M{"user_id": userID})
	return err
}
