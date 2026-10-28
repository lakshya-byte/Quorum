package service

import "errors"

var (
	ErrEmailTaken          = errors.New("email already registered")
	ErrInvalidCredentials  = errors.New("invalid email or password")
	ErrEmailNotVerified    = errors.New("email not verified")
	ErrInvalidOTP          = errors.New("invalid verification code")
	ErrOTPExpired          = errors.New("verification code expired or not found")
	ErrTooManyOTPAttempts  = errors.New("too many attempts, request a new code")
	ErrResendCooldown      = errors.New("please wait before requesting another code")
	ErrInvalidRefreshToken = errors.New("invalid or expired session")
	ErrUserNotFound        = errors.New("user not found")
)
