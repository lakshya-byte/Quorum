package handler

import (
	"patchloop-backend/internal/middleware"
	"patchloop-backend/internal/service"

	"github.com/gin-gonic/gin"
	"github.com/newrelic/go-agent/v3/integrations/nrgin"
	"github.com/newrelic/go-agent/v3/newrelic"
)

type RouterConfig struct {
	FrontendOrigin string
	AccessSecret   string
	AgentSecret    string
	TrustedProxies []string
	NewRelic       *newrelic.Application // nil disables APM

	// Optional pieces (nil = routes not registered); keeps old tests simple.
	Runs      *RunHandler
	GitHub    *GitHubHandler
	Settings  *SettingsHandler
	Webhooks  *WebhookHandler
	Tokens    *TokenHandler
	TokenAuth middleware.TokenAuthenticator
	DevMailer *service.Mailer // non-nil only when DEV_MODE=true
}

func NewRouter(authHandler *AuthHandler, cfg RouterConfig) *gin.Engine {
	r := gin.New()
	// Only trust X-Forwarded-For from configured proxies (guest rate limits
	// are per client IP and must not be spoofable).
	_ = r.SetTrustedProxies(cfg.TrustedProxies)
	r.Use(gin.Recovery())
	// Route-named APM transactions + W3C distributed tracing (no-op when nil).
	r.Use(nrgin.MiddlewareHandlerTxnNames(cfg.NewRelic))
	r.Use(middleware.Observability())
	r.Use(middleware.CORS(cfg.FrontendOrigin))

	r.GET("/health", func(c *gin.Context) {
		c.JSON(200, gin.H{"status": "ok"})
	})

	var requireAuth gin.HandlerFunc
	if cfg.TokenAuth != nil {
		requireAuth = middleware.RequireAuth(cfg.AccessSecret, cfg.TokenAuth)
	} else {
		requireAuth = middleware.RequireAuth(cfg.AccessSecret)
	}

	api := r.Group("/api/auth")
	{
		api.POST("/signup", authHandler.Signup)
		api.POST("/verify-otp", authHandler.VerifyOTP)
		api.POST("/resend-otp", authHandler.ResendOTP)
		api.POST("/login", authHandler.Login)
		api.POST("/refresh", authHandler.Refresh)
		api.POST("/logout", authHandler.Logout)
		api.GET("/me", requireAuth, authHandler.Me)
	}

	if cfg.Runs != nil {
		authed := r.Group("/api", requireAuth)
		authed.GET("/bugs", cfg.Runs.Bugs)
		authed.POST("/runs", cfg.Runs.Create)
		authed.GET("/runs", cfg.Runs.List)
		authed.GET("/runs/:id", cfg.Runs.Get)
		authed.GET("/runs/:id/events", cfg.Runs.Events)
		authed.POST("/runs/:id/pr", cfg.Runs.OpenPR)
		authed.GET("/runs/:id/pr", cfg.Runs.GetPR)
		authed.POST("/runs/:id/merge", cfg.Runs.Merge)
		authed.POST("/runs/:id/followup", cfg.Runs.Followup)
		authed.POST("/tasks", cfg.Runs.CreateTask)

		demo := r.Group("/api/demo")
		demo.GET("/bugs", cfg.Runs.Bugs)
		demo.POST("/runs", cfg.Runs.DemoCreate)
		demo.GET("/runs/:id/events", cfg.Runs.DemoEvents)

		internal := r.Group("/internal", middleware.RequireAgentSecret(cfg.AgentSecret))
		internal.POST("/runs/:id/complete", cfg.Runs.Complete)
		if cfg.DevMailer != nil {
			internal.GET("/dev/otp", DevOTP(cfg.DevMailer))
		}
	}

	if cfg.GitHub != nil {
		gh := r.Group("/api/github")
		gh.GET("/callback", cfg.GitHub.Callback) // public: protected by the signed state
		authedGH := gh.Group("", requireAuth)
		authedGH.GET("/status", cfg.GitHub.Status)
		authedGH.GET("/connect", cfg.GitHub.Connect)
		authedGH.POST("/demo", cfg.GitHub.Demo)
		authedGH.DELETE("", cfg.GitHub.Disconnect)
		authedGH.GET("/repos", cfg.GitHub.Repos)
		authedGH.GET("/repos/:owner/:repo/branches", cfg.GitHub.Branches)
	}

	if cfg.Settings != nil {
		api2 := r.Group("/api", requireAuth)
		api2.GET("/settings/slack", cfg.Settings.GetSlack)
		api2.PUT("/settings/slack", cfg.Settings.PutSlack)
		api2.DELETE("/settings/slack", cfg.Settings.DeleteSlack)
		api2.POST("/settings/slack/test", cfg.Settings.TestSlack)
		api2.POST("/slack/link-code", cfg.Settings.LinkCode)
		api2.GET("/notifications", cfg.Settings.Notifications)
		api2.POST("/notifications/:id/read", cfg.Settings.MarkRead)
	}

	if cfg.Webhooks != nil {
		r.POST("/api/github/webhook", cfg.Webhooks.GitHub)
		r.POST("/slack/commands", cfg.Webhooks.SlackCommand)
		r.POST("/slack/events", cfg.Webhooks.SlackEvents)
		r.POST("/slack/interactions", cfg.Webhooks.SlackInteractions)
	}

	if cfg.Tokens != nil {
		tokens := r.Group("/api/tokens", requireAuth)
		tokens.POST("", cfg.Tokens.Create)
		tokens.GET("", cfg.Tokens.List)
		tokens.DELETE("/:id", cfg.Tokens.Delete)
	}

	return r
}
