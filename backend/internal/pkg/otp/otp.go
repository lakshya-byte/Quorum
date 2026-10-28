package otp

import (
	"crypto/rand"
	"fmt"
	"math/big"
)

// Generate returns a 6-digit numeric OTP code, zero-padded.
func Generate() (string, error) {
	max := big.NewInt(1000000)
	n, err := rand.Int(rand.Reader, max)
	if err != nil {
		return "", err
	}
	return fmt.Sprintf("%06d", n.Int64()), nil
}
