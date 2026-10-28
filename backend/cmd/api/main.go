package main

import (
	"context"
	"log"

	"patchloop-backend/internal/config"
	"patchloop-backend/internal/db"
	"patchloop-backend/internal/handler"
	"patchloop-backend/internal/repository"
	"patchloop-backend/internal/service"
)

func main() {
	cfg := config.Load()

	database := db.Connect(cfg.MongoURI, cfg.MongoDBName)
	defer database.Disconnect(context.Background())

	userRepo := repository.NewUserRepository(database.Database)
	otpRepo := repository.NewOTPRepository(database.Database)
	tokenRepo := repository.NewTokenRepository(database.Database)

	mailer := service.NewMailer(cfg.ResendAPIKey, cfg.ResendFromEmail)

	authService := service.NewAuthService(userRepo, otpRepo, tokenRepo, mailer, service.AuthServiceConfig{
		JWTAccessSecret:  cfg.JWTAccessSecret,
		JWTRefreshSecret: cfg.JWTRefreshSecret,
		AccessTTLMin:     cfg.JWTAccessTTLMin,
		RefreshTTLDays:   cfg.JWTRefreshTTLDays,
		OTPTTLMin:        cfg.OTPTTLMin,
	})

	authHandler := handler.NewAuthHandler(authService, handler.AuthHandlerConfig{
		AccessTTLMin:   cfg.JWTAccessTTLMin,
		RefreshTTLDays: cfg.JWTRefreshTTLDays,
		CookieSecure:   cfg.CookieSecure,
		CookieDomain:   cfg.CookieDomain,
	})

	router := handler.NewRouter(authHandler, handler.RouterConfig{
		FrontendOrigin: cfg.FrontendOrigin,
		AccessSecret:   cfg.JWTAccessSecret,
	})

	log.Printf("patchloop-backend listening on :%s", cfg.Port)
	if err := router.Run(":" + cfg.Port); err != nil {
		log.Fatalf("server error: %v", err)
	}
}
