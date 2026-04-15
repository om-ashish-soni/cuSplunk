// Package syslog implements RFC 3164 and RFC 5424 syslog parsers plus the
// UDP/TCP/TLS listeners that feed events into the ingest queue.
package syslog

import (
	"fmt"
	"strconv"
	"strings"
	"time"
)

// Message is a parsed syslog message normalised from either RFC 3164 or RFC 5424.
type Message struct {
	// Priority is the raw <PRI> value (facility*8 + severity).
	Priority int
	Facility int
	Severity int

	Timestamp time.Time
	Hostname  string
	AppName   string
	ProcID    string
	MsgID     string

	// StructuredData holds RFC 5424 SD-elements (key: SD-ID, value: map of params).
	StructuredData map[string]map[string]string

	// Message is the log body after all headers have been parsed.
	Message string

	// Version is 0 for RFC 3164, 1 for RFC 5424.
	Version int
}

// Parse auto-detects the syslog version and dispatches to the correct parser.
// It returns an error only when the message is wholly unparseable; partial
// parses set available fields and leave the rest at zero values.
func Parse(raw []byte) (*Message, error) {
	s := strings.TrimRight(string(raw), "\n\r")
	if len(s) == 0 {
		return nil, fmt.Errorf("syslog: empty message")
	}

	// RFC 5424 messages start with <PRI>VERSION (e.g. "<34>1 ").
	// RFC 3164 messages start with <PRI> (e.g. "<34>Jan ").
	pri, rest, err := parsePRI(s)
	if err != nil {
		// No valid PRI — treat the whole string as the message body.
		return &Message{Message: s}, nil
	}

	// Check for RFC 5424 version digit.
	if len(rest) >= 2 && rest[0] == '1' && rest[1] == ' ' {
		msg, err := parse5424(pri, rest[2:])
		if err != nil {
			// Fall back to treating it as RFC 3164.
			return parse3164(pri, rest)
		}
		return msg, nil
	}

	return parse3164(pri, rest)
}

// parsePRI extracts the <PRI> integer from the start of a syslog message.
// Returns the priority value and the string after the closing '>'.
func parsePRI(s string) (int, string, error) {
	if len(s) < 3 || s[0] != '<' {
		return 0, s, fmt.Errorf("syslog: missing <PRI>")
	}
	end := strings.IndexByte(s, '>')
	if end < 2 {
		return 0, s, fmt.Errorf("syslog: malformed <PRI>")
	}
	pri, err := strconv.Atoi(s[1:end])
	if err != nil || pri < 0 || pri > 191 {
		return 0, s, fmt.Errorf("syslog: invalid priority %q", s[1:end])
	}
	return pri, s[end+1:], nil
}

// priComponents splits a PRI value into facility and severity.
func priComponents(pri int) (facility, severity int) {
	return pri >> 3, pri & 0x07
}

// -- RFC 3164 parser --

// parse3164 parses the remainder of an RFC 3164 syslog message after the PRI.
// Format: MMM DD HH:MM:SS HOSTNAME TAG[PID]: MSG
func parse3164(pri int, s string) (*Message, error) {
	fac, sev := priComponents(pri)
	msg := &Message{
		Priority: pri,
		Facility: fac,
		Severity: sev,
		Version:  0,
	}

	// Parse timestamp: "Jan  2 15:04:05" (15 chars with leading space) or
	// "Jan 12 15:04:05" (15 chars no leading space).
	now := time.Now()
	ts, rest, ok := parse3164Timestamp(s, now.Year())
	if ok {
		msg.Timestamp = ts
		s = strings.TrimPrefix(rest, " ")
	} else {
		msg.Timestamp = now
	}

	// Parse HOSTNAME (first space-separated token).
	if idx := strings.IndexByte(s, ' '); idx > 0 {
		msg.Hostname = s[:idx]
		s = s[idx+1:]
	}

	// Parse optional TAG[PID]: prefix. A tag is the first token if it
	// contains '[' (with matching ']') or ends with ':'.
	// If neither pattern matches, treat the whole remainder as the message.
	tag, pid, bodyStart, hasTag := parseTag(s)
	if hasTag {
		msg.AppName = tag
		msg.ProcID = pid
		msg.Message = strings.TrimSpace(s[bodyStart:])
	} else {
		msg.Message = strings.TrimSpace(s)
	}

	return msg, nil
}

// parse3164Timestamp tries to parse "Mon DD HH:MM:SS" or "Mon  D HH:MM:SS".
func parse3164Timestamp(s string, year int) (time.Time, string, bool) {
	// Minimum length: "Jan  1 00:00:00" = 15 chars + trailing space
	if len(s) < 15 {
		return time.Time{}, s, false
	}
	tsStr := s[:15]
	rest := s[15:]

	formats := []string{
		"Jan  2 15:04:05",
		"Jan 02 15:04:05",
	}
	for _, f := range formats {
		t, err := time.Parse(f, tsStr)
		if err == nil {
			return time.Date(year, t.Month(), t.Day(),
				t.Hour(), t.Minute(), t.Second(), 0, time.UTC), rest, true
		}
	}
	return time.Time{}, s, false
}

