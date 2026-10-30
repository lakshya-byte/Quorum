package service

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"time"

	"patchloop-backend/internal/models"
)

// Errors of the swarm task API (CONTRACT-V3).
var (
	ErrInvalidTaskType  = errors.New("taskType must be one of: " + strings.Join(models.TaskTypes, ", "))
	ErrInvalidStrict    = errors.New("strict must be at most 20 criterion ids (letters, digits, _ . : -, max 64 characters each)")
	ErrInvalidLimits    = errors.New("limits.maxWorkers, limits.maxTokens and limits.maxWallS must not be negative")
	ErrNotNeedsInput    = errors.New("this run is not waiting for answers")
	ErrInvalidAnswers   = errors.New("answers must map the run's question ids to 1 to 2000 character texts (at most 20 answers, 8000 characters in total)")
	ErrArtifactInvalid  = errors.New("invalid artifact id")
	ErrArtifactNotFound = errors.New("artifact not found")
	ErrArtifactTooLarge = errors.New("artifact is too large")
	ErrArtifactType     = errors.New("the agent returned an artifact type that is not allowed")
)

// Default hard caps on what a task may ask of the swarm; overridden by
// RunServiceConfig (env SWARM_MAX_WORKERS_CAP etc.). The agent clamps again.
const (
	DefaultMaxWorkersCap = 8
	DefaultMaxTokensCap  = 2_000_000
	DefaultMaxWallSCap   = 3600
)

