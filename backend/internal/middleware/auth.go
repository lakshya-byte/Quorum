package middleware

import (
	"net/http"

	pkgjwt "patchloop-backend/internal/pkg/jwt"

	"github.com/gin-gonic/gin"
)

const (
	AccessCookieName  = "patchloop_access_token"
	RefreshCookieName = "patchloop_refresh_token"

	ContextUserIDKey = "userID"
	ContextEmailKey  = "email"
)

func RequireAuth(accessSecret string) gin.HandlerFunc {
	return func(c *gin.Context) {
		token, err := c.Cookie(AccessCookieName)
		if err != nil || token == "" {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "not authenticated"})
			return
		}

		claims, err := pkgjwt.ParseAccessToken(accessSecret, token)
		if err != nil {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "invalid or expired session"})
			return
		}

		c.Set(ContextUserIDKey, claims.UserID)
		c.Set(ContextEmailKey, claims.Email)
		c.Next()
	}
}
