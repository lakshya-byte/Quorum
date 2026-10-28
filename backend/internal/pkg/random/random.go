package random

import (
	"crypto/rand"
	"encoding/base64"
)

// String returns a URL-safe, base64-encoded random string generated from
// n bytes of crypto/rand entropy. Used for opaque refresh tokens.
func String(n int) (string, error) {
	buf := make([]byte, n)
	if _, err := rand.Read(buf); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(buf), nil
}
