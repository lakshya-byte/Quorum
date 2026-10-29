package handler

import (
	"errors"
	"math"
	"net/http"
	"strconv"

	"patchloop-backend/internal/dto"
	"patchloop-backend/internal/middleware"
	"patchloop-backend/internal/models"
	"patchloop-backend/internal/pkg/hash"
	"patchloop-backend/internal/pkg/ratelimit"
	"patchloop-backend/internal/service"

	"github.com/gin-gonic/gin"
)

type RunHandler struct {
	runs       *service.RunService
	relay      *SSERelay
	guestLimit *ratelimit.Limiter
	ipSalt     string
}

type RunHandlerConfig struct {
	GuestLimiter *ratelimit.Limiter
	IPHashSalt   string
}

func NewRunHandler(runs *service.RunService, cfg RunHandlerConfig) *RunHandler {
	return &RunHandler{
		runs:       runs,
		relay:      &SSERelay{Transport: runs.Agent().Transport, Secret: runs.Agent().Secret},
		guestLimit: cfg.GuestLimiter,
		ipSalt:     cfg.IPHashSalt,
	}
}

func agentErrorResponse(c *gin.Context, err error) {
	var ae *service.AgentError
	switch {
	case errors.As(err, &ae):
		status := ae.Status
		if status == http.StatusUnauthorized || status == http.StatusForbidden {
			status = http.StatusBadGateway // our secret is wrong; not the user's fault
			c.JSON(status, gin.H{"error": "agent rejected the backend credentials"})
			return
		}
		c.JSON(status, gin.H{"error": ae.Message})
	case errors.Is(err, service.ErrAgentUnavailable):
		c.JSON(http.StatusBadGateway, gin.H{"error": "agent unavailable, please retry"})
	default:
		c.JSON(http.StatusInternalServerError, gin.H{"error": "internal error"})
	}
}

func runError(c *gin.Context, err error) {
	switch {
	case errors.Is(err, service.ErrInvalidBugID), errors.Is(err, service.ErrInvalidEngine):
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
	case errors.Is(err, service.ErrRunNotFound):
		c.JSON(http.StatusNotFound, gin.H{"error": "run not found"})
	case errors.Is(err, service.ErrRunNotReady):
		c.JSON(http.StatusConflict, gin.H{"error": err.Error()})
	default:
		agentErrorResponse(c, err)
	}
}

func toBugs(bugs []service.AgentBug) []dto.BugResponse {
	out := make([]dto.BugResponse, 0, len(bugs))
	for _, b := range bugs {
		out = append(out, dto.BugResponse{ID: b.ID, Title: b.Title, Issue: b.Issue, Tier: b.Tier})
	}
	return out
}

// Bugs: GET /api/bugs and GET /api/demo/bugs.
func (h *RunHandler) Bugs(c *gin.Context) {
	bugs, err := h.runs.ListBugs(c.Request.Context())
	if err != nil {
		agentErrorResponse(c, err)
		return
	}
	c.JSON(http.StatusOK, toBugs(bugs))
}

// Create: POST /api/runs.
func (h *RunHandler) Create(c *gin.Context) {
	var req dto.CreateRunRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: bugId is required and engine must be loop or graph"})
		return
	}
	run, err := h.runs.CreateRun(c.Request.Context(), service.CreateRunInput{
		UserID: c.GetString(middleware.ContextUserIDKey),
		BugID:  req.BugID,
		Engine: req.Engine,
		Replay: req.Replay,
	})
	if err != nil {
		runError(c, err)
		return
	}
	c.Set(middleware.ContextRunIDKey, run.ID.Hex())
	c.JSON(http.StatusCreated, dto.CreateRunResponse{RunID: run.ID.Hex(), Mode: run.Mode, Engine: run.Engine, Notice: run.Notice})
}

// List: GET /api/runs (the caller's runs, newest first, without nodes).
func (h *RunHandler) List(c *gin.Context) {
	runs, err := h.runs.ListMine(c.Request.Context(), c.GetString(middleware.ContextUserIDKey))
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to list runs"})
		return
	}
	c.JSON(http.StatusOK, runs)
}

