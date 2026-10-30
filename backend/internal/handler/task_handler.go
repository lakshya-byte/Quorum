package handler

import (
	"math"
	"net/http"
	"strconv"

	"patchloop-backend/internal/middleware"
	"patchloop-backend/internal/models"
	"patchloop-backend/internal/service"

	"github.com/gin-gonic/gin"
)

type createTaskRequest struct {
	Repo   string `json:"repo" binding:"required,max=201"`
	Branch string `json:"branch" binding:"max=200"`
	Task   string `json:"task" binding:"required,max=4000"`
	AutoPR *bool  `json:"autoPr"`
	Engine string `json:"engine" binding:"omitempty,oneof=loop graph"`

	// Swarm (CONTRACT-V3): validated again in the service.
	TaskType string       `json:"taskType" binding:"max=20"`
	Strict   []string     `json:"strict" binding:"max=20,dive,max=64"`
	Limits   *limitsInput `json:"limits"`
}

type limitsInput struct {
	MaxWorkers int   `json:"maxWorkers"`
	MaxTokens  int64 `json:"maxTokens"`
	MaxWallS   int   `json:"maxWallS"`
}

// sourceOf says which entry point an authenticated request came from.
func sourceOf(c *gin.Context) string {
	if c.GetString(middleware.ContextAuthTypeKey) == "token" {
		return models.SourceCLI
	}
	return models.SourceWeb
}

// CreateTask: POST /api/tasks. Guests have no account, so they never reach
// this authenticated route.
func (h *RunHandler) CreateTask(c *gin.Context) {
	var req createTaskRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		apiError(c, http.StatusBadRequest, "bad_request", "invalid request: repo (owner/name) and task (max 4000 characters) are required")
		return
	}
	userID := c.GetString(middleware.ContextUserIDKey)
	if err := service.ValidateRepoTask(req.Repo, req.Branch, req.Task); err != nil {
		serviceError(c, err) // malformed requests do not spend rate-limit budget
		return
	}
	taskType, strict, err := service.ValidateTaskOptions(req.TaskType, req.Strict)
	if err != nil {
		serviceError(c, err)
		return
	}
	var asked *models.Limits
	if req.Limits != nil {
		asked = &models.Limits{MaxWorkers: req.Limits.MaxWorkers, MaxTokens: req.Limits.MaxTokens, MaxWallS: req.Limits.MaxWallS}
	}
	if _, _, err := h.runs.ClampLimits(asked); err != nil {
		serviceError(c, err)
		return
	}
	if !h.allowTask(c, userID) {
		return
	}
	autoPR := true
	if req.AutoPR != nil {
		autoPR = *req.AutoPR
	}
	run, err := h.runs.StartRepoRun(c.Request.Context(), service.RepoRunInput{
		UserID: userID, Repo: req.Repo, Branch: req.Branch, Task: req.Task,
		Source: sourceOf(c), Engine: req.Engine, AutoPR: autoPR,
		TaskType: taskType, Strict: strict, Limits: asked,
	})
	if err != nil {
		serviceError(c, err)
		return
	}
	c.Set(middleware.ContextRunIDKey, run.ID.Hex())
	clamped := asked != nil && *asked != (models.Limits{}) && (run.Limits == nil || *run.Limits != *asked)
	c.JSON(http.StatusCreated, gin.H{"runId": run.ID.Hex(), "mode": run.Mode, "engine": run.Engine, "repo": run.Repo, "branch": run.Branch,
		"taskType": run.TaskType, "strict": run.Strict, "limits": run.Limits, "limitsClamped": clamped})
}

// allowTask spends one unit of the user's hourly task budget (every swarm
// start shares it: new tasks, follow-ups and answers). It writes the 429.
func (h *RunHandler) allowTask(c *gin.Context, userID string) bool {
	if h.taskLimit == nil {
		return true
	}
	ok, wait := h.taskLimit.Allow(userID)
	if ok {
		return true
	}
	secs := int(math.Ceil(wait.Seconds()))
	c.Header("Retry-After", strconv.Itoa(secs))
	apiError(c, http.StatusTooManyRequests, "rate_limited", "task limit reached for this hour, try again later", gin.H{"retryAfterSec": secs})
	return false
}

// GetPR: GET /api/runs/:id/pr.
func (h *RunHandler) GetPR(c *gin.Context) {
	run, ok := h.owned(c)
	if !ok {
		return
	}
	info, err := h.merge.Info(c.Request.Context(), run)
	if err != nil {
		serviceError(c, err)
		return
	}
	c.JSON(http.StatusOK, info)
}

// Merge: POST /api/runs/:id/merge {method?}. Requires the logged-in owner
// (cookie or plk_ token); the merge runs with that user's own GitHub token.
func (h *RunHandler) Merge(c *gin.Context) {
	run, ok := h.owned(c)
	if !ok {
		return
	}
	var req struct {
		Method string `json:"method"`
	}
	_ = c.ShouldBindJSON(&req) // body is optional
	res, err := h.merge.Merge(c.Request.Context(), run, c.GetString(middleware.ContextUserIDKey), req.Method)
	if err != nil {
		serviceError(c, err)
		return
	}
	c.JSON(http.StatusOK, res)
}

// Followup: POST /api/runs/:id/followup {message}.
func (h *RunHandler) Followup(c *gin.Context) {
	run, ok := h.owned(c)
	if !ok {
		return
	}
	var req struct {
		Message string `json:"message" binding:"required,max=2000"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		apiError(c, http.StatusBadRequest, "bad_request", "message is required (max 2000 characters)")
		return
	}
	if !h.allowTask(c, c.GetString(middleware.ContextUserIDKey)) {
		return
	}
	child, err := h.runs.Followup(c.Request.Context(), run, sourceOf(c), req.Message, nil)
	if err != nil {
		serviceError(c, err)
		return
	}
	c.JSON(http.StatusCreated, gin.H{"runId": child.ID.Hex(), "parentRunId": child.ParentRunID})
}
