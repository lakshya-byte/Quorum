package middleware

import (
	"context"
	"crypto/subtle"
	"net/http"
	"patchloop-backend/internal/pkg/apierr"
	"strings"

	// pkgjwt "patchloop-backend/internal/pkg/jwt"

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

// RequireAuth accepts "Authorization: Bearer plk_..." (CLI, via tokenAuth) or
// a Clerk session token (via clerkAuth): in the Authorization header, or in
// ?token= for EventSource, which cannot set headers. Either may be nil.
func RequireAuth(tokenAuth, clerkAuth TokenAuthenticator) gin.HandlerFunc {
	deny := func(c *gin.Context, msg string) {
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": msg, "code": apierr.Code(http.StatusUnauthorized)})
	}
	return func(c *gin.Context) {
		bearer := ""
		if authz := c.GetHeader("Authorization"); authz != "" {
			scheme, value, ok := strings.Cut(authz, " ")
			if !ok || !strings.EqualFold(scheme, "Bearer") {
				deny(c, "invalid authorization header")
				return
			}
			bearer = strings.TrimSpace(value)
		} else {
			bearer = c.Query("token")
		}
		if bearer == "" {
			deny(c, "not authenticated")
			return
		}

		var (
			userID, email string
			err           error
			authType      string
		)
		switch {
		case strings.HasPrefix(bearer, apiTokenPrefix) && tokenAuth != nil:
			authType = "token"
			userID, email, err = tokenAuth.Authenticate(c.Request.Context(), bearer)
		case clerkAuth != nil && !strings.HasPrefix(bearer, apiTokenPrefix):
			authType = "clerk"
			userID, email, err = clerkAuth.Authenticate(c.Request.Context(), bearer)
		default:
			deny(c, "invalid authorization header")
			return
		}
		if err != nil {
			deny(c, "invalid or expired session")
			return
		}
		c.Set(ContextUserIDKey, userID)
		c.Set(ContextEmailKey, email)
		c.Set(ContextAuthTypeKey, authType)
		c.Next()
	}
}

/* Previous cookie-based RequireAuth (replaced by Clerk), kept for reference:

func RequireAuth(accessSecret string, tokenAuth ...TokenAuthenticator) gin.HandlerFunc {
	... plk_ branch as above, then:
		token, err := c.Cookie(AccessCookieName)
		if err != nil || token == "" { 401 "not authenticated" }
		claims, err := pkgjwt.ParseAccessToken(accessSecret, token)
		if err != nil { 401 "invalid or expired session" }
		c.Set(ContextUserIDKey, claims.UserID)
		c.Set(ContextEmailKey, claims.Email)
		c.Set(ContextAuthTypeKey, "cookie")
}
*/

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
