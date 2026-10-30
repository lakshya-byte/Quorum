package handler

import (
	"net/http"
	"strconv"

	"patchloop-backend/internal/middleware"
	"patchloop-backend/internal/service"

	"github.com/gin-gonic/gin"
)

// Answers: POST /api/runs/:id/answers {answers: {questionId: text}}. Re-runs a
// needs_input run with the user's answers as a child run (same repo, branch).
// Owner only (cookie/Clerk session or plk_ token).
func (h *RunHandler) Answers(c *gin.Context) {
	run, ok := h.owned(c)
	if !ok {
		return
	}
	var req struct {
		Answers map[string]string `json:"answers" binding:"required,min=1,max=20"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		apiError(c, http.StatusBadRequest, "bad_request", service.ErrInvalidAnswers.Error())
		return
	}
	// Cheap state checks first, so a refused request spends no rate-limit budget.
	if run.Outcome != "needs_input" || run.Status != "completed" {
		serviceError(c, service.ErrNotNeedsInput)
		return
	}
	if _, err := service.CleanAnswers(run, req.Answers); err != nil {
		serviceError(c, err)
		return
	}
	if !h.allowTask(c, c.GetString(middleware.ContextUserIDKey)) {
		return
	}
	child, err := h.runs.Answer(c.Request.Context(), run, sourceOf(c), req.Answers, nil)
	if err != nil {
		serviceError(c, err)
		return
	}
	c.JSON(http.StatusCreated, gin.H{"runId": child.ID.Hex(), "parentRunId": child.ParentRunID})
}

// Artifacts: GET /api/runs/:id/artifacts. The index is proxied from the agent
// (X-Agent-Secret) and re-sanitised: only well-formed entries with an allowed
// media type are returned.
func (h *RunHandler) Artifacts(c *gin.Context) {
	run, ok := h.owned(c)
	if !ok {
		return
	}
	items, err := h.runs.ListArtifacts(c.Request.Context(), run)
	if err != nil {
		serviceError(c, err)
		return
	}
	c.Header("Cache-Control", "private, no-store")
	c.JSON(http.StatusOK, items)
}

// artifactCSP locks a served artifact down completely: no scripts, no
// network, no framing context of its own, even when opened directly.
const artifactCSP = "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:"

var artifactExt = map[string]string{
	"image/png": ".png", "image/jpeg": ".jpg", "image/svg+xml": ".svg", "text/plain": ".txt", "application/json": ".json",
}

// Artifact: GET /api/runs/:id/artifacts/:artifactId. Owner only; the id is
// validated before it reaches the agent; the media type must be on the
// allow-list (png, jpeg, svg, text/plain, json); SVG is delivered as an
// attachment (and with the sandbox CSP), everything with nosniff.
func (h *RunHandler) Artifact(c *gin.Context) {
	run, ok := h.owned(c)
	if !ok {
		return
	}
	id := c.Param("artifactId")
	art, err := h.runs.FetchArtifact(c.Request.Context(), run, id)
	if err != nil {
		serviceError(c, err)
		return
	}
	hd := c.Writer.Header()
	hd.Set("Content-Type", art.ContentType)
	hd.Set("X-Content-Type-Options", "nosniff")
	hd.Set("Content-Security-Policy", artifactCSP)
	hd.Set("Cache-Control", "private, no-store")
	hd.Set("Referrer-Policy", "no-referrer")
	hd.Set("Cross-Origin-Resource-Policy", "same-site")
	disp := "inline"
	if art.ContentType == "image/svg+xml" || c.Query("download") == "1" {
		disp = "attachment"
	}
	hd.Set("Content-Disposition", disp+`; filename="`+id+artifactExt[art.ContentType]+`"`)
	hd.Set("Content-Length", strconv.Itoa(len(art.Data)))
	c.Status(http.StatusOK)
	_, _ = c.Writer.Write(art.Data)
}
