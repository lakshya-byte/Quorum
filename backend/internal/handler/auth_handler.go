package handler

import (
	"net/http"
	"time"

	"patchloop-backend/internal/dto"
	"patchloop-backend/internal/middleware"
	"patchloop-backend/internal/models"
	"patchloop-backend/internal/service"

	"github.com/gin-gonic/gin"
)

type AuthHandler struct {
	auth         *service.AuthService
	accessTTL    time.Duration
	refreshTTL   time.Duration
	cookieSecure bool
	cookieDomain string
}

type AuthHandlerConfig struct {
	AccessTTLMin   int
	RefreshTTLDays int
	CookieSecure   bool
	CookieDomain   string
}

func NewAuthHandler(auth *service.AuthService, cfg AuthHandlerConfig) *AuthHandler {
	return &AuthHandler{
		auth:         auth,
		accessTTL:    time.Duration(cfg.AccessTTLMin) * time.Minute,
		refreshTTL:   time.Duration(cfg.RefreshTTLDays) * 24 * time.Hour,
		cookieSecure: cfg.CookieSecure,
		cookieDomain: cfg.CookieDomain,
	}
}

func (h *AuthHandler) setAuthCookies(c *gin.Context, pair *service.TokenPair) {
	c.SetSameSite(http.SameSiteLaxMode)
	c.SetCookie(middleware.AccessCookieName, pair.AccessToken, int(h.accessTTL.Seconds()), "/", h.cookieDomain, h.cookieSecure, true)
	c.SetCookie(middleware.RefreshCookieName, pair.RefreshToken, int(h.refreshTTL.Seconds()), "/", h.cookieDomain, h.cookieSecure, true)
}

func (h *AuthHandler) clearAuthCookies(c *gin.Context) {
	c.SetSameSite(http.SameSiteLaxMode)
	c.SetCookie(middleware.AccessCookieName, "", -1, "/", h.cookieDomain, h.cookieSecure, true)
	c.SetCookie(middleware.RefreshCookieName, "", -1, "/", h.cookieDomain, h.cookieSecure, true)
}

func toUserResponse(u *models.User) dto.UserResponse {
	return dto.UserResponse{
		ID:            u.ID.Hex(),
		Email:         u.Email,
		CompanyName:   u.CompanyName,
		EmailVerified: u.EmailVerified,
	}
}

func (h *AuthHandler) Signup(c *gin.Context) {
	var req dto.SignupRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	user, err := h.auth.Signup(c.Request.Context(), req)
	if err != nil {
		if err == service.ErrEmailTaken {
			c.JSON(http.StatusConflict, gin.H{"error": "an account with this email already exists"})
			return
		}
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to create account"})
		return
	}

	c.JSON(http.StatusCreated, gin.H{
		"message": "account created, check your email for a verification code",
		"user":    toUserResponse(user),
	})
}

func (h *AuthHandler) VerifyOTP(c *gin.Context) {
	var req dto.VerifyOTPRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	user, pair, err := h.auth.VerifyOTP(c.Request.Context(), req)
	if err != nil {
		status, msg := otpErrorStatus(err)
		c.JSON(status, gin.H{"error": msg})
		return
	}

	h.setAuthCookies(c, pair)
	c.JSON(http.StatusOK, gin.H{"user": toUserResponse(user)})
}

func (h *AuthHandler) ResendOTP(c *gin.Context) {
	var req dto.ResendOTPRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	if err := h.auth.ResendOTP(c.Request.Context(), req.Email); err != nil {
		switch err {
		case service.ErrResendCooldown:
			c.JSON(http.StatusTooManyRequests, gin.H{"error": "please wait before requesting another code"})
		case service.ErrUserNotFound:
			// Avoid leaking whether an email is registered.
			c.JSON(http.StatusOK, gin.H{"message": "if an account exists, a new code has been sent"})
		default:
			c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to resend code"})
		}
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "a new code has been sent"})
}

func (h *AuthHandler) Login(c *gin.Context) {
	var req dto.LoginRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	user, pair, err := h.auth.Login(c.Request.Context(), req)
	if err != nil {
		switch err {
		case service.ErrInvalidCredentials:
			c.JSON(http.StatusUnauthorized, gin.H{"error": "invalid email or password"})
		case service.ErrEmailNotVerified:
			c.JSON(http.StatusForbidden, gin.H{"error": "please verify your email before signing in", "code": "EMAIL_NOT_VERIFIED"})
		default:
			c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to sign in"})
		}
		return
	}

	h.setAuthCookies(c, pair)
	c.JSON(http.StatusOK, gin.H{"user": toUserResponse(user)})
}

func (h *AuthHandler) Refresh(c *gin.Context) {
	rawRefresh, err := c.Cookie(middleware.RefreshCookieName)
	if err != nil || rawRefresh == "" {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "not authenticated"})
		return
	}

	pair, err := h.auth.Refresh(c.Request.Context(), rawRefresh)
	if err != nil {
		h.clearAuthCookies(c)
		c.JSON(http.StatusUnauthorized, gin.H{"error": "session expired, please sign in again"})
		return
	}

	h.setAuthCookies(c, pair)
	c.JSON(http.StatusOK, gin.H{"message": "session refreshed"})
}

func (h *AuthHandler) Logout(c *gin.Context) {
	rawRefresh, _ := c.Cookie(middleware.RefreshCookieName)
	_ = h.auth.Logout(c.Request.Context(), rawRefresh)
	h.clearAuthCookies(c)
	c.JSON(http.StatusOK, gin.H{"message": "logged out"})
}

func (h *AuthHandler) Me(c *gin.Context) {
	userID := c.GetString(middleware.ContextUserIDKey)
	user, err := h.auth.GetUserByID(c.Request.Context(), userID)
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "user not found"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"user": toUserResponse(user)})
}

func otpErrorStatus(err error) (int, string) {
	switch err {
	case service.ErrUserNotFound:
		return http.StatusNotFound, "user not found"
	case service.ErrOTPExpired:
		return http.StatusBadRequest, "verification code expired, please request a new one"
	case service.ErrTooManyOTPAttempts:
		return http.StatusTooManyRequests, "too many attempts, please request a new code"
	case service.ErrInvalidOTP:
		return http.StatusBadRequest, "invalid verification code"
	default:
		return http.StatusInternalServerError, "failed to verify code"
	}
}
