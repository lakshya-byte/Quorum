package render

import (
	"fmt"
	"io"
	"sync"
	"time"
)

var frames = []string{"⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"}

// Spinner shows a one-line "still working" indicator on a terminal. It is a
// no-op when disabled (pipes, NO_COLOR, tests), so output stays clean.
type Spinner struct {
	w       io.Writer
	enabled bool

	mu      sync.Mutex
	msg     string
	paused  bool
	running bool
	stop    chan struct{}
	done    chan struct{}
}

func NewSpinner(w io.Writer, enabled bool) *Spinner {
	return &Spinner{w: w, enabled: enabled}
}

// Start begins animating with msg. Calling it again only changes the message.
func (s *Spinner) Start(msg string) {
	if !s.enabled {
		return
	}
	s.mu.Lock()
	s.msg = msg
	if s.running {
		s.mu.Unlock()
		return
	}
	s.running, s.paused = true, false
	s.stop, s.done = make(chan struct{}), make(chan struct{})
	stop, done := s.stop, s.done
	s.mu.Unlock()
	go func() {
		defer close(done)
		t := time.NewTicker(90 * time.Millisecond)
		defer t.Stop()
		for i := 0; ; i++ {
			select {
			case <-stop:
				return
			case <-t.C:
				s.mu.Lock()
				if !s.paused {
					fmt.Fprintf(s.w, "\r\x1b[2m%s %s\x1b[0m\x1b[K", frames[i%len(frames)], s.msg)
				}
				s.mu.Unlock()
			}
		}
	}()
}

// Pause erases the spinner line so other output can be written.
func (s *Spinner) Pause() {
	if !s.enabled {
		return
	}
	s.mu.Lock()
	s.paused = true
	fmt.Fprint(s.w, "\r\x1b[K")
	s.mu.Unlock()
}

// Resume lets the spinner draw again after Pause.
func (s *Spinner) Resume() {
	if !s.enabled {
		return
	}
	s.mu.Lock()
	s.paused = false
	s.mu.Unlock()
}

// SetMessage changes the text shown next to the spinner.
func (s *Spinner) SetMessage(msg string) {
	s.mu.Lock()
	s.msg = msg
	s.mu.Unlock()
}

// Stop ends the animation and clears the line.
func (s *Spinner) Stop() {
	if !s.enabled {
		return
	}
	s.mu.Lock()
	if !s.running {
		s.mu.Unlock()
		return
	}
	s.running = false
	close(s.stop)
	done := s.done
	s.mu.Unlock()
	<-done
	s.mu.Lock()
	fmt.Fprint(s.w, "\r\x1b[K")
	s.mu.Unlock()
}
