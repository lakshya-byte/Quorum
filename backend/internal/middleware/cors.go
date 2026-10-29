package middleware

import (
	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
)

func CORS(frontendOrigin string) gin.HandlerFunc {
	cfg := cors.Config{
		AllowOrigins:     []string{frontendOrigin},
		AllowMethods:     []string{"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"},
		AllowHeaders:     []string{"Origin", "Content-Type", "Accept", "Authorization", "traceparent", "tracestate", "Last-Event-ID"},
		ExposeHeaders:    []string{"Retry-After"},
		AllowCredentials: true,
	}
	return cors.New(cfg)
}
