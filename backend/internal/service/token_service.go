package service

import (
	"context"
	"crypto/subtle"
	"errors"
	"strings"

	"patchloop-backend/internal/models"
	"patchloop-backend/internal/pkg/hash"
	"patchloop-backend/internal/pkg/random"
	"patchloop-backend/internal/repository"

	"go.mongodb.org/mongo-driver/v2/bson"
)

const (
	APITokenPrefix   = "plk_"
	apiTokenBytes    = 32
	apiTokenShownLen = 12 // "plk_" + 8 chars, shown in listings
	maxTokensPerUser = 20
)

var (
	ErrInvalidAPIToken = errors.New("invalid api token")
	ErrTokenNotFound   = errors.New("token not found")
	ErrTooManyTokens   = errors.New("too many tokens")
)

type TokenService struct {
	tokens *repository.ApiTokenRepository
	users  *repository.UserRepository
}

func NewTokenService(tokens *repository.ApiTokenRepository, users *repository.UserRepository) *TokenService {
	return &TokenService{tokens: tokens, users: users}
}

// Create returns the stored token and the plaintext value (shown once).
func (s *TokenService) Create(ctx context.Context, userID, name string) (*models.ApiToken, string, error) {
	uid, err := bson.ObjectIDFromHex(userID)
	if err != nil {
		return nil, "", ErrUserNotFound
	}
	existing, err := s.tokens.ListByUser(ctx, uid)
	if err != nil {
		return nil, "", err
	}
	if len(existing) >= maxTokensPerUser {
		return nil, "", ErrTooManyTokens
	}
	raw, err := random.String(apiTokenBytes)
	if err != nil {
		return nil, "", err
	}
	plain := APITokenPrefix + raw
	t := &models.ApiToken{
		UserID:    uid,
		Name:      name,
		TokenHash: hash.HashToken(plain),
		Prefix:    plain[:apiTokenShownLen],
	}
	if err := s.tokens.Create(ctx, t); err != nil {
		return nil, "", err
	}
	return t, plain, nil
}

func (s *TokenService) List(ctx context.Context, userID string) ([]models.ApiToken, error) {
	uid, err := bson.ObjectIDFromHex(userID)
	if err != nil {
		return nil, ErrUserNotFound
	}
	return s.tokens.ListByUser(ctx, uid)
}

func (s *TokenService) Delete(ctx context.Context, userID, tokenID string) error {
	uid, err := bson.ObjectIDFromHex(userID)
	if err != nil {
		return ErrTokenNotFound
	}
	tid, err := bson.ObjectIDFromHex(tokenID)
	if err != nil {
		return ErrTokenNotFound
	}
	if err := s.tokens.Delete(ctx, uid, tid); err != nil {
		if err == repository.ErrNotFound {
			return ErrTokenNotFound
		}
		return err
	}
	return nil
}

// Authenticate resolves a "plk_..." bearer token to its user. The lookup is
// by sha256 hash (unique index) and the stored hash is then compared in
// constant time.
func (s *TokenService) Authenticate(ctx context.Context, plain string) (userID, email string, err error) {
	if !strings.HasPrefix(plain, APITokenPrefix) || len(plain) < apiTokenShownLen+8 || len(plain) > 200 {
		return "", "", ErrInvalidAPIToken
	}
	h := hash.HashToken(plain)
	t, err := s.tokens.FindByHash(ctx, h)
	if err != nil {
		return "", "", ErrInvalidAPIToken
	}
	if subtle.ConstantTimeCompare([]byte(t.TokenHash), []byte(h)) != 1 {
		return "", "", ErrInvalidAPIToken
	}
	user, err := s.users.FindByID(ctx, t.UserID)
	if err != nil {
		return "", "", ErrInvalidAPIToken
	}
	_ = s.tokens.TouchLastUsed(ctx, t.ID)
	return user.ID.Hex(), user.Email, nil
}
