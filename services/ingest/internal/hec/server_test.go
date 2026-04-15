package hec

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/om-ashish-soni/cusplunk/ingest/internal/queue"
)

const testToken = "test-token-abc123"

func init() { gin.SetMode(gin.TestMode) }

// newTestHandler creates a handler wired to a real channel queue.
func newTestHandler(t *testing.T) (*handler, *queue.ChannelQueue) {
	t.Helper()
	ts := newTokenStore()
	ts.add(testToken, "main", "test-host")
	q := queue.NewChannelQueue(1000)
	t.Cleanup(func() { q.Close() })
	return &handler{q: q, tokens: ts}, q
}

func authHeader(token string) string { return "Splunk " + token }

// setupRouter wires a handler into a Gin test router.
func setupRouter(h *handler) *gin.Engine {
	r := gin.New()
	r.POST("/services/collector/event", h.handleEvent)
	r.POST("/services/collector/raw", h.handleRaw)
	r.POST("/services/collector/ack", h.handleAck)
	r.GET("/services/collector/health", h.handleHealth)
	return r
}

// -- /services/collector/event tests --

func TestHEC_Event_SingleEvent(t *testing.T) {
	h, q := newTestHandler(t)
	r := setupRouter(h)

	body := `{"time":1735689600,"host":"myhost","source":"/var/log/app.log","sourcetype":"app","index":"main","event":{"msg":"hello world"}}`
	req := httptest.NewRequest(http.MethodPost, "/services/collector/event", strings.NewReader(body))
	req.Header.Set("Authorization", authHeader(testToken))
	req.Header.Set("Content-Type", "application/json")

	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
	var resp hecResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, hecCodeSuccess, resp.Code)

	// Verify event hit the queue.
	assert.Eventually(t, func() bool {
		select {
		case batch := <-q.Drain():
			return len(batch) == 1 && batch[0].Host == "myhost"
		default:
			return false
		}
	}, time.Second, 10*time.Millisecond)
}

func TestHEC_Event_BatchEvents(t *testing.T) {
	h, _ := newTestHandler(t)
	r := setupRouter(h)

	// Multiple JSON objects in one body (Splunk HEC batch format).
	body := `{"time":1000,"event":"first"}` + "\n" + `{"time":2000,"event":"second"}`
	req := httptest.NewRequest(http.MethodPost, "/services/collector/event", strings.NewReader(body))
	req.Header.Set("Authorization", authHeader(testToken))

	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
	var resp hecResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, 2, resp.AckID) // 2 events
}

func TestHEC_Event_InvalidToken(t *testing.T) {
	h, _ := newTestHandler(t)
	r := setupRouter(h)

	req := httptest.NewRequest(http.MethodPost, "/services/collector/event",
		strings.NewReader(`{"event":"test"}`))
	req.Header.Set("Authorization", "Splunk bad-token")

	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusUnauthorized, w.Code)
	var resp hecResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, hecCodeInvalidAuth, resp.Code)
}

func TestHEC_Event_MissingToken(t *testing.T) {
	h, _ := newTestHandler(t)
	r := setupRouter(h)

	req := httptest.NewRequest(http.MethodPost, "/services/collector/event",
		strings.NewReader(`{"event":"test"}`))
	// No Authorization header.

	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusUnauthorized, w.Code)
}

func TestHEC_Event_EmptyBody(t *testing.T) {
	h, _ := newTestHandler(t)
	r := setupRouter(h)

	req := httptest.NewRequest(http.MethodPost, "/services/collector/event",
		bytes.NewReader(nil))
	req.Header.Set("Authorization", authHeader(testToken))

	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusBadRequest, w.Code)
}

func TestHEC_Event_MalformedJSON(t *testing.T) {
	h, _ := newTestHandler(t)
	r := setupRouter(h)

	req := httptest.NewRequest(http.MethodPost, "/services/collector/event",
		strings.NewReader(`{not valid json`))
	req.Header.Set("Authorization", authHeader(testToken))

	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	var resp hecResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, hecCodeInvalidEvent, resp.Code)
}

func TestHEC_Event_DefaultsFromToken(t *testing.T) {
	// Event without host/index should inherit token defaults.
	ts := newTokenStore()
	ts.add("tok", "security", "default-host")
	q := queue.NewChannelQueue(100)
	defer q.Close()
	h := &handler{q: q, tokens: ts}
	r := setupRouter(h)

	req := httptest.NewRequest(http.MethodPost, "/services/collector/event",
		strings.NewReader(`{"event":"test"}`))
	req.Header.Set("Authorization", "Splunk tok")

	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
}

func TestHEC_Event_BearerTokenScheme(t *testing.T) {
	// Some clients send "Bearer <token>" instead of "Splunk <token>".
	h, _ := newTestHandler(t)
	r := setupRouter(h)

	req := httptest.NewRequest(http.MethodPost, "/services/collector/event",
		strings.NewReader(`{"event":"test"}`))
	req.Header.Set("Authorization", "Bearer "+testToken)

	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
}

// -- /services/collector/raw tests --

func TestHEC_Raw_Success(t *testing.T) {
	h, _ := newTestHandler(t)
	r := setupRouter(h)

	req := httptest.NewRequest(http.MethodPost, "/services/collector/raw?sourcetype=syslog",
		strings.NewReader("Jan  1 00:00:00 host kernel: message"))
	req.Header.Set("Authorization", authHeader(testToken))

	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
}

