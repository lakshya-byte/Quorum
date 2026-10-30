package handler

import (
	"errors"
	"net/http"

	"patchloop-backend/internal/pkg/crypt"
	"patchloop-backend/internal/service"

	"github.com/gin-gonic/gin"
)

// apiError writes the uniform error body {error, code} (plus optional extras).
func apiError(c *gin.Context, status int, code, msg string, extra ...gin.H) {
	body := gin.H{"error": msg, "code": code}
	for _, e := range extra {
		for k, v := range e {
			body[k] = v
		}
	}
	c.JSON(status, body)
}

// serviceError maps service-layer errors to HTTP. Returns true when handled.
func serviceError(c *gin.Context, err error) {
	var (
		mr *service.MergeRefusedError
		ge *service.GitHubAPIError
	)
	switch {
	case errors.Is(err, service.ErrGitHubNotConnected):
		apiError(c, http.StatusConflict, "github_not_connected", "connect github first")
	case errors.Is(err, service.ErrGitHubAppNotConfigured):
		apiError(c, http.StatusServiceUnavailable, "not_configured", "github app not configured")
	case errors.Is(err, crypt.ErrNotConfigured):
		apiError(c, http.StatusServiceUnavailable, "not_configured", "token encryption is not configured on this server (set TOKEN_ENC_KEY)")
	case errors.Is(err, service.ErrNeedUserAuth):
		apiError(c, http.StatusConflict, "github_reauth", err.Error())
	case errors.Is(err, service.ErrInvalidBugID), errors.Is(err, service.ErrInvalidEngine), errors.Is(err, service.ErrInvalidRepo),
		errors.Is(err, service.ErrInvalidBranch), errors.Is(err, service.ErrInvalidTask),
		errors.Is(err, service.ErrInvalidTaskType), errors.Is(err, service.ErrInvalidStrict), errors.Is(err, service.ErrInvalidLimits),
		errors.Is(err, service.ErrInvalidAnswers), errors.Is(err, service.ErrArtifactInvalid):
		apiError(c, http.StatusBadRequest, "bad_request", err.Error())
	case errors.Is(err, service.ErrRepoNotGranted):
		apiError(c, http.StatusForbidden, "repo_not_granted", err.Error())
	case errors.Is(err, service.ErrArtifactNotFound):
		apiError(c, http.StatusNotFound, "not_found", "artifact not found")
	case errors.Is(err, service.ErrArtifactTooLarge), errors.Is(err, service.ErrArtifactType):
		apiError(c, http.StatusBadGateway, "bad_artifact", "the artifact cannot be served")
	case errors.Is(err, service.ErrRunNotFound):
		apiError(c, http.StatusNotFound, "not_found", "run not found")
	case errors.Is(err, service.ErrRunNotReady), errors.Is(err, service.ErrNoPR), errors.Is(err, service.ErrRunNotDone), errors.Is(err, service.ErrNotNeedsInput):
		apiError(c, http.StatusConflict, "conflict", err.Error())
	case errors.Is(err, service.ErrFollowupLimit):
		apiError(c, http.StatusTooManyRequests, "rate_limited", err.Error())
	case errors.As(err, &mr):
		apiError(c, http.StatusConflict, "merge_refused", mr.Reason, gin.H{"reason": mr.Reason})
	case errors.As(err, &ge):
		switch ge.Status {
		case http.StatusUnauthorized, http.StatusForbidden:
			apiError(c, http.StatusConflict, "github_rejected", "GitHub rejected the request: reinstall or reconnect the PatchLoop GitHub App")
		case http.StatusNotFound:
			apiError(c, http.StatusNotFound, "not_found", "GitHub says that does not exist (or the App cannot see it)")
		case http.StatusTooManyRequests:
			apiError(c, http.StatusTooManyRequests, "rate_limited", "GitHub rate limit reached, retry later")
		default:
			apiError(c, http.StatusBadGateway, "upstream_error", "GitHub is unavailable, please retry")
		}
	default:
		agentErrorResponse(c, err)
	}
}
