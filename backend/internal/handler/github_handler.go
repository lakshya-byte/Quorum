package handler

import (
	"errors"
	"log/slog"
	"net/http"
	"net/url"
	"strconv"

	"patchloop-backend/internal/middleware"
	"patchloop-backend/internal/service"

	"github.com/gin-gonic/gin"
)

type GitHubHandler struct {
	gh          *service.GitHubService
	frontendURL string
}

func NewGitHubHandler(gh *service.GitHubService, frontendURL string) *GitHubHandler {
	return &GitHubHandler{gh: gh, frontendURL: frontendURL}
}

func uid(c *gin.Context) string { return c.GetString(middleware.ContextUserIDKey) }

// Status: GET /api/github/status.
func (h *GitHubHandler) Status(c *gin.Context) {
	st, err := h.gh.Status(c.Request.Context(), uid(c))
	if err != nil {
		serviceError(c, err)
		return
	}
	c.JSON(http.StatusOK, st)
}

// Connect: GET /api/github/connect -> {url} of the GitHub App install page.
func (h *GitHubHandler) Connect(c *gin.Context) {
	u, err := h.gh.ConnectURL(uid(c))
	if err != nil {
		serviceError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"url": u})
}

func (h *GitHubHandler) redirect(c *gin.Context, q url.Values) {
	c.Redirect(http.StatusFound, h.frontendURL+"/integrations?"+q.Encode())
}

// Callback: GET /api/github/callback (public; protected by the signed state).
func (h *GitHubHandler) Callback(c *gin.Context) {
	id, _ := strconv.ParseInt(c.Query("installation_id"), 10, 64)
	err := h.gh.HandleCallback(c.Request.Context(), id, c.Query("code"), c.Query("state"))
	if err != nil {
		reason := "failed"
		switch {
		case errors.Is(err, service.ErrBadState):
			reason = "invalid_state"
		case err.Error() == "github did not send an installation id":
			reason = "no_installation"
		case errors.Is(err, service.ErrNoUserAuthorization):
			reason = "no_authorization"
		case errors.Is(err, service.ErrInstallationNotOwned):
			reason = "installation_not_yours"
		}
		// The error text may come from GitHub; log it, never put it in the URL.
		slog.Warn("github callback failed", "reason", reason, "error", err.Error())
		h.redirect(c, url.Values{"github": {"error"}, "reason": {reason}})
		return
	}
	h.redirect(c, url.Values{"github": {"connected"}})
}

// Demo: POST /api/github/demo.
func (h *GitHubHandler) Demo(c *gin.Context) {
	if err := h.gh.ConnectDemo(c.Request.Context(), uid(c)); err != nil {
		apiError(c, http.StatusInternalServerError, "internal", "failed to connect the demo account")
		return
	}
	c.JSON(http.StatusOK, gin.H{"connected": true, "mode": "demo", "login": "demo-user"})
}

// Disconnect: DELETE /api/github.
func (h *GitHubHandler) Disconnect(c *gin.Context) {
	if err := h.gh.Disconnect(c.Request.Context(), uid(c)); err != nil {
		apiError(c, http.StatusInternalServerError, "internal", "failed to disconnect")
		return
	}
	c.JSON(http.StatusOK, gin.H{"connected": false})
}

// Repos: GET /api/github/repos?q=.
func (h *GitHubHandler) Repos(c *gin.Context) {
	repos, err := h.gh.Repos(c.Request.Context(), uid(c), c.Query("q"))
	if err != nil {
		serviceError(c, err)
		return
	}
	if repos == nil {
		repos = []service.GitHubRepo{}
	}
	c.JSON(http.StatusOK, repos)
}

// Branches: GET /api/github/repos/:owner/:repo/branches.
func (h *GitHubHandler) Branches(c *gin.Context) {
	bs, err := h.gh.Branches(c.Request.Context(), uid(c), c.Param("owner"), c.Param("repo"))
	if err != nil {
		if err.Error() == "invalid repository name" {
			apiError(c, http.StatusBadRequest, "bad_request", err.Error())
			return
		}
		serviceError(c, err)
		return
	}
	c.JSON(http.StatusOK, bs)
}
