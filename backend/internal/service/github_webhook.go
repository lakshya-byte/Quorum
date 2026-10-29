package service

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log/slog"
	"regexp"
	"strings"
	"time"

	"patchloop-backend/internal/models"
)

// VerifyGitHubSignature checks X-Hub-Signature-256 ("sha256=<hex>") over the
// raw body with a constant-time compare.
func VerifyGitHubSignature(secret string, body []byte, header string) bool {
	if secret == "" || !strings.HasPrefix(header, "sha256=") {
		return false
	}
	m := hmac.New(sha256.New, []byte(secret))
	m.Write(body)
	want := hex.EncodeToString(m.Sum(nil))
	return hmac.Equal([]byte(want), []byte(strings.TrimPrefix(header, "sha256=")))
}

// SignGitHubBody is the sender-side counterpart (tests, dev tooling).
func SignGitHubBody(secret string, body []byte) string {
	m := hmac.New(sha256.New, []byte(secret))
	m.Write(body)
	return "sha256=" + hex.EncodeToString(m.Sum(nil))
}

// GitHubWebhook turns GitHub App webhook deliveries into actions.
type GitHubWebhook struct {
	Secret    string
	github    *GitHubService
	runs      *RunService
	dedupe    DedupeStore
	AllowTask func(userID string) bool // per-user rate limit; nil = allow
	Sync      bool                     // run actions inline (tests)
}

func NewGitHubWebhook(secret string, github *GitHubService, runs *RunService, dedupe DedupeStore) *GitHubWebhook {
	return &GitHubWebhook{Secret: secret, github: github, runs: runs, dedupe: dedupe}
}

type webhookPayload struct {
	Action       string `json:"action"`
	Installation struct {
		ID int64 `json:"id"`
	} `json:"installation"`
	Sender struct {
		Login string `json:"login"`
		Type  string `json:"type"`
	} `json:"sender"`
	Repository struct {
		FullName string `json:"full_name"`
	} `json:"repository"`
	Label struct {
		Name string `json:"name"`
	} `json:"label"`
	Issue struct {
		Number      int             `json:"number"`
		Title       string          `json:"title"`
		Body        string          `json:"body"`
		PullRequest json.RawMessage `json:"pull_request"`
	} `json:"issue"`
	Comment struct {
		Body              string `json:"body"`
		AuthorAssociation string `json:"author_association"`
		User              struct {
			Login string `json:"login"`
			Type  string `json:"type"`
		} `json:"user"`
	} `json:"comment"`
}

// Handle processes one verified delivery. It returns a short status for the
// HTTP answer: accepted, duplicate or ignored.
func (w *GitHubWebhook) Handle(ctx context.Context, event, delivery string, body []byte) (string, error) {
	if delivery != "" && w.dedupe != nil {
		seen, err := w.dedupe.Seen(ctx, "gh-delivery:"+delivery)
		if err == nil && seen {
			return "duplicate", nil
		}
	}
	var p webhookPayload
	if err := json.Unmarshal(body, &p); err != nil {
		return "", fmt.Errorf("bad webhook payload")
	}
	isBot := p.Sender.Type == "Bot" || strings.HasSuffix(p.Sender.Login, "[bot]")

	switch event {
	case "installation":
		switch p.Action {
		case "created":
			w.github.LinkInstallationByLogin(ctx, p.Sender.Login, p.Installation.ID)
			return "accepted", nil
		case "deleted":
			w.github.UnlinkInstallation(ctx, p.Installation.ID)
			return "accepted", nil
		}
	case "issues":
		if p.Action == "labeled" && strings.EqualFold(p.Label.Name, "patchloop") && !isBot {
			return w.fromIssue(ctx, &p, p.Issue.Title+"\n\n"+p.Issue.Body)
		}
	case "issue_comment":
		if p.Action != "created" || p.Comment.User.Type == "Bot" || strings.HasSuffix(p.Comment.User.Login, "[bot]") {
			return "ignored", nil
		}
		low := strings.ToLower(p.Comment.Body)
		if !strings.Contains(low, "@patchloop") || !trustedAssociation(p.Comment.AuthorAssociation) {
			return "ignored", nil
		}
		if len(p.Issue.PullRequest) > 0 && string(p.Issue.PullRequest) != "null" {
			return w.fromPRComment(ctx, &p)
		}
		if strings.Contains(low, "@patchloop fix") {
			return w.fromIssue(ctx, &p, p.Issue.Title+"\n\n"+p.Issue.Body)
		}
	}
	return "ignored", nil
}

var mentionRe = regexp.MustCompile(`(?i)@patchloop`)

// trustedAssociation limits comment triggers to people with write-ish access.
func trustedAssociation(a string) bool {
	switch a {
	case "OWNER", "MEMBER", "COLLABORATOR":
		return true
	}
	return false
}

func (w *GitHubWebhook) run(f func()) {
	if w.Sync {
		f()
		return
	}
	go f()
}

func (w *GitHubWebhook) fromIssue(ctx context.Context, p *webhookPayload, task string) (string, error) {
	userID, err := w.github.UserForInstallation(ctx, p.Installation.ID)
	if err != nil || p.Repository.FullName == "" || p.Issue.Number == 0 {
		return "ignored", nil
	}
	if w.AllowTask != nil && !w.AllowTask(userID) {
		slog.Warn("github webhook run rate limited", "user", userID)
		return "ignored", nil
	}
	repo, issue := p.Repository.FullName, p.Issue.Number
	w.run(func() {
		c, cancel := context.WithTimeout(context.Background(), 60*time.Second)
		defer cancel()
		run, err := w.runs.StartRepoRun(c, RepoRunInput{
			UserID: userID, Repo: repo, Task: truncate(task, 4000), Source: models.SourceGitHub, AutoPR: true,
			Issue: &models.IssueRef{Number: issue},
		})
		if err != nil {
			slog.Warn("github-triggered run failed", "repo", repo, "error", err.Error())
			return
		}
		auth, err := w.github.AgentToken(c, userID)
		if err == nil && auth.Token != "" {
			body := "PatchLoop is on it: " + w.runs.RunURL(run)
			if err := w.github.API().CommentIssue(c, auth.Token, repo, issue, body); err != nil {
				slog.Warn("issue comment failed", "error", redact(err, auth.Token).Error())
			}
		}
	})
	return "accepted", nil
}

func (w *GitHubWebhook) fromPRComment(ctx context.Context, p *webhookPayload) (string, error) {
	userID, err := w.github.UserForInstallation(ctx, p.Installation.ID)
	if err != nil {
		return "ignored", nil
	}
	run, err := w.runs.FindByPR(ctx, p.Repository.FullName, p.Issue.Number)
	if err != nil || run.UserID != userID || !strings.HasPrefix(run.PRBranch, "patchloop/") {
		return "ignored", nil // only PRs PatchLoop opened
	}
	msg := strings.TrimSpace(mentionRe.ReplaceAllString(p.Comment.Body, ""))
	if msg == "" {
		return "ignored", nil
	}
	if w.AllowTask != nil && !w.AllowTask(userID) {
		return "ignored", nil
	}
	w.run(func() {
		c, cancel := context.WithTimeout(context.Background(), 60*time.Second)
		defer cancel()
		if _, err := w.runs.Followup(c, run, models.SourceGitHub, msg, nil); err != nil {
			slog.Warn("github-triggered follow-up failed", "error", err.Error())
		}
	})
	return "accepted", nil
}
