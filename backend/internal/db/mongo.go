package db

import (
	"context"
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
	d.ensureIndexes(ctx)

	return d
}

func (d *Database) ensureIndexes(ctx context.Context) {
	users := d.Database.Collection("users")
	_, err := users.Indexes().CreateOne(ctx, mongo.IndexModel{
		Keys:    bson.D{{Key: "email", Value: 1}},
		Options: options.Index().SetUnique(true),
	})
	if err != nil {
		log.Fatalf("failed to create users email index: %v", err)
	}

	otps := d.Database.Collection("otps")
	_, err = otps.Indexes().CreateOne(ctx, mongo.IndexModel{
		Keys:    bson.D{{Key: "expires_at", Value: 1}},
		Options: options.Index().SetExpireAfterSeconds(0),
	})
	if err != nil {
		log.Fatalf("failed to create otps ttl index: %v", err)
	}

	refreshTokens := d.Database.Collection("refresh_tokens")
	_, err = refreshTokens.Indexes().CreateOne(ctx, mongo.IndexModel{
		Keys:    bson.D{{Key: "expires_at", Value: 1}},
		Options: options.Index().SetExpireAfterSeconds(0),
	})
	if err != nil {
		log.Fatalf("failed to create refresh_tokens ttl index: %v", err)
	}
}

func (d *Database) Disconnect(ctx context.Context) {
	if err := d.Client.Disconnect(ctx); err != nil {
		log.Printf("error disconnecting mongo client: %v", err)
	}
}
