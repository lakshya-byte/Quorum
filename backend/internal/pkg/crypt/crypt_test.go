package crypt

import (
	"bytes"
	"encoding/base64"
	"strings"
	"testing"
)

func TestRoundTripAndRandomNonce(t *testing.T) {
	c, err := Derive("secret", "test")
	if err != nil {
		t.Fatal(err)
	}
	a, _ := c.Seal("ghp_supersecret")
	b, _ := c.Seal("ghp_supersecret")
	if a == b {
		t.Fatal("nonce reuse: identical ciphertexts")
	}
	if strings.Contains(a, "ghp_") {
		t.Fatal("plaintext visible in ciphertext")
	}
	got, err := c.Open(a)
	if err != nil || got != "ghp_supersecret" {
		t.Fatalf("open: %q %v", got, err)
	}
}

func TestTamperAndWrongKeyFail(t *testing.T) {
	c, _ := Derive("secret", "test")
	other, _ := Derive("other", "test")
	s, _ := c.Seal("x")
	if _, err := other.Open(s); err == nil {
		t.Fatal("wrong key opened the secret")
	}
	raw, _ := base64.StdEncoding.DecodeString(s)
	raw[len(raw)-1] ^= 1
	if _, err := c.Open(base64.StdEncoding.EncodeToString(raw)); err == nil {
		t.Fatal("tampered ciphertext opened")
	}
	if _, err := c.Open("not base64!"); err == nil {
		t.Fatal("garbage opened")
	}
}

func TestNilCipherRefuses(t *testing.T) {
	var c *Cipher
	if _, err := c.Seal("x"); err != ErrNotConfigured {
		t.Fatalf("seal: %v", err)
	}
	if _, err := c.Open("x"); err != ErrNotConfigured {
		t.Fatalf("open: %v", err)
	}
}

func TestFromBase64(t *testing.T) {
	key := bytes.Repeat([]byte{7}, 32)
	if _, err := FromBase64(base64.StdEncoding.EncodeToString(key)); err != nil {
		t.Fatal(err)
	}
	if _, err := FromBase64(base64.StdEncoding.EncodeToString(key[:16])); err == nil {
		t.Fatal("short key accepted")
	}
	if _, err := FromBase64("%%%"); err == nil {
		t.Fatal("bad base64 accepted")
	}
}
