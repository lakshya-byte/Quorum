// Package memstore holds in-memory implementations of the service store
// interfaces. They exist so the whole GitHub/Slack/run flow can be tested
// without MongoDB; production uses internal/repository.
package memstore

import (
	"context"
	"sort"
	"sync"
	"time"

	"patchloop-backend/internal/models"
	"patchloop-backend/internal/repository"

	"go.mongodb.org/mongo-driver/v2/bson"
)

// Store implements every store interface in one struct.
type Store struct {
	mu            sync.Mutex
	runs          map[string]*models.Run
	order         []string
	gh            map[string]*models.GitHubConnection
	slackSettings map[string]*models.SlackSettings
	slackLinks    map[string]string // slack user -> user
	codes         map[string]models.SlackLinkCode
	notes         []*models.Notification
	seen          map[string]bool
}

func New() *Store {
	return &Store{runs: map[string]*models.Run{}, gh: map[string]*models.GitHubConnection{},
		slackSettings: map[string]*models.SlackSettings{}, slackLinks: map[string]string{},
		codes: map[string]models.SlackLinkCode{}, seen: map[string]bool{}}
}

func clone(r *models.Run) *models.Run { c := *r; return &c }

// ---- RunStore ----

func (s *Store) Create(ctx context.Context, run *models.Run) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	run.ID = bson.NewObjectID()
	run.CreatedAt = time.Now().UTC()
	s.runs[run.ID.Hex()] = clone(run)
	s.order = append(s.order, run.ID.Hex())
	return nil
}

func (s *Store) FindByID(ctx context.Context, id string) (*models.Run, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	r, ok := s.runs[id]
	if !ok {
		return nil, repository.ErrNotFound
	}
	return clone(r), nil
}

func (s *Store) ListByUser(ctx context.Context, userID string, limit int64) ([]models.Run, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := []models.Run{}
	for i := len(s.order) - 1; i >= 0; i-- {
		if r := s.runs[s.order[i]]; r.UserID == userID {
			c := clone(r)
			c.Nodes = nil
			c.Plan = nil
			out = append(out, *c)
		}
	}
	return out, nil
}

func (s *Store) CountLiveSince(ctx context.Context, userID string, since time.Time) (int64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	var n int64
	for _, r := range s.runs {
		if r.UserID == userID && r.Live && !r.CreatedAt.Before(since) {
			n++
		}
	}
	return n, nil
}

func (s *Store) with(id string, f func(r *models.Run)) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	r, ok := s.runs[id]
	if !ok {
		return repository.ErrNotFound
	}
	f(r)
	return nil
}

func (s *Store) SetAgentRun(ctx context.Context, id, agentRunID, mode, engine, traceID string) error {
	return s.with(id, func(r *models.Run) {
		r.AgentRunID, r.Mode, r.Engine = agentRunID, mode, engine
		if traceID != "" {
			r.TraceID = traceID
		}
	})
}
func (s *Store) SetStatus(ctx context.Context, id, status string) error {
	return s.with(id, func(r *models.Run) { r.Status = status })
}
func (s *Store) SetPR(ctx context.Context, id, url string, number int, branch string) error {
	return s.with(id, func(r *models.Run) {
		r.PRURL = url
		if number > 0 {
			r.PRNumber = number
		}
		if branch != "" {
			r.PRBranch = branch
		}
	})
}
func (s *Store) SetMerged(ctx context.Context, id, by string, at time.Time) error {
	return s.with(id, func(r *models.Run) { r.Merged = &models.Merged{By: by, At: at} })
}
func (s *Store) SetMergedForPR(ctx context.Context, userID, repo, branch string, number int, by string, at time.Time) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, r := range s.runs {
		if r.UserID == userID && r.Repo == repo && r.PRNumber == number && r.PRBranch == branch {
			r.Merged = &models.Merged{By: by, At: at}
		}
	}
	return nil
}
func (s *Store) SetSlackSent(ctx context.Context, id string) error {
	return s.with(id, func(r *models.Run) { r.SlackSent = true })
}
func (s *Store) SetSlackRoot(ctx context.Context, id, rootTS string) error {
	return s.with(id, func(r *models.Run) {
		if r.Slack != nil {
			r.Slack.RootTS = rootTS
		}
	})
}

func (s *Store) newest(match func(*models.Run) bool) (*models.Run, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for i := len(s.order) - 1; i >= 0; i-- {
		if r := s.runs[s.order[i]]; match(r) {
			return clone(r), nil
		}
	}
	return nil, repository.ErrNotFound
}

func (s *Store) FindBySlackThread(ctx context.Context, channel, threadTS string) (*models.Run, error) {
	return s.newest(func(r *models.Run) bool {
		return r.Slack != nil && r.Slack.Channel == channel && r.Slack.ThreadTS == threadTS
	})
}
func (s *Store) FindByPR(ctx context.Context, repo string, number int) (*models.Run, error) {
	return s.newest(func(r *models.Run) bool { return r.Repo == repo && r.PRNumber == number })
}
func (s *Store) CountChildren(ctx context.Context, parentID string) (int64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	var n int64
	for _, r := range s.runs {
		if r.ParentRunID == parentID {
			n++
		}
	}
	return n, nil
}

