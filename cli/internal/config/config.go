// Package config stores the CLI's API URL and token in
// ~/.config/patchloop/config.json (mode 0600). PATCHLOOP_CONFIG overrides
// the file path (used by tests).
package config

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
)

const DefaultAPI = "http://localhost:8080"

type Config struct {
	API   string `json:"api"`
	Token string `json:"token"`
}

func Path() (string, error) {
	if p := os.Getenv("PATCHLOOP_CONFIG"); p != "" {
		return p, nil
	}
	dir := os.Getenv("XDG_CONFIG_HOME")
	if dir == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			return "", err
		}
		dir = filepath.Join(home, ".config")
	}
	return filepath.Join(dir, "patchloop", "config.json"), nil
}

// Load returns the saved config (empty, not an error, if none exists).
func Load() (*Config, error) {
	p, err := Path()
	if err != nil {
		return nil, err
	}
	b, err := os.ReadFile(p)
	if errors.Is(err, os.ErrNotExist) {
		return &Config{}, nil
	}
	if err != nil {
		return nil, err
	}
	var c Config
	if err := json.Unmarshal(b, &c); err != nil {
		return nil, err
	}
	return &c, nil
}

// Save writes the config with mode 0600 (directory 0700).
func Save(c *Config) (string, error) {
	p, err := Path()
	if err != nil {
		return "", err
	}
	if err := os.MkdirAll(filepath.Dir(p), 0o700); err != nil {
		return "", err
	}
	b, err := json.MarshalIndent(c, "", "  ")
	if err != nil {
		return "", err
	}
	tmp := p + ".tmp"
	if err := os.WriteFile(tmp, b, 0o600); err != nil {
		return "", err
	}
	if err := os.Chmod(tmp, 0o600); err != nil {
		return "", err
	}
	return p, os.Rename(tmp, p)
}
