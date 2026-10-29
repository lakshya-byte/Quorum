// Package apierr maps HTTP statuses to the stable machine-readable `code`
// that accompanies every error body: {"error": "...", "code": "..."}.
package apierr

import "net/http"

// Code returns the default code for an HTTP status.
func Code(status int) string {
	switch status {
	case http.StatusBadRequest, http.StatusUnprocessableEntity, http.StatusRequestEntityTooLarge:
		return "bad_request"
	case http.StatusUnauthorized:
		return "unauthorized"
	case http.StatusForbidden:
		return "forbidden"
	case http.StatusNotFound:
		return "not_found"
	case http.StatusConflict:
		return "conflict"
	case http.StatusTooManyRequests:
		return "rate_limited"
	case http.StatusServiceUnavailable:
		return "not_configured"
	case http.StatusBadGateway, http.StatusGatewayTimeout:
		return "upstream_error"
	default:
		return "internal"
	}
}
