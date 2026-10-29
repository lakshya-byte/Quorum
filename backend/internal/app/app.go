// Package app wires repositories, services and handlers into a gin engine.
// It is shared by cmd/api and the integration tests.
package app

import (
	"log/slog"
	"time"

	"patchloop-backend/internal/config"
	"patchloop-backend/internal/handler"
	"patchloop-backend/internal/middleware"
	"patchloop-backend/internal/pkg/crypt"
	"patchloop-backend/internal/pkg/ratelimit"
	"patchloop-backend/internal/repository"
	"patchloop-backend/internal/service"

	"github.com/gin-gonic/gin"
	"github.com/newrelic/go-agent/v3/newrelic"
	"go.mongodb.org/mongo-driver/v2/mongo"
)

type App struct {
	Router        *gin.Engine
	Mailer        *service.Mailer
	Runs          *service.RunService
	GitHub        *service.GitHubService
	GitHubWebhook *service.GitHubWebhook
	Slack         *service.SlackApp
	SlackSettings *service.SlackSettingsService
	Merge         *service.MergeService
}

// Stores are the persistence interfaces; Mongo-backed in production,
// in-memory in tests.
type Stores struct {
	Runs          service.RunStore
	GitHub        service.GitHubStore
	Slack         service.SlackStore
	Notifications service.NotificationStore
	Dedupe        service.DedupeStore
}

// Auth carries what the auth routes need; tests may substitute a fake
// TokenAuth so they do not need accounts.
type Auth struct {
	Handler   *handler.AuthHandler
	TokenAuth middleware.TokenAuthenticator
	Mailer    *service.Mailer
}

// New wires the production app on MongoDB.
func New(cfg *config.Config, database *mongo.Database, nr *newrelic.Application) *App {
	userRepo := repository.NewUserRepository(database)
	otpRepo := repository.NewOTPRepository(database)
	tokenRepo := repository.NewTokenRepository(database)
	apiTokenRepo := repository.NewApiTokenRepository(database)

	mailer := service.NewMailerWithOptions(cfg.ResendAPIKey, cfg.ResendFromEmail, cfg.DevMode)
	authService := service.NewAuthService(userRepo, otpRepo, tokenRepo, mailer, service.AuthServiceConfig{
		JWTAccessSecret:  cfg.JWTAccessSecret,
		JWTRefreshSecret: cfg.JWTRefreshSecret,
		AccessTTLMin:     cfg.JWTAccessTTLMin,
		RefreshTTLDays:   cfg.JWTRefreshTTLDays,
		OTPTTLMin:        cfg.OTPTTLMin,
	})
	tokenService := service.NewTokenService(apiTokenRepo, userRepo)
	authHandler := handler.NewAuthHandler(authService, handler.AuthHandlerConfig{
		AccessTTLMin:   cfg.JWTAccessTTLMin,
		RefreshTTLDays: cfg.JWTRefreshTTLDays,
		CookieSecure:   cfg.CookieSecure,
		CookieDomain:   cfg.CookieDomain,
	})
	a := Build(cfg, Stores{
		Runs:          repository.NewRunRepository(database),
		GitHub:        repository.NewGitHubRepository(database),
		Slack:         repository.NewSlackRepository(database),
		Notifications: repository.NewNotificationRepository(database),
		Dedupe:        repository.NewDedupeRepository(database),
	}, Auth{Handler: authHandler, TokenAuth: middleware.TokenAuthenticator(tokenService), Mailer: mailer}, nr, handler.NewTokenHandler(tokenService))
	return a
}

// cipherFor builds the at-rest cipher. TOKEN_ENC_KEY wins; in DEV_MODE a key
// is derived from the JWT secret; otherwise there is no cipher and storing
// tokens or webhooks is refused (503) while the rest keeps working.
func cipherFor(cfg *config.Config) *crypt.Cipher {
	if cfg.TokenEncKey != "" {
		c, err := crypt.FromBase64(cfg.TokenEncKey)
		if err != nil {
			slog.Error("TOKEN_ENC_KEY is invalid: encrypted storage disabled", "error", err.Error())
			return nil
		}
		return c
	}
	if cfg.DevMode {
		c, _ := crypt.Derive(cfg.JWTAccessSecret, "token-enc")
		return c
	}
	slog.Warn("TOKEN_ENC_KEY is not set: GitHub tokens and Slack webhooks cannot be stored")
	return nil
}

