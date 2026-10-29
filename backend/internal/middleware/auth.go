package middleware

import (
	"context"
	"crypto/subtle"
	"net/http"
	"patchloop-backend/internal/pkg/apierr"
	"strings"

	pkgjwt "patchloop-backend/internal/pkg/jwt"

	"github.com/gin-gonic/gin"
)

const (
	AccessCookieName  = "patchloop_access_token"
	RefreshCookieName = "patchloop_refresh_token"

	ContextUserIDKey   = "userID"
	ContextEmailKey    = "email"
	ContextAuthTypeKey = "authType" // "cookie" or "token"

	apiTokenPrefix = "plk_"
)

// TokenAuthenticator resolves a personal API token ("plk_...") to a user.
type TokenAuthenticator interface {
	Authenticate(ctx context.Context, plain string) (userID, email string, err error)
}

// RequireAuth accepts the access-token cookie (browser) or, when a
// TokenAuthenticator is given, "Authorization: Bearer plk_..." (CLI).
func RequireAuth(accessSecret string, tokenAuth ...TokenAuthenticator) gin.HandlerFunc {
	var ta TokenAuthenticator
	if len(tokenAuth) > 0 {
		ta = tokenAuth[0]
	}
	return func(c *gin.Context) {
		if authz := c.GetHeader("Authorization"); authz != "" && ta != nil {
			scheme, value, ok := strings.Cut(authz, " ")
			value = strings.TrimSpace(value)
			if !ok || !strings.EqualFold(scheme, "Bearer") || !strings.HasPrefix(value, apiTokenPrefix) {
				c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "invalid authorization header", "code": apierr.Code(http.StatusUnauthorized)})
				return
			}
			userID, email, err := ta.Authenticate(c.Request.Context(), value)
			if err != nil {
				c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "invalid or revoked api token", "code": apierr.Code(http.StatusUnauthorized)})
				return
			}
			c.Set(ContextUserIDKey, userID)
			c.Set(ContextEmailKey, email)
			c.Set(ContextAuthTypeKey, "token")
			c.Next()
			return
		}

		token, err := c.Cookie(AccessCookieName)
		if err != nil || token == "" {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "not authenticated", "code": apierr.Code(http.StatusUnauthorized)})
			return
		}

		claims, err := pkgjwt.ParseAccessToken(accessSecret, token)
		if err != nil {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "invalid or expired session", "code": apierr.Code(http.StatusUnauthorized)})
			return
		}

		c.Set(ContextUserIDKey, claims.UserID)
		c.Set(ContextEmailKey, claims.Email)
		c.Set(ContextAuthTypeKey, "cookie")
		c.Next()
	}
}

// RequireAgentSecret protects /internal/* with the shared X-Agent-Secret,
// compared in constant time.
func RequireAgentSecret(secret string) gin.HandlerFunc {
	want := []byte(secret)
	return func(c *gin.Context) {
		got := []byte(c.GetHeader("X-Agent-Secret"))
		if len(want) == 0 || subtle.ConstantTimeCompare(got, want) != 1 {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "invalid agent secret", "code": apierr.Code(http.StatusUnauthorized)})
			return
		}
		c.Next()
	}
}
