package handler

import (
	"errors"
	"net/http"

	"patchloop-backend/internal/dto"
	"patchloop-backend/internal/middleware"
	"patchloop-backend/internal/service"

	"github.com/gin-gonic/gin"
)

type TokenHandler struct {
	tokens *service.TokenService
}

func NewTokenHandler(tokens *service.TokenService) *TokenHandler {
	return &TokenHandler{tokens: tokens}
}

// Create: POST /api/tokens {name} -> {token} (plaintext shown once).
func (h *TokenHandler) Create(c *gin.Context) {
	var req dto.CreateTokenRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "name is required (max 100 characters)"})
		return
	}
	t, plain, err := h.tokens.Create(c.Request.Context(), c.GetString(middleware.ContextUserIDKey), req.Name)
	if err != nil {
		if errors.Is(err, service.ErrTooManyTokens) {
			c.JSON(http.StatusConflict, gin.H{"error": "token limit reached, delete an old token first"})
			return
		}
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to create token"})
		return
	}
	c.JSON(http.StatusCreated, gin.H{"token": plain, "id": t.ID.Hex(), "name": t.Name, "prefix": t.Prefix, "createdAt": t.CreatedAt})
}

// List: GET /api/tokens (never returns secrets or hashes).
func (h *TokenHandler) List(c *gin.Context) {
	tokens, err := h.tokens.List(c.Request.Context(), c.GetString(middleware.ContextUserIDKey))
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to list tokens"})
		return
	}
	c.JSON(http.StatusOK, tokens)
}

// Delete: DELETE /api/tokens/:id.
func (h *TokenHandler) Delete(c *gin.Context) {
	err := h.tokens.Delete(c.Request.Context(), c.GetString(middleware.ContextUserIDKey), c.Param("id"))
	if err != nil {
		if errors.Is(err, service.ErrTokenNotFound) {
			c.JSON(http.StatusNotFound, gin.H{"error": "token not found"})
			return
		}
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to delete token"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "token deleted"})
}

// DevOTP: GET /internal/dev/otp?email=... — only registered when DEV_MODE=true.
func DevOTP(mailer *service.Mailer) gin.HandlerFunc {
	return func(c *gin.Context) {
		code, ok := mailer.LastOTP(c.Query("email"))
		if !ok {
			c.JSON(http.StatusNotFound, gin.H{"error": "no code for that email"})
			return
		}
		c.JSON(http.StatusOK, gin.H{"code": code})
	}
}
