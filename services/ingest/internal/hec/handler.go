package hec

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/om-ashish-soni/cusplunk/ingest/internal/event"
	"github.com/om-ashish-soni/cusplunk/ingest/internal/queue"
)

// HEC response codes mirror the Splunk HEC spec so existing clients work unchanged.
const (
	hecCodeSuccess         = 0
	hecCodeTokenDisabled   = 1
	hecCodeTokenRequired   = 2
	hecCodeInvalidAuth     = 3
	hecCodeInvalidEvent    = 5
	hecCodeServerError     = 8
	hecCodeInvalidDataChan = 9
	hecCodeChannelMissing  = 10
	hecCodeInvalidChan     = 11
	hecCodeAckDisabled     = 14
)

type hecResponse struct {
	Text    string `json:"text"`
	Code    int    `json:"code"`
	AckID   int    `json:"ackId,omitempty"`
}

func successResp() hecResponse  { return hecResponse{Text: "Success", Code: hecCodeSuccess} }
func errorResp(code int, text string) hecResponse { return hecResponse{Text: text, Code: code} }

// hecEventPayload is the JSON body for POST /services/collector/event.
type hecEventPayload struct {
	Time       *float64               `json:"time"`
	Host       string                 `json:"host"`
	Source     string                 `json:"source"`
	Sourcetype string                 `json:"sourcetype"`
	Index      string                 `json:"index"`
	Event      json.RawMessage        `json:"event"`
	Fields     map[string]interface{} `json:"fields"`
}

// handler holds the queue and token store used by all HEC endpoints.
type handler struct {
	q      queue.Queue
	tokens *tokenStore
}

// handleEvent implements POST /services/collector/event
// Accepts single or batched JSON event objects (newline-delimited).
func (h *handler) handleEvent(c *gin.Context) {
	token := extractToken(c.Request)
	meta, ok := h.tokens.lookup(token)
	if !ok {
		c.JSON(http.StatusUnauthorized, errorResp(hecCodeInvalidAuth, "Invalid token"))
		return
	}

	body, err := io.ReadAll(c.Request.Body)
	if err != nil {
		c.JSON(http.StatusBadRequest, errorResp(hecCodeInvalidEvent, "Failed to read body"))
		return
	}
	if len(body) == 0 {
		c.JSON(http.StatusBadRequest, errorResp(hecCodeInvalidEvent, "No data"))
		return
	}

	count := 0
	dec := json.NewDecoder(nopCloser(body))
	for dec.More() {
		var p hecEventPayload
		if err := dec.Decode(&p); err != nil {
			c.JSON(http.StatusBadRequest, errorResp(hecCodeInvalidEvent,
				fmt.Sprintf("JSON decode error: %v", err)))
			return
		}

		ev := payloadToEvent(p, meta)
		if err := h.q.Enqueue(c.Request.Context(), ev); err != nil {
			c.JSON(http.StatusServiceUnavailable, errorResp(hecCodeServerError, "Queue full"))
			return
		}
		count++
	}

	if count == 0 {
		c.JSON(http.StatusBadRequest, errorResp(hecCodeInvalidEvent, "No events parsed"))
		return
	}

	resp := successResp()
	resp.AckID = count
	c.JSON(http.StatusOK, resp)
}

