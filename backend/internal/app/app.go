// Package app wires repositories, services and handlers into a gin engine.
// It is shared by cmd/api and the integration tests.
package app

import (
	"time"

	"patchloop-backend/internal/config"
	"patchloop-backend/internal/handler"
	"patchloop-backend/internal/middleware"
	"patchloop-backend/internal/pkg/ratelimit"
	"patchloop-backend/internal/repository"
	"patchloop-backend/internal/service"

	"github.com/gin-gonic/gin"
	"github.com/newrelic/go-agent/v3/newrelic"
	"go.mongodb.org/mongo-driver/v2/mongo"
)

type App struct {
	Router *gin.Engine
	Mailer *service.Mailer
	Runs   *service.RunService
}

func New(cfg *config.Config, database *mongo.Database, nr *newrelic.Application) *App {
	userRepo := repository.NewUserRepository(database)
	otpRepo := repository.NewOTPRepository(database)
	tokenRepo := repository.NewTokenRepository(database)
	runRepo := repository.NewRunRepository(database)
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
	agent := service.NewAgentClient(cfg.AgentURL, cfg.AgentSharedSecret)
	slack := service.NewSlackNotifier(cfg.SlackWebhookURL, cfg.PublicAppURL)
	runService := service.NewRunService(runRepo, agent, slack, nr, service.RunServiceConfig{
		LiveRunsPerUserPerDay: cfg.LiveRunsPerUserPerDay,
	})

	authHandler := handler.NewAuthHandler(authService, handler.AuthHandlerConfig{
		AccessTTLMin:   cfg.JWTAccessTTLMin,
		RefreshTTLDays: cfg.JWTRefreshTTLDays,
		CookieSecure:   cfg.CookieSecure,
		CookieDomain:   cfg.CookieDomain,
	})
	runHandler := handler.NewRunHandler(runService, handler.RunHandlerConfig{
		GuestLimiter: ratelimit.New(cfg.GuestRunsPerHour, time.Hour),
		IPHashSalt:   cfg.AgentSharedSecret,
	})

	var devMailer *service.Mailer
	if cfg.DevMode {
		devMailer = mailer
	}

	router := handler.NewRouter(authHandler, handler.RouterConfig{
		FrontendOrigin: cfg.FrontendOrigin,
		AccessSecret:   cfg.JWTAccessSecret,
		AgentSecret:    cfg.AgentSharedSecret,
		TrustedProxies: cfg.TrustedProxies,
		NewRelic:       nr,
		Runs:           runHandler,
		Tokens:         handler.NewTokenHandler(tokenService),
		TokenAuth:      middleware.TokenAuthenticator(tokenService),
		DevMailer:      devMailer,
	})

	return &App{Router: router, Mailer: mailer, Runs: runService}
}
