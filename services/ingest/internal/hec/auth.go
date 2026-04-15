// Package hec implements the Splunk HTTP Event Collector (HEC) endpoint.
// Splunk HEC clients send events via HTTP POST; cuSplunk accepts them unchanged.
package hec

import (
	"net/http"
	"strings"
	"sync"
)

// tokenStore is a thread-safe lookup of valid HEC tokens.
type tokenStore struct {
	mu     sync.RWMutex
	tokens map[string]tokenMeta
}

type tokenMeta struct {
	DefaultIndex string
	DefaultHost  string
}

func newTokenStore() *tokenStore {
	return &tokenStore{tokens: make(map[string]tokenMeta)}
}

func (ts *tokenStore) add(token, defaultIndex, defaultHost string) {
	ts.mu.Lock()
	defer ts.mu.Unlock()
	ts.tokens[token] = tokenMeta{DefaultIndex: defaultIndex, DefaultHost: defaultHost}
}

// lookup validates a token and returns its metadata.
// Returns (meta, true) on success, (zero, false) on failure.
func (ts *tokenStore) lookup(token string) (tokenMeta, bool) {
	ts.mu.RLock()
	defer ts.mu.RUnlock()
	m, ok := ts.tokens[token]
	return m, ok
}

// extractToken parses the HEC bearer token from an HTTP Authorization header.
// Splunk HEC uses: "Authorization: Splunk <token>"
func extractToken(r *http.Request) string {
	auth := r.Header.Get("Authorization")
	if auth == "" {
		return ""
	}
	parts := strings.SplitN(auth, " ", 2)
	if len(parts) != 2 {
		return ""
	}
	scheme := strings.ToLower(parts[0])
	if scheme != "splunk" && scheme != "bearer" {
		return ""
	}
	return strings.TrimSpace(parts[1])
}