// parseTag extracts TAG[PID]: from the message body.
// Returns tag, pid, byte offset where the message body starts, and hasTag.
// hasTag is true only when the first token contains '[...]' or ends with ':'.
// If no tag pattern is found, the caller should treat the whole string as MSG.
func parseTag(s string) (tag, pid string, bodyStart int, hasTag bool) {
	// Find first '[', ':', or ' ' to delimit the tag.
	for i, c := range s {
		switch c {
		case '[':
			tag = s[:i]
			// Find closing ']'.
			end := strings.IndexByte(s[i:], ']')
			if end < 0 {
				return tag, "", i, true
			}
			pid = s[i+1 : i+end]
			bodyStart = i + end + 1
			// Skip optional ': '
			if bodyStart < len(s) && s[bodyStart] == ':' {
				bodyStart++
			}
			if bodyStart < len(s) && s[bodyStart] == ' ' {
				bodyStart++
			}
			return tag, pid, bodyStart, true
		case ':':
			tag = s[:i]
			bodyStart = i + 1
			if bodyStart < len(s) && s[bodyStart] == ' ' {
				bodyStart++
			}
			return tag, "", bodyStart, true
		case ' ':
			// First token has no tag marker — no TAG present.
			return "", "", 0, false
		}
	}
	return "", "", 0, false
}

// -- RFC 5424 parser --

// parse5424 parses the header fields of an RFC 5424 message.
// Format: TIMESTAMP HOSTNAME APP-NAME PROCID MSGID STRUCTURED-DATA MSG
//
// STRUCTURED-DATA may contain internal spaces inside quoted values, so we
// cannot simply split the whole string on spaces. Instead we parse the first
// five space-delimited fields (timestamp through msgid), then hand the rest
// to parseSD and the MSG extractor which understand the bracket structure.
func parse5424(pri int, s string) (*Message, error) {
	fac, sev := priComponents(pri)
	msg := &Message{
		Priority: pri,
		Facility: fac,
		Severity: sev,
		Version:  1,
	}

	// Parse the five fixed fields: TIMESTAMP HOSTNAME APP-NAME PROCID MSGID
	fixed := make([]string, 5)
	rest := s
	for i := range fixed {
		idx := strings.IndexByte(rest, ' ')
		if idx < 0 {
			return nil, fmt.Errorf("syslog 5424: too few header fields (field %d)", i)
		}
		fixed[i] = rest[:idx]
		rest = rest[idx+1:]
	}

	// TIMESTAMP
	if fixed[0] != "-" {
		ts, err := time.Parse(time.RFC3339Nano, fixed[0])
		if err != nil {
			ts, err = time.Parse(time.RFC3339, fixed[0])
			if err != nil {
				msg.Timestamp = time.Now()
			} else {
				msg.Timestamp = ts
			}
		} else {
			msg.Timestamp = ts
		}
	} else {
		msg.Timestamp = time.Now()
	}

	msg.Hostname = nilDash(fixed[1])
	msg.AppName = nilDash(fixed[2])
	msg.ProcID = nilDash(fixed[3])
	msg.MsgID = nilDash(fixed[4])

	// rest is now: STRUCTURED-DATA [SP MSG]
	// STRUCTURED-DATA is either '-' or one or more '[...]' elements.
	if strings.HasPrefix(rest, "-") {
		// No structured data.
		rest = strings.TrimPrefix(rest, "-")
	} else if strings.HasPrefix(rest, "[") {
		// Consume all SD elements.
		sdEnd := 0
		for sdEnd < len(rest) && rest[sdEnd] == '[' {
			end := findSDEnd(rest[sdEnd:])
			if end < 0 {
				break
			}
			sdEnd += end + 1
		}
		sdStr := rest[:sdEnd]
		msg.StructuredData = parseSD(sdStr)
		rest = rest[sdEnd:]
	}

	// Remaining text (after optional space) is the MSG.
	rest = strings.TrimPrefix(rest, " ")
	if rest != "" {
		msg.Message = strings.TrimPrefix(rest, "\xef\xbb\xbf") // strip BOM
	}

	return msg, nil
}

// parseSD parses RFC 5424 structured data: [id key="val" key2="val2"][id2 ...]
func parseSD(s string) map[string]map[string]string {
	result := make(map[string]map[string]string)
	for len(s) > 0 && s[0] == '[' {
		end := findSDEnd(s)
		if end < 0 {
			break
		}
		elem := s[1:end]
		s = s[end+1:]

		// First token is the SD-ID.
		parts := strings.SplitN(elem, " ", 2)
		sdID := parts[0]
		params := make(map[string]string)

		if len(parts) == 2 {
			parseSDParams(parts[1], params)
		}
		result[sdID] = params
	}
	return result
}

// findSDEnd finds the closing ']' of an SD-element, respecting escaped characters.
func findSDEnd(s string) int {
	inQuote := false
	for i := 1; i < len(s); i++ {
		switch s[i] {
		case '"':
			if i > 0 && s[i-1] != '\\' {
				inQuote = !inQuote
			}
		case ']':
			if !inQuote {
				return i
			}
		}
	}
	return -1
}

// parseSDParams parses space-separated key="value" pairs into params.
func parseSDParams(s string, params map[string]string) {
	for len(s) > 0 {
		s = strings.TrimPrefix(s, " ")
		eqIdx := strings.IndexByte(s, '=')
		if eqIdx < 0 {
			break
		}
		key := s[:eqIdx]
		s = s[eqIdx+1:]
		if len(s) == 0 || s[0] != '"' {
			break
		}
		s = s[1:] // skip opening quote
		var val strings.Builder
		for len(s) > 0 {
			if s[0] == '\\' && len(s) > 1 {
				val.WriteByte(s[1])
				s = s[2:]
			} else if s[0] == '"' {
				s = s[1:] // skip closing quote
				break
			} else {
				val.WriteByte(s[0])
				s = s[1:]
			}
		}
		params[key] = val.String()
	}
}

func nilDash(s string) string {
	if s == "-" {
		return ""
	}
	return s
}
