// Package ingest is the cuSplunk ingest service.
//
// It accepts log events from Splunk Universal Forwarders (S2S), the HTTP Event
// Collector (HEC), and syslog (RFC 3164 / RFC 5424), batches them via the GPU
// parse queue, and forwards processed events to the store service.
package ingest
