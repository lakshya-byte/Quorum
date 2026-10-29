// Package clerk verifies Clerk session JWTs and reads users from Clerk's
// Backend API. Only the secret key is needed: signing keys come from
// GET /v1/jwks.
package clerk

import (
	"context"
	"crypto/rsa"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

const defaultAPIBase = "https://api.clerk.com"

type Client struct {
	secret  string
	apiBase string
	http    *http.Client

	mu        sync.Mutex
	keys      map[string]*rsa.PublicKey
	lastFetch time.Time
}

func New(secretKey, apiBase string) *Client {
	if apiBase == "" {
		apiBase = defaultAPIBase
	}
	return &Client{secret: secretKey, apiBase: strings.TrimRight(apiBase, "/"), http: &http.Client{Timeout: 10 * time.Second}}
}

// Verify checks signature + expiry of a Clerk session token and returns the
// Clerk user id (the "sub" claim) and the claims.
func (c *Client) Verify(ctx context.Context, token string) (string, jwt.MapClaims, error) {
	claims := jwt.MapClaims{}
	_, err := jwt.ParseWithClaims(token, claims, func(t *jwt.Token) (any, error) {
		kid, _ := t.Header["kid"].(string)
		return c.key(ctx, kid)
	}, jwt.WithValidMethods([]string{"RS256"}), jwt.WithExpirationRequired())
	if err != nil {
		return "", nil, err
	}
	sub, _ := claims["sub"].(string)
	if sub == "" {
		return "", nil, errors.New("clerk token has no sub")
	}
	return sub, claims, nil
}

func (c *Client) key(ctx context.Context, kid string) (*rsa.PublicKey, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if k, ok := c.keys[kid]; ok {
		return k, nil
	}
	// Unknown kid: refetch, but at most once a minute so junk tokens can't hammer Clerk.
	if time.Since(c.lastFetch) < time.Minute && c.keys != nil {
		return nil, fmt.Errorf("unknown signing key %q", kid)
	}
	var set struct {
		Keys []struct {
			Kid string `json:"kid"`
			N   string `json:"n"`
			E   string `json:"e"`
		} `json:"keys"`
	}
	if err := c.get(ctx, "/v1/jwks", &set); err != nil {
		return nil, err
	}
	c.lastFetch = time.Now()
	c.keys = map[string]*rsa.PublicKey{}
	for _, k := range set.Keys {
		n, err1 := base64.RawURLEncoding.DecodeString(k.N)
		e, err2 := base64.RawURLEncoding.DecodeString(k.E)
		if err1 != nil || err2 != nil {
			continue
		}
		c.keys[k.Kid] = &rsa.PublicKey{N: new(big.Int).SetBytes(n), E: int(new(big.Int).SetBytes(e).Int64())}
	}
	if k, ok := c.keys[kid]; ok {
		return k, nil
	}
	return nil, fmt.Errorf("unknown signing key %q", kid)
}

// User is the slice of a Clerk user PatchLoop needs.
type User struct {
	Email string
	Name  string
}

// GetUser fetches a user's primary email and name from the Backend API.
func (c *Client) GetUser(ctx context.Context, id string) (*User, error) {
	var u struct {
		FirstName  string `json:"first_name"`
		LastName   string `json:"last_name"`
		PrimaryID  string `json:"primary_email_address_id"`
		EmailAddrs []struct {
			ID    string `json:"id"`
			Email string `json:"email_address"`
		} `json:"email_addresses"`
	}
	if err := c.get(ctx, "/v1/users/"+id, &u); err != nil {
		return nil, err
	}
	out := &User{Name: strings.TrimSpace(u.FirstName + " " + u.LastName)}
	for _, e := range u.EmailAddrs {
		if e.ID == u.PrimaryID || out.Email == "" {
			out.Email = strings.ToLower(e.Email)
		}
	}
	if out.Email == "" {
		return nil, errors.New("clerk user has no email")
	}
	return out, nil
}

func (c *Client) get(ctx context.Context, path string, out any) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.apiBase+path, nil)
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+c.secret)
	res, err := c.http.Do(req)
	if err != nil {
		return err
	}
	defer res.Body.Close()
	if res.StatusCode != http.StatusOK {
		return fmt.Errorf("clerk api %s: status %d", path, res.StatusCode)
	}
	return json.NewDecoder(res.Body).Decode(out)
}