var (
	criterionIDPattern = regexp.MustCompile(`^[A-Za-z0-9_.:-]{1,64}$`)
	questionIDPattern  = regexp.MustCompile(`^[A-Za-z0-9_.-]{1,64}$`)
	artifactIDPattern  = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`)
)

// ValidateTaskOptions normalises and checks taskType ("" = auto) and strict.
func ValidateTaskOptions(taskType string, strict []string) (string, []string, error) {
	taskType = strings.ToLower(strings.TrimSpace(taskType))
	if taskType == "" {
		taskType = models.TaskTypeAuto
	}
	if !models.ValidTaskType(taskType) {
		return "", nil, ErrInvalidTaskType
	}
	if len(strict) > 20 {
		return "", nil, ErrInvalidStrict
	}
	seen := map[string]bool{}
	var out []string
	for _, id := range strict {
		id = strings.TrimSpace(id)
		if !criterionIDPattern.MatchString(id) {
			return "", nil, ErrInvalidStrict
		}
		if !seen[id] {
			seen[id] = true
			out = append(out, id)
		}
	}
	return taskType, out, nil
}

// ClampLimits validates requested budgets and clamps them to the configured
// caps. Zero fields mean "agent default" and stay zero. It reports whether
// anything was reduced.
func (s *RunService) ClampLimits(in *models.Limits) (*models.Limits, bool, error) {
	if in == nil {
		return nil, false, nil
	}
	if in.MaxWorkers < 0 || in.MaxTokens < 0 || in.MaxWallS < 0 {
		return nil, false, ErrInvalidLimits
	}
	out := *in
	clamped := false
	if out.MaxWorkers > s.caps.MaxWorkers {
		out.MaxWorkers, clamped = s.caps.MaxWorkers, true
	}
	if out.MaxTokens > s.caps.MaxTokens {
		out.MaxTokens, clamped = s.caps.MaxTokens, true
	}
	if out.MaxWallS > s.caps.MaxWallS {
		out.MaxWallS, clamped = s.caps.MaxWallS, true
	}
	if out == (models.Limits{}) {
		return nil, clamped, nil
	}
	return &out, clamped, nil
}

// SwarmCaps are the configured ceilings for per-task limits.
type SwarmCaps struct {
	MaxWorkers int
	MaxTokens  int64
	MaxWallS   int
}

func (c SwarmCaps) withDefaults() SwarmCaps {
	if c.MaxWorkers <= 0 {
		c.MaxWorkers = DefaultMaxWorkersCap
	}
	if c.MaxTokens <= 0 {
		c.MaxTokens = DefaultMaxTokensCap
	}
	if c.MaxWallS <= 0 {
		c.MaxWallS = DefaultMaxWallSCap
	}
	return c
}

func agentLimits(l *models.Limits) *AgentLimits {
	if l == nil {
		return nil
	}
	return &AgentLimits{MaxWorkers: l.MaxWorkers, MaxTokens: l.MaxTokens, MaxWallS: l.MaxWallS}
}

// ---- answers (needs_input) ------------------------------------------------

// QuestionIDs lists the ids of a run's stored clarifying questions.
func QuestionIDs(run *models.Run) []string {
	var ids []string
	for _, q := range run.Questions {
		if m, ok := q.(map[string]any); ok {
			if id, ok := m["id"].(string); ok && id != "" {
				ids = append(ids, id)
			}
		}
	}
	return ids
}

// QuestionTexts returns id -> text for a run's questions, in order.
func QuestionTexts(run *models.Run) (ids []string, texts map[string]string) {
	texts = map[string]string{}
	for _, q := range run.Questions {
		if m, ok := q.(map[string]any); ok {
			id, _ := m["id"].(string)
			text, _ := m["text"].(string)
			if id != "" {
				ids = append(ids, id)
				texts[id] = text
			}
		}
	}
	return ids, texts
}

// CleanAnswers validates answers against the run's known question ids.
func CleanAnswers(run *models.Run, answers map[string]string) (map[string]string, error) {
	if len(answers) == 0 || len(answers) > 20 {
		return nil, ErrInvalidAnswers
	}
	known := map[string]bool{}
	for _, id := range QuestionIDs(run) {
		known[id] = true
	}
	out := map[string]string{}
	total := 0
	for id, text := range answers {
		text = strings.TrimSpace(text)
		n := len([]rune(text))
		if !questionIDPattern.MatchString(id) || n == 0 || n > 2000 || (len(known) > 0 && !known[id]) {
			return nil, ErrInvalidAnswers
		}
		total += n
		out[id] = text
	}
	if total > 8000 {
		return nil, ErrInvalidAnswers
	}
	return out, nil
}

// Answer re-runs a needs_input run with the user's answers: a child run on the
// same repo and branch (the agent receives answers). Only the owner may call
// it (the caller checks) and only while the run is waiting for input.
func (s *RunService) Answer(ctx context.Context, run *models.Run, source string, answers map[string]string, slack *models.SlackRef) (*models.Run, error) {
	if run.Kind != models.RunKindRepo {
		return nil, ErrNotNeedsInput
	}
	if run.Status != models.RunStatusCompleted || run.Outcome != models.OutcomeNeedsInput {
		return nil, ErrNotNeedsInput
	}
	clean, err := CleanAnswers(run, answers)
	if err != nil {
		return nil, err
	}
	if slack == nil {
		slack = run.Slack
	}
	return s.StartRepoRun(ctx, RepoRunInput{
		UserID: run.UserID, Repo: run.Repo, Branch: run.Branch, Task: run.Task, Source: source,
		Slack: slack, Issue: run.Issue, AnswerFor: run, Answers: clean, AutoPR: run.AutoPR,
		TaskType: taskTypeHint(run), Strict: run.Strict, Limits: run.Limits,
	})
}

// taskTypeHint is the task type to resend on a re-run: the user's own choice
// stays, an auto-resolved type is left to the planner again.
func taskTypeHint(run *models.Run) string {
	if run.TaskTypeSource == "user" && models.ValidTaskType(run.TaskType) {
		return run.TaskType
	}
	return models.TaskTypeAuto
}

// ---- artifacts --------------------------------------------------------------

// artifactMIME is the allow-list of artifact media types served to browsers.
var artifactMIME = map[string]bool{
	"image/png":        true,
	"image/jpeg":       true,
	"image/svg+xml":    true,
	"text/plain":       true,
	"application/json": true,
}

// SafeArtifactMIME maps the agent-reported media type to one the backend
// serves. text/html (agent logs/reports) is downgraded to text/plain so it
// can never render; everything else outside the allow-list is refused.
func SafeArtifactMIME(m string) (string, bool) {
	m = strings.ToLower(strings.TrimSpace(m))
	if m == "text/html" {
		return "text/plain", true
	}
	return m, artifactMIME[m]
}

// ValidArtifactID reports whether id can name an artifact (no separators,
// no dots, so no path traversal ever reaches the agent).
func ValidArtifactID(id string) bool { return artifactIDPattern.MatchString(id) }

// SanitizeArtifactIndex keeps only well-formed index entries
// {id,kind,label,phase,viewport,mime,size}; at most 100.
func SanitizeArtifactIndex(in []any) []any {
	out := []any{}
	for _, v := range in {
		m, ok := v.(map[string]any)
		if !ok {
			continue
		}
		id, _ := m["id"].(string)
		if !ValidArtifactID(id) {
			continue
		}
		mimeType, _ := m["mime"].(string)
		safe, ok := SafeArtifactMIME(mimeType)
		if !ok {
			continue
		}
		e := map[string]any{"id": id, "mime": safe}
		for _, k := range []string{"kind", "label", "phase", "viewport"} {
			if s, ok := m[k].(string); ok {
				e[k] = truncate(s, 200)
			}
		}
		if n, ok := toInt(m["size"]); ok && n >= 0 {
			e["size"] = n
		}
		out = append(out, e)
		if len(out) >= 100 {
			break
		}
	}
	return out
}

// ListArtifacts returns the run's artifact index from the agent.
func (s *RunService) ListArtifacts(ctx context.Context, run *models.Run) ([]any, error) {
	if run.AgentRunID == "" {
		return nil, ErrRunNotReady
	}
	items, err := s.agent.ListArtifacts(ctx, run.AgentRunID)
	if err != nil {
		var ae *AgentError
		if errors.As(err, &ae) && ae.Status == 404 {
			return []any{}, nil
		}
		return nil, err
	}
	raw := make([]any, 0, len(items))
	for _, it := range items {
		raw = append(raw, it)
	}
	return SanitizeArtifactIndex(raw), nil
}

// Artifact is a fetched artifact that is safe to serve.
type Artifact struct {
	ContentType string
	Data        []byte
}

// FetchArtifact proxies one artifact from the agent. The id is validated
// before it reaches the agent; the media type must be on the allow-list and
// image bytes must match their declared type.
func (s *RunService) FetchArtifact(ctx context.Context, run *models.Run, id string) (*Artifact, error) {
	if !ValidArtifactID(id) {
		return nil, ErrArtifactInvalid
	}
	if run.AgentRunID == "" {
		return nil, ErrRunNotReady
	}
	blob, err := s.agent.GetArtifact(ctx, run.AgentRunID, id)
	if err != nil {
		return nil, err
	}
	ct, ok := SafeArtifactMIME(blob.ContentType)
	if !ok {
		return nil, ErrArtifactType
	}
	if !magicMatches(ct, blob.Data) {
		return nil, ErrArtifactType
	}
	return &Artifact{ContentType: ct, Data: blob.Data}, nil
}

func magicMatches(ct string, data []byte) bool {
	switch ct {
	case "image/png":
		return len(data) >= 8 && string(data[:8]) == "\x89PNG\r\n\x1a\n"
	case "image/jpeg":
		return len(data) >= 3 && data[0] == 0xff && data[1] == 0xd8 && data[2] == 0xff
	}
	return true
}

// ---- completion helpers ------------------------------------------------------

// intOf reads a JSON number (or an integer) from a map under any of keys.
func intOf(m map[string]any, keys ...string) int {
	for _, k := range keys {
		if n, ok := toInt(m[k]); ok {
			return n
		}
	}
	return 0
}

// criteriaSummary parses the agent's `criteria` object ({hard_pass,hard_total,
// advisory:[...]}; camelCase accepted). Anything else yields nil.
func criteriaSummary(v any) *models.CriteriaSummary {
	m, ok := v.(map[string]any)
	if !ok {
		return nil
	}
	cs := &models.CriteriaSummary{
		HardPass:  intOf(m, "hard_pass", "hardPass"),
		HardTotal: intOf(m, "hard_total", "hardTotal"),
		Advisory:  []any{},
	}
	if adv, ok := m["advisory"].([]any); ok {
		for _, a := range adv {
			if len(cs.Advisory) >= 20 {
				break
			}
			cs.Advisory = append(cs.Advisory, a)
		}
	}
	if cs.HardTotal == 0 && cs.HardPass == 0 && len(cs.Advisory) == 0 {
		return nil
	}
	return cs
}

// cleanQuestions keeps well-formed {id,text} questions (max 20).
func cleanQuestions(in []any) []any {
	var out []any
	for _, v := range in {
		m, ok := v.(map[string]any)
		if !ok {
			continue
		}
		id, _ := m["id"].(string)
		text, _ := m["text"].(string)
		if !questionIDPattern.MatchString(id) || strings.TrimSpace(text) == "" {
			continue
		}
		out = append(out, map[string]any{"id": id, "text": truncate(text, 1000)})
		if len(out) >= 20 {
			break
		}
	}
	return out
}

// resolveOutcome picks the run outcome: the agent's when valid, else derived
// from the legacy solved flag.
func resolveOutcome(outcome string, solved bool) string {
	outcome = strings.ToLower(strings.TrimSpace(outcome))
	if models.ValidOutcome(outcome) {
		return outcome
	}
	if solved {
		return models.OutcomeComplete
	}
	return models.OutcomeFailed
}

// clarifyFromEvents replays the agent's event log looking for the clarify
// event (questions). Best effort: bounded to a few seconds, used only when the
// completion callback carried no questions.
func (s *RunService) clarifyFromEvents(ctx context.Context, agentRunID string) []any {
	c, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	var out []any
	_ = s.agent.StreamEvents(c, agentRunID, func(typ string, d map[string]any) bool {
		if typ == "clarify" {
			if qs, ok := d["questions"].([]any); ok {
				out = cleanQuestions(qs)
			}
			return false
		}
		return true
	})
	return out
}

// SortedKeys is a small helper for deterministic output.
func SortedKeys(m map[string]string) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

// answersText renders answers for display (Slack echo).
func answersText(ids []string, answers map[string]string) string {
	var sb strings.Builder
	for _, id := range ids {
		if a, ok := answers[id]; ok {
			fmt.Fprintf(&sb, "%s: %s\n", id, a)
		}
	}
	return strings.TrimSpace(sb.String())
}
