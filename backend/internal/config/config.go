package config

import (
	"log"
	"os"
	"strconv"

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
}

func Load() *Config {
	if err := godotenv.Load(); err != nil {
		log.Println("no .env file found, relying on process environment")
	}

	cfg := &Config{
		Port:              getEnv("PORT", "8080"),
		MongoURI:          getEnv("MONGO_URI", "mongodb://localhost:27017"),
		MongoDBName:       getEnv("MONGO_DB_NAME", "patchloop"),
		JWTAccessSecret:   mustGetEnv("JWT_ACCESS_SECRET"),
		JWTRefreshSecret:  mustGetEnv("JWT_REFRESH_SECRET"),
		JWTAccessTTLMin:   getEnvInt("JWT_ACCESS_TTL_MIN", 15),
		JWTRefreshTTLDays: getEnvInt("JWT_REFRESH_TTL_DAYS", 30),
		ResendAPIKey:      mustGetEnv("RESEND_API_KEY"),
		ResendFromEmail:   getEnv("RESEND_FROM_EMAIL", "noreply@patchloop.dev"),
		FrontendOrigin:    getEnv("FRONTEND_ORIGIN", "http://localhost:3000"),
		OTPTTLMin:         getEnvInt("OTP_TTL_MIN", 10),
		CookieSecure:      getEnv("COOKIE_SECURE", "false") == "true",
		CookieDomain:      getEnv("COOKIE_DOMAIN", "localhost"),
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
