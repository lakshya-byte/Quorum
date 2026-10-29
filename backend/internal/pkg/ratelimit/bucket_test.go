package ratelimit

import (
	"testing"
	"time"
)

func TestBucket(t *testing.T) {
	now := time.Unix(0, 0)
	l := New(3, time.Hour)
	l.SetClock(func() time.Time { return now })
	for i := 0; i < 3; i++ {
		if ok, _ := l.Allow("ip"); !ok {
			t.Fatalf("request %d denied", i)
		}
	}
	ok, wait := l.Allow("ip")
	if ok || wait <= 0 || wait > 20*time.Minute {
		t.Fatalf("4th: ok=%v wait=%v", ok, wait)
	}
	if ok, _ := l.Allow("other-ip"); !ok {
		t.Fatal("other key should be independent")
	}
	now = now.Add(20 * time.Minute)
	if ok, _ := l.Allow("ip"); !ok {
		t.Fatal("token should refill after 20 minutes")
	}
	if ok, _ := l.Allow("ip"); ok {
		t.Fatal("only one token refilled")
	}
}