func (s *Store) Complete(ctx context.Context, agentRunID string, c repository.RunCompletion) (*models.Run, *models.Run, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for id, r := range s.runs {
		if r.AgentRunID == agentRunID {
			prev := clone(r)
			after := repository.ApplyCompletion(*r, c, time.Now().UTC())
			s.runs[id] = after
			return prev, clone(after), nil
		}
	}
	return nil, nil, repository.ErrNotFound
}

// ---- GitHubStore ----

func (s *Store) Get(ctx context.Context, userID string) (*models.GitHubConnection, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	c, ok := s.gh[userID]
	if !ok {
		return nil, repository.ErrNotFound
	}
	cp := *c
	return &cp, nil
}
func (s *Store) Put(ctx context.Context, c *models.GitHubConnection) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	cp := *c
	s.gh[c.UserID] = &cp
	return nil
}
func (s *Store) Delete(ctx context.Context, userID string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	delete(s.gh, userID)
	return nil
}
func (s *Store) findGH(match func(*models.GitHubConnection) bool) (*models.GitHubConnection, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, c := range s.gh {
		if match(c) {
			cp := *c
			return &cp, nil
		}
	}
	return nil, repository.ErrNotFound
}
func (s *Store) FindByInstallation(ctx context.Context, id int64) (*models.GitHubConnection, error) {
	return s.findGH(func(c *models.GitHubConnection) bool {
		return id != 0 && c.InstallationID == id && (c.Mode == models.GitHubModeApp || c.Mode == models.GitHubModeDemo)
	})
}
func (s *Store) FindByLogin(ctx context.Context, login string) (*models.GitHubConnection, error) {
	return s.findGH(func(c *models.GitHubConnection) bool { return c.Login == login && c.Mode == models.GitHubModeApp })
}

// RawGitHub returns the stored connection, ciphertext included (tests).
func (s *Store) RawGitHub(userID string) *models.GitHubConnection {
	c, _ := s.Get(context.Background(), userID)
	return c
}

// ---- SlackStore ----

func (s *Store) GetSettings(ctx context.Context, userID string) (*models.SlackSettings, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	v, ok := s.slackSettings[userID]
	if !ok {
		return nil, repository.ErrNotFound
	}
	cp := *v
	return &cp, nil
}
func (s *Store) PutSettings(ctx context.Context, v *models.SlackSettings) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	cp := *v
	s.slackSettings[v.UserID] = &cp
	return nil
}
func (s *Store) DeleteWebhook(ctx context.Context, userID string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if v, ok := s.slackSettings[userID]; ok {
		v.EncWebhook = ""
	}
	return nil
}
func (s *Store) PutLink(ctx context.Context, l *models.SlackLink) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	for k, u := range s.slackLinks {
		if u == l.UserID {
			delete(s.slackLinks, k)
		}
	}
	s.slackLinks[l.SlackUserID] = l.UserID
	return nil
}
func (s *Store) UserForSlack(ctx context.Context, slackUserID string) (string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if u, ok := s.slackLinks[slackUserID]; ok {
		return u, nil
	}
	return "", repository.ErrNotFound
}
func (s *Store) SlackForUser(ctx context.Context, userID string) (string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for k, u := range s.slackLinks {
		if u == userID {
			return k, nil
		}
	}
	return "", repository.ErrNotFound
}
func (s *Store) PutCode(ctx context.Context, c *models.SlackLinkCode) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.codes[c.Code] = *c
	return nil
}
func (s *Store) TakeCode(ctx context.Context, code string, now time.Time) (string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	c, ok := s.codes[code]
	if !ok || !c.ExpiresAt.After(now) {
		return "", repository.ErrNotFound
	}
	delete(s.codes, code)
	return c.UserID, nil
}

// ---- NotificationStore ----

// Notes returns a snapshot of all notifications (tests).
func (s *Store) Notes() []models.Notification {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := []models.Notification{}
	for _, n := range s.notes {
		out = append(out, *n)
	}
	return out
}

// NotificationStore is the notifications view of Store (Create/ListByUser
// would otherwise clash with the run methods of the same name).
func (s *Store) NotificationStore() *Notifications { return &Notifications{s: s} }

type Notifications struct{ s *Store }

// Notesx returns every notification of every user (tests).
func (n *Notifications) Notesx() []models.Notification { return n.s.Notes() }

func (n *Notifications) Create(ctx context.Context, v *models.Notification) error {
	n.s.mu.Lock()
	defer n.s.mu.Unlock()
	v.ID = bson.NewObjectID()
	v.CreatedAt = time.Now().UTC()
	cp := *v
	n.s.notes = append(n.s.notes, &cp)
	return nil
}
func (n *Notifications) ListByUser(ctx context.Context, userID string, limit int64) ([]models.Notification, error) {
	n.s.mu.Lock()
	defer n.s.mu.Unlock()
	out := []models.Notification{}
	for _, v := range n.s.notes {
		if v.UserID == userID {
			out = append(out, *v)
		}
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].CreatedAt.After(out[j].CreatedAt) })
	return out, nil
}
func (n *Notifications) MarkRead(ctx context.Context, userID, id string) error {
	n.s.mu.Lock()
	defer n.s.mu.Unlock()
	for _, v := range n.s.notes {
		if v.ID.Hex() == id && v.UserID == userID {
			v.Read = true
			return nil
		}
	}
	return repository.ErrNotFound
}

// ---- DedupeStore ----

func (s *Store) Seen(ctx context.Context, key string) (bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.seen[key] {
		return true, nil
	}
	s.seen[key] = true
	return false, nil
}
