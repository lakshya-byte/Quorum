// Package crypt encrypts small secrets (GitHub tokens, Slack webhooks) at rest
// with AES-256-GCM. The stored form is base64(nonce || ciphertext || tag).
package crypt

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"fmt"
	"io"
)

// ErrNotConfigured is returned when no key is available.
var ErrNotConfigured = errors.New("token encryption is not configured")

// Cipher seals and opens secrets. A nil *Cipher refuses to do either.
type Cipher struct {
	aead cipher.AEAD
}

// New builds a Cipher from a raw 32-byte key.
func New(key []byte) (*Cipher, error) {
	if len(key) != 32 {
		return nil, fmt.Errorf("encryption key must be 32 bytes, got %d", len(key))
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, err
	}
	aead, err := cipher.NewGCM(block)
	if err != nil {
		return nil, err
	}
	return &Cipher{aead: aead}, nil
}

// FromBase64 parses TOKEN_ENC_KEY (base64 of exactly 32 bytes).
func FromBase64(s string) (*Cipher, error) {
	var key []byte
	var err error
	for _, enc := range []*base64.Encoding{base64.StdEncoding, base64.URLEncoding, base64.RawStdEncoding, base64.RawURLEncoding} {
		if key, err = enc.DecodeString(s); err == nil {
			return New(key)
		}
	}
	return nil, errors.New("TOKEN_ENC_KEY is not valid base64")
}

// Derive builds a Cipher from an arbitrary secret (DEV_MODE fallback: the
// JWT secret). The purpose string separates it from other uses of the secret.
func Derive(secret, purpose string) (*Cipher, error) {
	sum := sha256.Sum256([]byte("patchloop|" + purpose + "|" + secret))
	return New(sum[:])
}

// Seal encrypts plaintext with a fresh random nonce.
func (c *Cipher) Seal(plaintext string) (string, error) {
	if c == nil {
		return "", ErrNotConfigured
	}
	nonce := make([]byte, c.aead.NonceSize())
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		return "", err
	}
	out := c.aead.Seal(nonce, nonce, []byte(plaintext), nil)
	return base64.StdEncoding.EncodeToString(out), nil
}

// Open decrypts a value produced by Seal.
func (c *Cipher) Open(sealed string) (string, error) {
	if c == nil {
		return "", ErrNotConfigured
	}
	raw, err := base64.StdEncoding.DecodeString(sealed)
	if err != nil || len(raw) < c.aead.NonceSize()+c.aead.Overhead() {
		return "", errors.New("stored secret is corrupt")
	}
	n := c.aead.NonceSize()
	pt, err := c.aead.Open(nil, raw[:n], raw[n:], nil)
	if err != nil {
		return "", errors.New("stored secret cannot be decrypted (wrong TOKEN_ENC_KEY?)")
	}
	return string(pt), nil
}