func (h *RunHandler) owned(c *gin.Context) (*models.Run, bool) {
	run, err := h.runs.GetOwned(c.Request.Context(), c.Param("id"), c.GetString(middleware.ContextUserIDKey))
	if err != nil {
		runError(c, err)
		return nil, false
	}
	c.Set(middleware.ContextRunIDKey, run.ID.Hex())
	return run, true
}

// Get: GET /api/runs/:id.
func (h *RunHandler) Get(c *gin.Context) {
	run, ok := h.owned(c)
	if !ok {
		return
	}
	c.JSON(http.StatusOK, run)
}

// Events: GET /api/runs/:id/events (SSE passthrough).
func (h *RunHandler) Events(c *gin.Context) {
	run, ok := h.owned(c)
	if !ok {
		return
	}
	h.stream(c, run)
}

func (h *RunHandler) stream(c *gin.Context, run *models.Run) {
	if run.AgentRunID == "" {
		c.JSON(http.StatusConflict, gin.H{"error": "run has not started"})
		return
	}
	h.relay.Serve(c, h.runs.Agent().EventsURL(run.AgentRunID))
}

// OpenPR: POST /api/runs/:id/pr.
func (h *RunHandler) OpenPR(c *gin.Context) {
	run, ok := h.owned(c)
	if !ok {
		return
	}
	url, err := h.runs.OpenPR(c.Request.Context(), run)
	if err != nil {
		runError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"url": url})
}

func (h *RunHandler) ipHash(c *gin.Context) string {
	return hash.HashToken(h.ipSalt + "|" + c.ClientIP())
}

// DemoCreate: POST /api/demo/runs (guest; replay/fake only; rate limited per IP).
func (h *RunHandler) DemoCreate(c *gin.Context) {
	var req dto.DemoRunRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: bugId is required"})
		return
	}
	ipHash := h.ipHash(c)
	if ok, wait := h.guestLimit.Allow(ipHash); !ok {
		secs := int(math.Ceil(wait.Seconds()))
		c.Header("Retry-After", strconv.Itoa(secs))
		c.JSON(http.StatusTooManyRequests, gin.H{"error": "guest run limit reached, sign up for more runs or try again later", "retryAfterSec": secs})
		return
	}
	run, err := h.runs.CreateRun(c.Request.Context(), service.CreateRunInput{
		BugID:  req.BugID,
		Replay: true,
		Guest:  true,
		IPHash: ipHash,
	})
	if err != nil {
		runError(c, err)
		return
	}
	c.Set(middleware.ContextRunIDKey, run.ID.Hex())
	c.JSON(http.StatusCreated, dto.CreateRunResponse{RunID: run.ID.Hex(), Mode: run.Mode, Engine: run.Engine, Notice: run.Notice})
}

// DemoEvents: GET /api/demo/runs/:id/events (only for guest runs).
func (h *RunHandler) DemoEvents(c *gin.Context) {
	run, err := h.runs.Get(c.Request.Context(), c.Param("id"))
	if err != nil || !run.Guest {
		c.JSON(http.StatusNotFound, gin.H{"error": "run not found"})
		return
	}
	c.Set(middleware.ContextRunIDKey, run.ID.Hex())
	h.stream(c, run)
}

// Complete: POST /internal/runs/:id/complete (agent callback, X-Agent-Secret).
func (h *RunHandler) Complete(c *gin.Context) {
	var p service.CompletePayload
	if err := c.ShouldBindJSON(&p); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid payload"})
		return
	}
	agentRunID := c.Param("id")
	if p.RunID != "" && p.RunID != agentRunID {
		c.JSON(http.StatusBadRequest, gin.H{"error": "run_id does not match path"})
		return
	}
	run, err := h.runs.Complete(c.Request.Context(), agentRunID, p)
	if err != nil {
		if errors.Is(err, service.ErrRunNotFound) {
			c.JSON(http.StatusNotFound, gin.H{"error": "run not found"})
			return
		}
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to store run"})
		return
	}
	c.Set(middleware.ContextRunIDKey, run.ID.Hex())
	c.JSON(http.StatusOK, gin.H{"ok": true, "runId": run.ID.Hex()})
}
