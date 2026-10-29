package db

import (
	"context"
	"fmt"
	"log"
	"time"

	"go.mongodb.org/mongo-driver/v2/bson"
	"go.mongodb.org/mongo-driver/v2/mongo"
	"go.mongodb.org/mongo-driver/v2/mongo/options"
)

type Database struct {
	Client   *mongo.Client
	Database *mongo.Database
}

func Connect(uri, dbName string) *Database {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	client, err := mongo.Connect(options.Client().ApplyURI(uri))
	if err != nil {
		log.Fatalf("failed to connect to mongo: %v", err)
	}

	if err := client.Ping(ctx, nil); err != nil {
		log.Fatalf("failed to ping mongo: %v", err)
	}

	database := client.Database(dbName)

	d := &Database{Client: client, Database: database}
	if err := EnsureIndexes(ctx, database); err != nil {
		log.Fatalf("failed to create indexes: %v", err)
	}

	return d
}

// EnsureIndexes creates every index the backend relies on. It is idempotent.
func EnsureIndexes(ctx context.Context, database *mongo.Database) error {
	type idx struct {
		col   string
		model mongo.IndexModel
	}
	indexes := []idx{
		{"users", mongo.IndexModel{Keys: bson.D{{Key: "email", Value: 1}}, Options: options.Index().SetUnique(true)}},
		{"otps", mongo.IndexModel{Keys: bson.D{{Key: "expires_at", Value: 1}}, Options: options.Index().SetExpireAfterSeconds(0)}},
		{"refresh_tokens", mongo.IndexModel{Keys: bson.D{{Key: "expires_at", Value: 1}}, Options: options.Index().SetExpireAfterSeconds(0)}},
		{"runs", mongo.IndexModel{Keys: bson.D{{Key: "user_id", Value: 1}, {Key: "created_at", Value: -1}}}},
		{"runs", mongo.IndexModel{Keys: bson.D{{Key: "agent_run_id", Value: 1}}}},
		{"apiTokens", mongo.IndexModel{Keys: bson.D{{Key: "token_hash", Value: 1}}, Options: options.Index().SetUnique(true)}},
		{"apiTokens", mongo.IndexModel{Keys: bson.D{{Key: "user_id", Value: 1}}}},
	}
	for _, i := range indexes {
		if _, err := database.Collection(i.col).Indexes().CreateOne(ctx, i.model); err != nil {
			return fmt.Errorf("index on %s: %w", i.col, err)
		}
	}
	return nil
}

func (d *Database) Disconnect(ctx context.Context) {
	if err := d.Client.Disconnect(ctx); err != nil {
		log.Printf("error disconnecting mongo client: %v", err)
	}
}
