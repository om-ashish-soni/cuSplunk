package syslog

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// -- RFC 3164 tests --

func TestParse_RFC3164_FullMessage(t *testing.T) {
	raw := []byte("<34>Jan  1 12:00:00 myhost sshd[1234]: Accepted publickey for user")
	msg, err := Parse(raw)
	require.NoError(t, err)
	assert.Equal(t, 34, msg.Priority)
	assert.Equal(t, 4, msg.Facility)  // 34 >> 3 = 4
	assert.Equal(t, 2, msg.Severity)  // 34 & 7 = 2
	assert.Equal(t, "myhost", msg.Hostname)
	assert.Equal(t, "sshd", msg.AppName)
	assert.Equal(t, "1234", msg.ProcID)
	assert.Contains(t, msg.Message, "Accepted publickey")
	assert.Equal(t, 0, msg.Version)
}

func TestParse_RFC3164_NoTag(t *testing.T) {
	raw := []byte("<13>Jan 12 08:30:00 host.example.com This is the message body")
	msg, err := Parse(raw)
	require.NoError(t, err)
	assert.Equal(t, "host.example.com", msg.Hostname)
	assert.Contains(t, msg.Message, "This is the message body")
}

func TestParse_RFC3164_TagWithColon(t *testing.T) {
	raw := []byte("<14>Jan 15 09:00:00 router kernel: Firewall rule matched")
	msg, err := Parse(raw)
	require.NoError(t, err)
	assert.Equal(t, "router", msg.Hostname)
	assert.Equal(t, "kernel", msg.AppName)
	assert.Equal(t, "", msg.ProcID)
	assert.Contains(t, msg.Message, "Firewall rule matched")
}

func TestParse_RFC3164_WrongYear(t *testing.T) {
	// RFC 3164 has no year in the timestamp — parser uses current year.
	raw := []byte("<14>Jan  1 00:00:00 host app: message")
	msg, err := Parse(raw)
	require.NoError(t, err)
	assert.Equal(t, time.Now().Year(), msg.Timestamp.Year())
}

// -- RFC 5424 tests --

func TestParse_RFC5424_FullMessage(t *testing.T) {
	raw := []byte(`<165>1 2026-04-15T12:00:00Z myhostname myapp 1234 ID47 [exampleSDID@32473 iut="3" eventSource="Application" eventID="1011"] BOM'su root' failed for lonvick on /dev/pts/8`)
	msg, err := Parse(raw)
	require.NoError(t, err)
	assert.Equal(t, 165, msg.Priority)
	assert.Equal(t, 1, msg.Version)
	assert.Equal(t, "myhostname", msg.Hostname)
	assert.Equal(t, "myapp", msg.AppName)
	assert.Equal(t, "1234", msg.ProcID)
	assert.Equal(t, "ID47", msg.MsgID)
	assert.NotNil(t, msg.StructuredData)

	sd := msg.StructuredData["exampleSDID@32473"]
	assert.Equal(t, "3", sd["iut"])
	assert.Equal(t, "Application", sd["eventSource"])
	assert.Equal(t, "1011", sd["eventID"])
}

func TestParse_RFC5424_NilFields(t *testing.T) {
	// All header fields set to '-' (nil value in RFC 5424).
	raw := []byte("<0>1 - - - - - - nil field message")
	msg, err := Parse(raw)
	require.NoError(t, err)
	assert.Equal(t, 1, msg.Version)
	assert.Equal(t, "", msg.Hostname)
	assert.Equal(t, "", msg.AppName)
	assert.Equal(t, "", msg.ProcID)
	assert.Equal(t, "", msg.MsgID)
	assert.Nil(t, msg.StructuredData)
}

func TestParse_RFC5424_NoStructuredData(t *testing.T) {
	raw := []byte("<14>1 2026-04-15T12:00:00Z host app 100 - - message body")
	msg, err := Parse(raw)
	require.NoError(t, err)
	assert.Nil(t, msg.StructuredData)
	assert.Equal(t, "message body", msg.Message)
}

