package handler

import (
	"patchloop-backend/internal/middleware"

	"github.com/gin-gonic/gin"
)

type RouterConfig struct {
	FrontendOrigin string
	AccessSecret   string
}

func NewRouter(authHandler *AuthHandler, cfg RouterConfig) *gin.Engine {
	r := gin.New()
	r.Use(gin.Logger(), gin.Recovery())
	r.Use(middleware.CORS(cfg.FrontendOrigin))

	r.GET("/health", func(c *gin.Context) {
		c.JSON(200, gin.H{"status": "ok"})
	})

	api := r.Group("/api/auth")
	{
		api.POST("/signup", authHandler.Signup)
		api.POST("/verify-otp", authHandler.VerifyOTP)
		api.POST("/resend-otp", authHandler.ResendOTP)
		api.POST("/login", authHandler.Login)
		api.POST("/refresh", authHandler.Refresh)
		api.POST("/logout", authHandler.Logout)
		api.GET("/me", middleware.RequireAuth(cfg.AccessSecret), authHandler.Me)
	}

	return r
}