// handleRaw implements POST /services/collector/raw
// Accepts raw text; each line is treated as a separate event.
func (h *handler) handleRaw(c *gin.Context) {
	token := extractToken(c.Request)
	meta, ok := h.tokens.lookup(token)
	if !ok {
		c.JSON(http.StatusUnauthorized, errorResp(hecCodeInvalidAuth, "Invalid token"))
		return
	}

	// Extract optional query-param overrides (same as Splunk HEC).
	qp := c.Request.URL.Query()
	overrideIndex := firstNonEmpty(qp.Get("index"), meta.DefaultIndex, "main")
	overrideHost := firstNonEmpty(qp.Get("host"), meta.DefaultHost, "unknown")
	overrideSourcetype := firstNonEmpty(qp.Get("sourcetype"), "generic_single_line")
	overrideSource := qp.Get("source")

	body, err := io.ReadAll(c.Request.Body)
	if err != nil {
		c.JSON(http.StatusBadRequest, errorResp(hecCodeInvalidEvent, "Failed to read body"))
		return
	}
	if len(body) == 0 {
		c.JSON(http.StatusBadRequest, errorResp(hecCodeInvalidEvent, "No data"))
		return
	}

	ctx := c.Request.Context()
	now := time.Now()
	ev := event.RawEvent{
		Time:       now,
		Raw:        body,
		Host:       overrideHost,
		Source:     overrideSource,
		Sourcetype: overrideSourcetype,
		Index:      overrideIndex,
	}
	if err := h.q.Enqueue(ctx, ev); err != nil {
		c.JSON(http.StatusServiceUnavailable, errorResp(hecCodeServerError, "Queue full"))
		return
	}

	c.JSON(http.StatusOK, successResp())
}

// handleAck implements POST /services/collector/ack
// Splunk HEC clients poll this to confirm delivery. cuSplunk always reports
// all requested ack IDs as committed (R1 stub — R2 will wire to store ACKs).
func (h *handler) handleAck(c *gin.Context) {
	token := extractToken(c.Request)
	if _, ok := h.tokens.lookup(token); !ok {
		c.JSON(http.StatusUnauthorized, errorResp(hecCodeInvalidAuth, "Invalid token"))
		return
	}

	var req struct {
		Acks []int `json:"acks"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, errorResp(hecCodeInvalidEvent, "Invalid ack request"))
		return
	}

	// Mark all requested acks as committed (stub).
	acks := make(map[string]bool, len(req.Acks))
	for _, id := range req.Acks {
		acks[strconv.Itoa(id)] = true
	}
	c.JSON(http.StatusOK, gin.H{"acks": acks})
}

// handleHealth implements GET /services/collector/health
// Splunk-compatible health check endpoint.
func (h *handler) handleHealth(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"text": "HEC is healthy", "code": 17})
}

// payloadToEvent converts a parsed HEC JSON payload into a RawEvent.
func payloadToEvent(p hecEventPayload, meta tokenMeta) event.RawEvent {
	ts := time.Now()
	if p.Time != nil {
		sec := int64(*p.Time)
		ns := int64((*p.Time - float64(sec)) * 1e9)
		ts = time.Unix(sec, ns)
	}

	raw := []byte(fmt.Sprintf("%s", p.Event))
	if len(raw) == 0 {
		raw = []byte("{}")
	}

	fields := make(map[string]string, len(p.Fields))
	for k, v := range p.Fields {
		fields[k] = fmt.Sprintf("%v", v)
	}

	return event.RawEvent{
		Time:       ts,
		Raw:        raw,
		Host:       firstNonEmpty(p.Host, meta.DefaultHost, "unknown"),
		Source:     p.Source,
		Sourcetype: firstNonEmpty(p.Sourcetype, "hec_json"),
		Index:      firstNonEmpty(p.Index, meta.DefaultIndex, "main"),
		Fields:     fields,
	}
}

func firstNonEmpty(ss ...string) string {
	for _, s := range ss {
		if s != "" {
			return s
		}
	}
	return ""
}

// nopCloser wraps a byte slice as an io.Reader.
type nopCloserReader struct{ *bytesReader }
type bytesReader struct{ buf []byte; pos int }

func (r *bytesReader) Read(p []byte) (int, error) {
	if r.pos >= len(r.buf) { return 0, io.EOF }
	n := copy(p, r.buf[r.pos:])
	r.pos += n
	return n, nil
}

func nopCloser(b []byte) io.Reader {
	return &bytesReader{buf: b}
}

// Compile-time check: context is available through gin.
var _ context.Context = context.Background()
