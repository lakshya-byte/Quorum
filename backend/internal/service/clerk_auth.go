package service

import (
	"context"
	"errors"

	"patchloop-backend/internal/models"
	"patchloop-backend/internal/pkg/clerk"
	"patchloop-backend/internal/repository"
)

// ClerkAuth turns a Clerk session token into a local PatchLoop user, so
// every downstream handler keeps using the Mongo user id.
type ClerkAuth struct {
	clerk *clerk.Client
	users *repository.UserRepository
}

func NewClerkAuth(c *clerk.Client, users *repository.UserRepository) *ClerkAuth {
	return &ClerkAuth{clerk: c, users: users}
}

// Authenticate implements middleware.TokenAuthenticator.
func (a *ClerkAuth) Authenticate(ctx context.Context, token string) (string, string, error) {
	clerkID, _, err := a.clerk.Verify(ctx, token)
	if err != nil {
		return "", "", err
	}
	user, err := a.users.FindByClerkID(ctx, clerkID)
	if errors.Is(err, repository.ErrNotFound) {
		user, err = a.provision(ctx, clerkID)
	}
	if err != nil {
		return "", "", err
	}
	return user.ID.Hex(), user.Email, nil
}

// provision runs on a Clerk user's first request: link an existing account
// with the same email, else create one.
func (a *ClerkAuth) provision(ctx context.Context, clerkID string) (*models.User, error) {
	cu, err := a.clerk.GetUser(ctx, clerkID)
	if err != nil {
		return nil, err
	}
	existing, err := a.users.FindByEmail(ctx, cu.Email)
	if err == nil {
		if err := a.users.SetClerkID(ctx, existing.ID, clerkID); err != nil {
			return nil, err
		}
		existing.ClerkID = clerkID
		return existing, nil
	}
	if !errors.Is(err, repository.ErrNotFound) {
		return nil, err
	}
	user := &models.User{Email: cu.Email, CompanyName: cu.Name, ClerkID: clerkID, EmailVerified: true}
	if err := a.users.Create(ctx, user); err != nil {
		if errors.Is(err, repository.ErrDuplicateEmail) { // concurrent first requests
			return a.users.FindByClerkID(ctx, clerkID)
		}
		return nil, err
	}
	return user, nil
}