// Build wires everything above the persistence layer.
func Build(cfg *config.Config, st Stores, auth Auth, nr *newrelic.Application, tokens *handler.TokenHandler) *App {
	cipher := cipherFor(cfg)

	api, err := service.NewGitHubAPI(service.GitHubAppConfig{
		AppID: cfg.GitHubAppID, Slug: cfg.GitHubAppSlug, PrivateKey: cfg.GitHubAppPrivateKey,
		ClientID: cfg.GitHubClientID, ClientSecret: cfg.GitHubClientSecret,
		APIBase: cfg.GitHubAPIURL, WebBase: cfg.GitHubWebURL,
	})
	if err != nil {
		slog.Error("github app disabled", "error", err.Error())
		api, _ = service.NewGitHubAPI(service.GitHubAppConfig{APIBase: cfg.GitHubAPIURL, WebBase: cfg.GitHubWebURL})
	}
	github := service.NewGitHubService(api, st.GitHub, cipher, cfg.JWTAccessSecret)

	agent := service.NewAgentClient(cfg.AgentURL, cfg.AgentSharedSecret)
	notifier := service.NewSlackNotifier(cfg.SlackWebhookURL, cfg.PublicAppURL)
	runService := service.NewRunService(st.Runs, agent, notifier, nr, service.RunServiceConfig{
		LiveRunsPerUserPerDay: cfg.LiveRunsPerUserPerDay,
		PublicAppURL:          cfg.PublicAppURL,
	})
	runService.SetGitHub(github)
	runService.SetNotifications(st.Notifications)

	slackSettings := service.NewSlackSettingsService(st.Slack, cipher, notifier, cfg.DevMode)
	runService.SetUserWebhook(slackSettings.Webhook)

	mergeService := service.NewMergeService(github, st.Runs, runService)
	mergeService.DemoChecksDelay = time.Duration(cfg.DemoChecksDelaySec) * time.Second
	slackAPI := service.NewSlackAPI(cfg.SlackBotToken, cfg.SlackAPIBase)
	slackApp := service.NewSlackApp(cfg.SlackSigningSecret, slackAPI, slackSettings, runService, mergeService, github, st.Dedupe)
	runService.SetObserver(slackApp)

	taskPerHour := cfg.TasksPerUserPerHour
	if taskPerHour <= 0 {
		taskPerHour = 10
	}
	taskLimiter := ratelimit.New(taskPerHour, time.Hour)
	// Issue/comment-triggered runs share the same per-user budget.
	ghWebhook := service.NewGitHubWebhook(cfg.GitHubWebhookSecret, github, runService, st.Dedupe)
	ghWebhook.AllowTask = func(userID string) bool { ok, _ := taskLimiter.Allow(userID); return ok }

	runHandler := handler.NewRunHandler(runService, handler.RunHandlerConfig{
		GuestLimiter: ratelimit.New(cfg.GuestRunsPerHour, time.Hour),
		TaskLimiter:  taskLimiter,
		Merge:        mergeService,
		IPHashSalt:   cfg.AgentSharedSecret,
	})

	var devMailer *service.Mailer
	if cfg.DevMode {
		devMailer = auth.Mailer
	}

	router := handler.NewRouter(auth.Handler, handler.RouterConfig{
		FrontendOrigin: cfg.FrontendOrigin,
		AccessSecret:   cfg.JWTAccessSecret,
		AgentSecret:    cfg.AgentSharedSecret,
		TrustedProxies: cfg.TrustedProxies,
		NewRelic:       nr,
		Runs:           runHandler,
		GitHub:         handler.NewGitHubHandler(github, cfg.FrontendURL),
		Settings:       handler.NewSettingsHandler(slackSettings, st.Notifications, cfg.SlackSigningSecret != "" && slackAPI.Enabled()),
		Webhooks:       handler.NewWebhookHandler(ghWebhook, slackApp),
		Tokens:         tokens,
		TokenAuth:      auth.TokenAuth,
		DevMailer:      devMailer,
	})

	return &App{Router: router, Mailer: auth.Mailer, Runs: runService, GitHub: github, GitHubWebhook: ghWebhook,
		Slack: slackApp, SlackSettings: slackSettings, Merge: mergeService}
}
