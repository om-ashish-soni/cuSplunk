// Package event defines the shared RawEvent type produced by all ingest protocols.
package event

import "time"

// RawEvent is the normalized representation of a single log event after protocol
// parsing. Every ingest protocol (S2S, HEC, Syslog, Kafka) converts its wire
// format into a RawEvent before handing off to the GPU parse queue.
type RawEvent struct {
	// Time is the event timestamp. Protocols that carry no timestamp use
	// the ingest wall-clock time.
	Time time.Time

	// Raw is the original log line exactly as received (unmodified).
	Raw []byte

	// Host is the originating host name.
	Host string

	// Source is the source identifier (file path, input name, etc.).
	Source string

	// Sourcetype identifies the format / parser for this event.
	Sourcetype string

	// Index is the target index name. Defaults to "main" when not specified.
	Index string

	// Fields holds any additional key-value metadata extracted by the protocol
	// layer (e.g. S2S header fields, HEC metadata JSON, syslog SD-IDs).
	Fields map[string]string
}

// Protocol identifies which ingest protocol produced an event.
type Protocol uint8

const (
	ProtocolS2S    Protocol = iota // Splunk-to-Splunk (Universal Forwarder)
	ProtocolHEC                    // HTTP Event Collector
	ProtocolSyslog                 // RFC 3164 / RFC 5424
	ProtocolKafka                  // Kafka consumer
)