func TestParse_RFC5424_MultipleSDElements(t *testing.T) {
	raw := []byte(`<86>1 2026-01-01T00:00:00Z host app - - [a key="val1"][b key="val2"] msg`)
	msg, err := Parse(raw)
	require.NoError(t, err)
	assert.Equal(t, "val1", msg.StructuredData["a"]["key"])
	assert.Equal(t, "val2", msg.StructuredData["b"]["key"])
}

func TestParse_RFC5424_EscapedSDValue(t *testing.T) {
	raw := []byte(`<13>1 2026-01-01T00:00:00Z h a - - [id key="val\"with\"quotes"] msg`)
	msg, err := Parse(raw)
	require.NoError(t, err)
	assert.Equal(t, `val"with"quotes`, msg.StructuredData["id"]["key"])
}

func TestParse_RFC5424_Timestamp(t *testing.T) {
	raw := []byte("<14>1 2026-04-15T08:30:00.123456Z host app - - - msg")
	msg, err := Parse(raw)
	require.NoError(t, err)
	assert.Equal(t, 2026, msg.Timestamp.Year())
	assert.Equal(t, time.April, msg.Timestamp.Month())
	assert.Equal(t, 15, msg.Timestamp.Day())
}

// -- PRI tests --

func TestParsePRI_Valid(t *testing.T) {
	tests := []struct {
		input   string
		wantPRI int
		wantFac int
		wantSev int
	}{
		{"<0>rest", 0, 0, 0},
		{"<34>rest", 34, 4, 2},
		{"<191>rest", 191, 23, 7},
		{"<13>rest", 13, 1, 5},
	}
	for _, tc := range tests {
		pri, _, err := parsePRI(tc.input)
		require.NoError(t, err, "input %q", tc.input)
		assert.Equal(t, tc.wantPRI, pri)
		fac, sev := priComponents(pri)
		assert.Equal(t, tc.wantFac, fac)
		assert.Equal(t, tc.wantSev, sev)
	}
}

func TestParsePRI_Invalid(t *testing.T) {
	cases := []string{"no pri", "<>rest", "<192>rest", "<abc>rest", ""}
	for _, c := range cases {
		_, _, err := parsePRI(c)
		assert.Error(t, err, "expected error for %q", c)
	}
}

// -- Empty / malformed input --

func TestParse_EmptyMessage(t *testing.T) {
	_, err := Parse([]byte(""))
	assert.Error(t, err)
}

func TestParse_NoPRI(t *testing.T) {
	// No <PRI> prefix — parser returns message as-is without error.
	raw := []byte("plain log line with no syslog header")
	msg, err := Parse(raw)
	require.NoError(t, err)
	assert.Equal(t, "plain log line with no syslog header", msg.Message)
}

func TestParse_TrailingNewline(t *testing.T) {
	raw := []byte("<14>Jan  1 00:00:00 host app: msg\n")
	msg, err := Parse(raw)
	require.NoError(t, err)
	assert.NotContains(t, msg.Message, "\n")
}

// -- parseTag tests --

func TestParseTag_WithPID(t *testing.T) {
	tag, pid, _, hasTag := parseTag("nginx[123]: request received")
	assert.Equal(t, "nginx", tag)
	assert.Equal(t, "123", pid)
	assert.True(t, hasTag)
}

func TestParseTag_WithColon(t *testing.T) {
	tag, pid, _, hasTag := parseTag("kernel: oops")
	assert.Equal(t, "kernel", tag)
	assert.Equal(t, "", pid)
	assert.True(t, hasTag)
}

func TestParseTag_Plain(t *testing.T) {
	_, _, _, hasTag := parseTag("some message without tag marker")
	assert.False(t, hasTag)
}

// -- parseSD edge cases --

func TestParseSD_EmptyString(t *testing.T) {
	sd := parseSD("")
	assert.Empty(t, sd)
}

func TestParseSD_SingleElement(t *testing.T) {
	sd := parseSD(`[origin ip="192.168.1.1" port="514"]`)
	assert.Equal(t, "192.168.1.1", sd["origin"]["ip"])
	assert.Equal(t, "514", sd["origin"]["port"])
}

func TestParseSD_NoParams(t *testing.T) {
	sd := parseSD("[meta]")
	assert.Contains(t, sd, "meta")
	assert.Empty(t, sd["meta"])
}