func TestHEC_Raw_InvalidToken(t *testing.T) {
	h, _ := newTestHandler(t)
	r := setupRouter(h)

	req := httptest.NewRequest(http.MethodPost, "/services/collector/raw",
		strings.NewReader("log line"))
	req.Header.Set("Authorization", "Splunk wrong")

	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusUnauthorized, w.Code)
}

func TestHEC_Raw_EmptyBody(t *testing.T) {
	h, _ := newTestHandler(t)
	r := setupRouter(h)

	req := httptest.NewRequest(http.MethodPost, "/services/collector/raw",
		bytes.NewReader(nil))
	req.Header.Set("Authorization", authHeader(testToken))

	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusBadRequest, w.Code)
}

// -- /services/collector/ack tests --

func TestHEC_Ack_Success(t *testing.T) {
	h, _ := newTestHandler(t)
	r := setupRouter(h)

	body := `{"acks":[1,2,3]}`
	req := httptest.NewRequest(http.MethodPost, "/services/collector/ack",
		strings.NewReader(body))
	req.Header.Set("Authorization", authHeader(testToken))
	req.Header.Set("Content-Type", "application/json")

	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
	var resp map[string]interface{}
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	_, hasAcks := resp["acks"]
	assert.True(t, hasAcks)
}

func TestHEC_Ack_InvalidToken(t *testing.T) {
	h, _ := newTestHandler(t)
	r := setupRouter(h)

	req := httptest.NewRequest(http.MethodPost, "/services/collector/ack",
		strings.NewReader(`{"acks":[1]}`))
	req.Header.Set("Authorization", "Splunk bad")
	req.Header.Set("Content-Type", "application/json")

	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusUnauthorized, w.Code)
}

// -- /services/collector/health tests --

func TestHEC_Health(t *testing.T) {
	h, _ := newTestHandler(t)
	r := setupRouter(h)

	req := httptest.NewRequest(http.MethodGet, "/services/collector/health", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
}

// -- extractToken tests --

func TestExtractToken_SplunkScheme(t *testing.T) {
	r := httptest.NewRequest("POST", "/", nil)
	r.Header.Set("Authorization", "Splunk my-secret-token")
	assert.Equal(t, "my-secret-token", extractToken(r))
}

func TestExtractToken_BearerScheme(t *testing.T) {
	r := httptest.NewRequest("POST", "/", nil)
	r.Header.Set("Authorization", "Bearer my-secret-token")
	assert.Equal(t, "my-secret-token", extractToken(r))
}

func TestExtractToken_Missing(t *testing.T) {
	r := httptest.NewRequest("POST", "/", nil)
	assert.Equal(t, "", extractToken(r))
}

func TestExtractToken_UnknownScheme(t *testing.T) {
	r := httptest.NewRequest("POST", "/", nil)
	r.Header.Set("Authorization", "Basic dXNlcjpwYXNz")
	assert.Equal(t, "", extractToken(r))
}

// -- payloadToEvent tests --

func TestPayloadToEvent_AllFields(t *testing.T) {
	ts := float64(1735689600)
	p := hecEventPayload{
		Time:       &ts,
		Host:       "event-host",
		Source:     "/log/path",
		Sourcetype: "json",
		Index:      "security",
		Event:      json.RawMessage(`{"key":"value"}`),
		Fields:     map[string]interface{}{"env": "prod"},
	}
	meta := tokenMeta{DefaultIndex: "main", DefaultHost: "default"}
	ev := payloadToEvent(p, meta)

	assert.Equal(t, "event-host", ev.Host)
	assert.Equal(t, "/log/path", ev.Source)
	assert.Equal(t, "json", ev.Sourcetype)
	assert.Equal(t, "security", ev.Index)
	assert.Equal(t, int64(1735689600), ev.Time.Unix())
	assert.Equal(t, "prod", ev.Fields["env"])
}

func TestPayloadToEvent_Defaults(t *testing.T) {
	// Event fields missing — token defaults apply.
	p := hecEventPayload{Event: json.RawMessage(`"raw string"`)}
	meta := tokenMeta{DefaultIndex: "ops", DefaultHost: "fallback-host"}
	ev := payloadToEvent(p, meta)

	assert.Equal(t, "fallback-host", ev.Host)
	assert.Equal(t, "ops", ev.Index)
}

func TestPayloadToEvent_NilTime(t *testing.T) {
	p := hecEventPayload{Event: json.RawMessage(`"event"`)}
	meta := tokenMeta{}
	before := time.Now()
	ev := payloadToEvent(p, meta)
	after := time.Now()

	assert.True(t, ev.Time.After(before) || ev.Time.Equal(before))
	assert.True(t, ev.Time.Before(after) || ev.Time.Equal(after))
}

// -- tokenStore tests --

func TestTokenStore_ValidToken(t *testing.T) {
	ts := newTokenStore()
	ts.add("tok1", "idx", "hst")
	m, ok := ts.lookup("tok1")
	require.True(t, ok)
	assert.Equal(t, "idx", m.DefaultIndex)
	assert.Equal(t, "hst", m.DefaultHost)
}

func TestTokenStore_InvalidToken(t *testing.T) {
	ts := newTokenStore()
	_, ok := ts.lookup("unknown")
	assert.False(t, ok)
}

func TestTokenStore_MultipleTokens(t *testing.T) {
	ts := newTokenStore()
	for i := 0; i < 10; i++ {
		ts.add(fmt.Sprintf("token-%d", i), "main", "")
	}
	for i := 0; i < 10; i++ {
		_, ok := ts.lookup(fmt.Sprintf("token-%d", i))
		assert.True(t, ok)
	}
	_, ok := ts.lookup("token-99")
	assert.False(t, ok)
}
