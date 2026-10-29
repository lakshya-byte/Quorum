package service

import (
	"context"
	"errors"
	"fmt"
	"net/http"
)

var (
	ErrNoUserAuthorization  = errors.New(`github did not send an authorization code: enable "Request user authorization (OAuth) during installation" on the GitHub App`)
	ErrInstallationNotOwned = errors.New("that installation does not belong to your GitHub account")
)

// UserInstallations lists the installations of this App the user can access
// (GET /user/installations with the user's token). It proves that the
// installation_id in the callback URL really belongs to the signed-in user.
func (g *GitHubAPI) UserInstallations(ctx context.Context, userToken string) ([]int64, error) {
	var out struct {
		Installations []struct {
			ID int64 `json:"id"`
		} `json:"installations"`
	}
	if err := g.do(ctx, http.MethodGet, g.cfg.APIBase+"/user/installations?per_page=100", userToken, nil, &out); err != nil {
		return nil, err
	}
	ids := make([]int64, 0, len(out.Installations))
	for _, i := range out.Installations {
		ids = append(ids, i.ID)
	}
	return ids, nil
}

// verifyInstallationOwnership exchanges the callback code and checks that the
// user can access installationID. installation_id is a query parameter, i.e.
// attacker-controlled: without this check a user could claim someone else's
// installation and mint tokens for their repositories.
func (s *GitHubService) verifyInstallationOwnership(ctx context.Context, installationID int64, code string) (*UserTokens, error) {
	if code == "" {
		return nil, ErrNoUserAuthorization
	}
	tok, err := s.api.ExchangeCode(ctx, code)
	if err != nil {
		return nil, fmt.Errorf("code exchange failed: %w", err)
	}
	if installationID != 0 {
		ids, err := s.api.UserInstallations(ctx, tok.AccessToken)
		if err != nil {
			return nil, fmt.Errorf("could not verify installation: %w", err)
		}
		for _, id := range ids {
			if id == installationID {
				return tok, nil
			}
		}
		return nil, ErrInstallationNotOwned
	}
	return tok, nil
}
