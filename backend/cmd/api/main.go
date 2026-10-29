package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"patchloop-backend/internal/app"
	"patchloop-backend/internal/config"
	"patchloop-backend/internal/db"
	"patchloop-backend/internal/observability"

	"github.com/gin-gonic/gin"
)

func main() {
	observability.NewLogger()
	cfg := config.Load()
	if os.Getenv("GIN_MODE") == "" {
		gin.SetMode(gin.ReleaseMode)
	}
	if cfg.DevMode {
		slog.Warn("DEV_MODE=true: OTPs are kept in memory and readable via /internal/dev/otp; never use in production")
	}

	nr := observability.NewRelic(cfg.NewRelicAppName, cfg.NewRelicLicenseKey)
	defer nr.Shutdown(5 * time.Second)

	database := db.Connect(cfg.MongoURI, cfg.MongoDBName)
	defer database.Disconnect(context.Background())

	a := app.New(cfg, database.Database, nr)

	srv := &http.Server{
		Addr:              ":" + cfg.Port,
		Handler:           a.Router,
		ReadHeaderTimeout: 10 * time.Second,
		// No WriteTimeout: SSE streams are long-lived.
		IdleTimeout: 120 * time.Second,
	}

	go func() {
		slog.Info("patchloop-backend listening", "port", cfg.Port, "agent_url", cfg.AgentURL,
			"slack", cfg.SlackWebhookURL != "", "new_relic", nr != nil)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			slog.Error("server error", "error", err.Error())
			os.Exit(1)
		}
	}()

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_ = srv.Shutdown(ctx)
}
