// Package ratelimit is a small in-memory token bucket keyed by string
// (e.g. client IP). It is per-process: fine for a single backend instance.
package ratelimit

import (
	"math"
	"sync"
	"time"
)

type bucket struct {
	tokens float64
	last   time.Time
}

type Limiter struct {
	mu       sync.Mutex
	capacity float64
	rate     float64 // tokens per second
	buckets  map[string]*bucket
	now      func() time.Time
	lastGC   time.Time
}

// New allows `capacity` requests per `per` per key, refilled continuously.
func New(capacity int, per time.Duration) *Limiter {
	return &Limiter{
		capacity: float64(capacity),
		rate:     float64(capacity) / per.Seconds(),
		buckets:  map[string]*bucket{},
		now:      time.Now,
	}
}

// Allow consumes one token for key. When denied it returns how long until
// the next token is available.
func (l *Limiter) Allow(key string) (bool, time.Duration) {
	l.mu.Lock()
	defer l.mu.Unlock()
	now := l.now()
	l.gc(now)
	b, ok := l.buckets[key]
	if !ok {
		b = &bucket{tokens: l.capacity, last: now}
		l.buckets[key] = b
	}
	b.tokens = math.Min(l.capacity, b.tokens+now.Sub(b.last).Seconds()*l.rate)
	b.last = now
	if b.tokens >= 1 {
		b.tokens--
		return true, 0
	}
	if l.rate <= 0 {
		return false, time.Hour
	}
	wait := time.Duration((1 - b.tokens) / l.rate * float64(time.Second))
	return false, wait
}

// gc drops full buckets occasionally so memory stays bounded.
func (l *Limiter) gc(now time.Time) {
	if now.Sub(l.lastGC) < 10*time.Minute {
		return
	}
	l.lastGC = now
	for k, b := range l.buckets {
		if b.tokens+now.Sub(b.last).Seconds()*l.rate >= l.capacity {
			delete(l.buckets, k)
		}
	}
}

// SetClock is for tests.
func (l *Limiter) SetClock(now func() time.Time) { l.now = now }
