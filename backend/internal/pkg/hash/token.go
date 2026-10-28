package hash

import (
	"crypto/sha256"
	"encoding/hex"
)

// HashToken is used for high-entropy random tokens (refresh tokens) where a
// fast, deterministic hash is sufficient — unlike passwords/OTPs these are
// not brute-forceable within their lifetime.
func HashToken(token string) string {
	sum := sha256.Sum256([]byte(token))
	return hex.EncodeToString(sum[:])
}
