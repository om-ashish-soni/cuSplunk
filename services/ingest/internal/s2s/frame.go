// Package s2s implements the Splunk-to-Splunk (S2S) wire protocol server.
//
// S2S v3 is the protocol used by Splunk Universal Forwarders to stream events
// to an indexer. cuSplunk accepts forwarder connections on TCP port 9997.
//
// Wire format per message:
//
//	[4 bytes: uint32 big-endian — total byte length of the following payload]
//	[payload: null-terminated key\x00value\x00 pairs]
//	[payload ends with an empty key: \x00 (double-null)]
//
// Required keys in every event frame:
//
//	_raw         — raw event string
//	_time        — Unix epoch seconds (string)
//	host         — originating host
//	source       — source identifier
//	sourcetype   — log format / parser name
//	MetaData:index — target index name
package s2s

import (
	"bytes"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
)

const (
	// maxFrameBytes is an upper bound on a single S2S frame (10 MB).
	// Real Splunk indexers impose similar limits.
	maxFrameBytes = 10 * 1024 * 1024

	// signatureLen is the length of the initial S2S handshake magic sent
	// by Universal Forwarders when they first connect.
	signatureLen = 4
)

// S2S connection-level signatures (version negotiation).
var (
	// magicHello is sent by the client to open a new forwarder session.
	magicHello = [4]byte{0x00, 0x01, 0x65, 0x58} // "\x00\x01eX"
	// magicAck is sent by the server to accept the session.
	magicAck = [4]byte{0x00, 0x01, 0x65, 0x59} // "\x00\x01eY"
)

// MagicHello returns the 4-byte client hello used to initiate an S2S session.
// Exported for use in integration tests and protocol compatibility tests.
func MagicHello() [4]byte { return magicHello }

// MagicAck returns the 4-byte server acknowledgement of a valid S2S hello.
func MagicAck() [4]byte { return magicAck }

// Frame holds the key-value pairs decoded from a single S2S event message.
type Frame struct {
	Fields map[string]string
}

// Raw returns the _raw field (original log line).
func (f *Frame) Raw() string { return f.Fields["_raw"] }

// Time returns the _time field as a string (Unix epoch seconds).
func (f *Frame) Time() string { return f.Fields["_time"] }

// Host returns the host field.
func (f *Frame) Host() string { return f.Fields["host"] }

// Source returns the source field.
func (f *Frame) Source() string { return f.Fields["source"] }

// Sourcetype returns the sourcetype field.
func (f *Frame) Sourcetype() string { return f.Fields["sourcetype"] }

// Index returns the MetaData:index field, defaulting to "main".
func (f *Frame) Index() string {
	if v, ok := f.Fields["MetaData:index"]; ok && v != "" {
		return v
	}
	return "main"
}

// ReadHandshake reads the 4-byte client hello magic from r.
// Returns an error if the magic is not the expected S2S hello signature.
func ReadHandshake(r io.Reader) error {
	var magic [signatureLen]byte
	if _, err := io.ReadFull(r, magic[:]); err != nil {
		return fmt.Errorf("s2s handshake: read magic: %w", err)
	}
	if magic != magicHello {
		return fmt.Errorf("s2s handshake: unexpected magic %x (want %x)", magic, magicHello)
	}
	return nil
}

// WriteHandshakeAck writes the 4-byte server ACK magic to w.
func WriteHandshakeAck(w io.Writer) error {
	_, err := w.Write(magicAck[:])
	return err
}

// ReadFrame reads one S2S event frame from r.
// Format: [4-byte big-endian length][payload of null-separated k\0v\0 pairs ending \0\0]
//
// Returns io.EOF if the remote cleanly closed the connection between frames.
// Any other error (including io.ErrUnexpectedEOF) indicates a parse failure.
func ReadFrame(r io.Reader) (*Frame, error) {
	// Read 4-byte payload length.
	var lenBuf [4]byte
	if _, err := io.ReadFull(r, lenBuf[:]); err != nil {
		// io.EOF here means the forwarder closed the connection cleanly
		// between frames — not an error condition.
		if errors.Is(err, io.EOF) {
			return nil, io.EOF
		}
		return nil, fmt.Errorf("s2s frame: read length: %w", err)
	}
	payloadLen := binary.BigEndian.Uint32(lenBuf[:])

	if payloadLen == 0 {
		return nil, fmt.Errorf("s2s frame: zero-length payload")
	}
	if payloadLen > maxFrameBytes {
		return nil, fmt.Errorf("s2s frame: payload too large (%d > %d)", payloadLen, maxFrameBytes)
	}

	// Read payload.
	payload := make([]byte, payloadLen)
	if _, err := io.ReadFull(r, payload); err != nil {
		return nil, fmt.Errorf("s2s frame: read payload: %w", err)
	}

	return parsePayload(payload)
}

// parsePayload decodes the null-delimited k\0v\0 payload into a Frame.
func parsePayload(payload []byte) (*Frame, error) {
	f := &Frame{Fields: make(map[string]string)}
	buf := payload

	for {
		// Read key (null-terminated).
		idx := bytes.IndexByte(buf, 0x00)
		if idx < 0 {
			return nil, fmt.Errorf("s2s frame: unterminated key in payload")
		}
		key := string(buf[:idx])
		buf = buf[idx+1:]

		// Empty key signals end of frame.
		if key == "" {
			break
		}

		// Read value (null-terminated).
		idx = bytes.IndexByte(buf, 0x00)
		if idx < 0 {
			return nil, fmt.Errorf("s2s frame: unterminated value for key %q", key)
		}
		val := string(buf[:idx])
		buf = buf[idx+1:]

		f.Fields[key] = val
	}

	if f.Raw() == "" {
		return nil, fmt.Errorf("s2s frame: missing _raw field")
	}
	return f, nil
}

// WriteAck writes a 4-byte sequence number ACK back to a connected forwarder.
// Forwarders expect periodic ACKs to confirm event receipt.
func WriteAck(w io.Writer, seq uint32) error {
	var buf [4]byte
	binary.BigEndian.PutUint32(buf[:], seq)
	_, err := w.Write(buf[:])
	return err
}

// BuildFrame serialises key-value pairs into an S2S frame payload (including
// the 4-byte length prefix). Used by tests to construct synthetic frames.
func BuildFrame(fields map[string]string) []byte {
	var payload bytes.Buffer
	for k, v := range fields {
		payload.WriteString(k)
		payload.WriteByte(0x00)
		payload.WriteString(v)
		payload.WriteByte(0x00)
	}
	payload.WriteByte(0x00) // end-of-frame double-null

	var out bytes.Buffer
	var lenBuf [4]byte
	binary.BigEndian.PutUint32(lenBuf[:], uint32(payload.Len()))
	out.Write(lenBuf[:])
	out.Write(payload.Bytes())
	return out.Bytes()
}
