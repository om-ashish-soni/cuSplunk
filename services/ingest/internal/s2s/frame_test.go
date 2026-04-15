package s2s

import (
	"bytes"
	"encoding/binary"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// -- Frame parsing tests --

func TestReadFrame_ValidFrame(t *testing.T) {
	frame := BuildFrame(map[string]string{
		"_raw":          "Jan  1 00:00:00 host sshd[1]: Accepted",
		"_time":         "1735689600",
		"host":          "webserver-01",
		"source":        "/var/log/auth.log",
		"sourcetype":    "linux_secure",
		"MetaData:index": "main",
	})

	f, err := ReadFrame(bytes.NewReader(frame))
	require.NoError(t, err)
	assert.Equal(t, "Jan  1 00:00:00 host sshd[1]: Accepted", f.Raw())
	assert.Equal(t, "1735689600", f.Time())
	assert.Equal(t, "webserver-01", f.Host())
	assert.Equal(t, "/var/log/auth.log", f.Source())
	assert.Equal(t, "linux_secure", f.Sourcetype())
	assert.Equal(t, "main", f.Index())
}

func TestReadFrame_DefaultIndex(t *testing.T) {
	// Frame without MetaData:index should default to "main".
	frame := BuildFrame(map[string]string{
		"_raw":       "some event",
		"_time":      "0",
		"host":       "h",
		"source":     "s",
		"sourcetype": "st",
	})
	f, err := ReadFrame(bytes.NewReader(frame))
	require.NoError(t, err)
	assert.Equal(t, "main", f.Index())
}

func TestReadFrame_ZeroLength(t *testing.T) {
	var buf [4]byte // zero length
	_, err := ReadFrame(bytes.NewReader(buf[:]))
	require.Error(t, err)
	assert.Contains(t, err.Error(), "zero-length")
}

func TestReadFrame_TooLarge(t *testing.T) {
	var buf [4]byte
	binary.BigEndian.PutUint32(buf[:], maxFrameBytes+1)
	_, err := ReadFrame(bytes.NewReader(buf[:]))
	require.Error(t, err)
	assert.Contains(t, err.Error(), "too large")
}

func TestReadFrame_TruncatedPayload(t *testing.T) {
	// Length says 100 bytes but only 10 bytes follow.
	var buf bytes.Buffer
	var lenBuf [4]byte
	binary.BigEndian.PutUint32(lenBuf[:], 100)
	buf.Write(lenBuf[:])
	buf.Write(make([]byte, 10))
	_, err := ReadFrame(&buf)
	require.Error(t, err)
}

func TestReadFrame_MissingRaw(t *testing.T) {
	// Build frame without _raw field.
	frame := BuildFrame(map[string]string{
		"host":       "h",
		"sourcetype": "st",
	})
	_, err := ReadFrame(bytes.NewReader(frame))
	require.Error(t, err)
	assert.Contains(t, err.Error(), "_raw")
}

func TestReadFrame_UnterminatedKey(t *testing.T) {
	// Payload has no null terminator.
	var buf [4]byte
	binary.BigEndian.PutUint32(buf[:], 5)
	payload := []byte("hello") // no null
	data := append(buf[:], payload...)
	_, err := ReadFrame(bytes.NewReader(data))
	require.Error(t, err)
}

func TestReadFrame_MultipleFields(t *testing.T) {
	fields := map[string]string{
		"_raw":          "event data",
		"_time":         "1000000000.5",
		"host":          "host-42",
		"source":        "/var/log/messages",
		"sourcetype":    "syslog",
		"MetaData:index": "security",
		"custom_field":  "custom_value",
	}
	frame := BuildFrame(fields)
	f, err := ReadFrame(bytes.NewReader(frame))
	require.NoError(t, err)
	for k, want := range fields {
		assert.Equal(t, want, f.Fields[k], "field %q", k)
	}
}

// -- Handshake tests --

func TestReadHandshake_ValidMagic(t *testing.T) {
	err := ReadHandshake(bytes.NewReader(magicHello[:]))
	assert.NoError(t, err)
}

func TestReadHandshake_WrongMagic(t *testing.T) {
	bad := []byte{0xDE, 0xAD, 0xBE, 0xEF}
	err := ReadHandshake(bytes.NewReader(bad))
	require.Error(t, err)
	assert.Contains(t, err.Error(), "unexpected magic")
}

func TestReadHandshake_ShortRead(t *testing.T) {
	err := ReadHandshake(bytes.NewReader([]byte{0x00}))
	require.Error(t, err)
}

func TestWriteHandshakeAck(t *testing.T) {
	var buf bytes.Buffer
	err := WriteHandshakeAck(&buf)
	require.NoError(t, err)
	assert.Equal(t, magicAck[:], buf.Bytes())
}

// -- BuildFrame round-trip --

func TestBuildFrame_RoundTrip(t *testing.T) {
	input := map[string]string{
		"_raw":       "round trip test",
		"_time":      "123456789",
		"host":       "rt-host",
		"source":     "rt-source",
		"sourcetype": "rt-st",
	}
	data := BuildFrame(input)
	f, err := ReadFrame(bytes.NewReader(data))
	require.NoError(t, err)
	for k, want := range input {
		assert.Equal(t, want, f.Fields[k])
	}
}

func TestBuildFrame_LargeRaw(t *testing.T) {
	// 64 KB raw event — well within the 10 MB limit.
	raw := strings.Repeat("A", 64*1024)
	data := BuildFrame(map[string]string{
		"_raw":  raw,
		"_time": "0",
		"host":  "h",
	})
	f, err := ReadFrame(bytes.NewReader(data))
	require.NoError(t, err)
	assert.Equal(t, raw, f.Raw())
}

// -- WriteAck tests --

func TestWriteAck(t *testing.T) {
	var buf bytes.Buffer
	err := WriteAck(&buf, 42)
	require.NoError(t, err)
	seq := binary.BigEndian.Uint32(buf.Bytes())
	assert.Equal(t, uint32(42), seq)
}

func TestWriteAck_Zero(t *testing.T) {
	var buf bytes.Buffer
	err := WriteAck(&buf, 0)
	require.NoError(t, err)
	seq := binary.BigEndian.Uint32(buf.Bytes())
	assert.Equal(t, uint32(0), seq)
}
