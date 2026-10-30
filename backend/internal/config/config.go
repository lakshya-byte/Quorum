package config

import (
	"log"
	"os"
	"strconv"
	"strings"

	"github.com/joho/godotenv"
)

type Config struct {
	Port              string
	MongoURI          string
	MongoDBName       string
	JWTAccessSecret   string
	JWTRefreshSecret  string
	JWTAccessTTLMin   int
	JWTRefreshTTLDays int
	ResendAPIKey      string
	ResendFromEmail   string
	FrontendOrigin    string
	OTPTTLMin         int
	CookieSecure      bool
	CookieDomain      string

	// Clerk (browser auth). The secret key verifies session tokens and reads users.
	ClerkSecretKey string
	ClerkAPIURL    string // override for tests; defaults to https://api.clerk.com

	// Agent service (internal only).
	AgentURL          string
	AgentSharedSecret string

	// Notifications and links.
	SlackWebhookURL string
	PublicAppURL    string

	// GitHub App. Without it only the offline demo account works.
	GitHubAppID         string
	GitHubAppSlug       string
	GitHubAppPrivateKey string // PEM or base64 PEM
	GitHubClientID      string // the App's user-authorization credentials (merge as the user)
	GitHubClientSecret  string
	GitHubWebhookSecret string
	PublicURL           string // backend public base URL (setup + webhook URLs)
	FrontendURL         string // where the backend redirects after the install flow

	// Slack workspace app (all optional).
	SlackSigningSecret string
	SlackBotToken      string
	SlackAPIBase       string
	TokenEncKey        string // base64 of 32 bytes; encrypts tokens and webhooks at rest
	GitHubAPIURL       string // override for tests / GitHub Enterprise
	GitHubWebURL       string // override for tests / GitHub Enterprise

	// Limits.
	TasksPerUserPerHour   int
	DemoChecksDelaySec    int // fake CI of demo PRs is "pending" this long (merge is refused meanwhile)
	LiveRunsPerUserPerDay int
	GuestRunsPerHour      int
	TrustedProxies        []string

	// Observability (both optional; New Relic is a no-op when the key is unset).
	NewRelicLicenseKey string
	NewRelicAppName    string

	// DevMode enables test-only helpers (stored OTPs readable via
	// /internal/dev/otp). Never enabled unless DEV_MODE=true.
	DevMode bool
}

func Load() *Config {
	if err := godotenv.Load(); err != nil {
		log.Println("no .env file found, relying on process environment")
	}

	devMode := getEnv("DEV_MODE", "false") == "true"
	frontendOrigin := getEnv("FRONTEND_ORIGIN", "http://localhost:3000")

	resendKey := os.Getenv("RESEND_API_KEY")
	if resendKey == "" && !devMode {
		log.Fatalf("missing required environment variable: RESEND_API_KEY")
	}

	cfg := &Config{
		Port:              getEnv("PORT", "8080"),
		MongoURI:          getEnv("MONGO_URI", "mongodb://localhost:27017"),
		MongoDBName:       getEnv("MONGO_DB_NAME", "patchloop"),
		JWTAccessSecret:   mustGetEnv("JWT_ACCESS_SECRET"),
		JWTRefreshSecret:  mustGetEnv("JWT_REFRESH_SECRET"),
		JWTAccessTTLMin:   getEnvInt("JWT_ACCESS_TTL_MIN", 15),
		JWTRefreshTTLDays: getEnvInt("JWT_REFRESH_TTL_DAYS", 30),
		ResendAPIKey:      resendKey,
		ResendFromEmail:   getEnv("RESEND_FROM_EMAIL", "noreply@patchloop.dev"),
		FrontendOrigin:    frontendOrigin,
		OTPTTLMin:         getEnvInt("OTP_TTL_MIN", 10),
		CookieSecure:      getEnv("COOKIE_SECURE", "false") == "true",
		CookieDomain:      getEnv("COOKIE_DOMAIN", "localhost"),
		ClerkSecretKey:    mustGetEnv("CLERK_SECRET_KEY"),
		ClerkAPIURL:       os.Getenv("CLERK_API_URL"),

		AgentURL:          strings.TrimRight(getEnv("AGENT_URL", "http://localhost:8001"), "/"),
		AgentSharedSecret: mustGetEnv("AGENT_SHARED_SECRET"),

		SlackWebhookURL: os.Getenv("SLACK_WEBHOOK_URL"),
		PublicAppURL:    strings.TrimRight(getEnv("PUBLIC_APP_URL", frontendOrigin), "/"),

		GitHubAppID:         os.Getenv("GITHUB_APP_ID"),
		GitHubAppSlug:       os.Getenv("GITHUB_APP_SLUG"),
		GitHubAppPrivateKey: os.Getenv("GITHUB_APP_PRIVATE_KEY"),
		GitHubClientID:      os.Getenv("GITHUB_CLIENT_ID"),
		GitHubClientSecret:  os.Getenv("GITHUB_CLIENT_SECRET"),
		GitHubWebhookSecret: os.Getenv("GITHUB_WEBHOOK_SECRET"),
		PublicURL:           strings.TrimRight(getEnv("PUBLIC_URL", "http://localhost:"+getEnv("PORT", "8080")), "/"),
		FrontendURL:         strings.TrimRight(getEnv("FRONTEND_URL", frontendOrigin), "/"),

		SlackSigningSecret: os.Getenv("SLACK_SIGNING_SECRET"),
		SlackBotToken:      os.Getenv("SLACK_BOT_TOKEN"),
		SlackAPIBase:       os.Getenv("SLACK_API_BASE"),

		TokenEncKey:  os.Getenv("TOKEN_ENC_KEY"),
		GitHubAPIURL: strings.TrimRight(getEnv("GITHUB_API_URL", "https://api.github.com"), "/"),
		GitHubWebURL: strings.TrimRight(getEnv("GITHUB_WEB_URL", "https://github.com"), "/"),

		TasksPerUserPerHour:   getEnvInt("TASKS_PER_USER_PER_HOUR", 10),
		DemoChecksDelaySec:    getEnvInt("DEMO_CHECKS_PENDING_SEC", 4),
		LiveRunsPerUserPerDay: getEnvInt("LIVE_RUNS_PER_USER_PER_DAY", 10),
		GuestRunsPerHour:      getEnvInt("GUEST_RUNS_PER_HOUR", 3),
		TrustedProxies:        splitList(os.Getenv("TRUSTED_PROXIES")),

		NewRelicLicenseKey: os.Getenv("NEW_RELIC_LICENSE_KEY"),
		NewRelicAppName:    getEnv("NEW_RELIC_APP_NAME", "patchloop-backend"),

		DevMode: devMode,
	}

	return cfg
}

func getEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func mustGetEnv(key string) string {
	v := os.Getenv(key)
	if v == "" {
		log.Fatalf("missing required environment variable: %s", key)
	}
	return v
}

func getEnvInt(key string, fallback int) int {
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	i, err := strconv.Atoi(v)
	if err != nil {
		log.Fatalf("invalid integer environment variable %s: %v", key, err)
	}
	return i
}

func splitList(v string) []string {
	var out []string
	for _, p := range strings.Split(v, ",") {
		if p = strings.TrimSpace(p); p != "" {
			out = append(out, p)
		}
	}
	return out
}
