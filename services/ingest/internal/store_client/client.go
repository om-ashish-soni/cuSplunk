// Package store_client provides a gRPC client for the cuSplunk store service.
//
// In R2, the ingest pipeline uses this client to forward processed event batches
// (Arrow IPC) to the store service after GPU parsing and LZ4 compression.
//
//go:generate /tmp/protoc/bin/protoc --plugin=protoc-gen-go=$(go env GOPATH)/bin/protoc-gen-go --plugin=protoc-gen-go-grpc=$(go env GOPATH)/bin/protoc-gen-go-grpc --go_out=../../../../libs/proto/go/storepb --go_opt=paths=source_relative --go-grpc_out=../../../../libs/proto/go/storepb --go-grpc_opt=paths=source_relative --proto_path=../../../../libs/proto ../../../../libs/proto/store.proto
package store_client

import (
	"context"
	"fmt"
	"time"

	"go.uber.org/zap"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/status"

	storepb "github.com/om-ashish-soni/cusplunk/proto/storepb"
	"github.com/om-ashish-soni/cusplunk/ingest/internal/event"
)

// StoreClient is the interface the ingest pipeline uses to write events to the
// store service. Both the real gRPC implementation and the test no-op implement
// this interface.
type StoreClient interface {
	// Write forwards a batch of events to the store service.
	Write(ctx context.Context, events []event.RawEvent) error
	// Close tears down the connection.
	Close() error
}

// Config configures the gRPC store client.
type Config struct {
	// Address is the store service address (host:port). Default: "localhost:50051".
	Address string
	// DialTimeout is the maximum time to wait for the initial connection.
	DialTimeout time.Duration
	// WriteTimeout is applied to each Write RPC call.
	WriteTimeout time.Duration
	// MaxBatchSize is the maximum number of events per WriteRequest. Larger
	// batches are split automatically.
	MaxBatchSize int
}

func (c *Config) withDefaults() Config {
	out := *c
	if out.Address == "" {
		out.Address = "localhost:50051"
	}
	if out.DialTimeout == 0 {
		out.DialTimeout = 5 * time.Second
	}
	if out.WriteTimeout == 0 {
		out.WriteTimeout = 30 * time.Second
	}
	if out.MaxBatchSize == 0 {
		out.MaxBatchSize = 5_000
	}
	return out
}

// grpcStoreClient is the production gRPC implementation of StoreClient.
type grpcStoreClient struct {
	cfg  Config
	conn *grpc.ClientConn
	stub storepb.StoreClient
	log  *zap.Logger
}

// New dials the store service and returns a StoreClient. The caller must call
// Close when done.
func New(cfg Config, log *zap.Logger) (StoreClient, error) {
	cfg = cfg.withDefaults()

	dialCtx, cancel := context.WithTimeout(context.Background(), cfg.DialTimeout)
	defer cancel()

	conn, err := grpc.DialContext(dialCtx, cfg.Address,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithBlock(),
	)
	if err != nil {
		return nil, fmt.Errorf("store_client: dial %s: %w", cfg.Address, err)
	}

	return &grpcStoreClient{
		cfg:  cfg,
		conn: conn,
		stub: storepb.NewStoreClient(conn),
		log:  log,
	}, nil
}

// Write converts []event.RawEvent to proto Events and calls store.Write().
// Large batches are automatically split to respect MaxBatchSize.
func (c *grpcStoreClient) Write(ctx context.Context, events []event.RawEvent) error {
	if len(events) == 0 {
		return nil
	}

	// Determine index from the first event (batch is always single-index).
	index := events[0].Index
	if index == "" {
		index = "main"
	}

	for start := 0; start < len(events); start += c.cfg.MaxBatchSize {
		end := start + c.cfg.MaxBatchSize
		if end > len(events) {
			end = len(events)
		}
		chunk := events[start:end]

		if err := c.writeBatch(ctx, index, chunk); err != nil {
			return err
		}
	}
	return nil
}

func (c *grpcStoreClient) writeBatch(ctx context.Context, index string, events []event.RawEvent) error {
	protoEvents := make([]*storepb.Event, 0, len(events))
	for _, e := range events {
		pe := &storepb.Event{
			TimeNs:     e.Time.UnixNano(),
			Raw:        e.Raw,
			Host:       e.Host,
			Source:     e.Source,
			Sourcetype: e.Sourcetype,
			Index:      e.Index,
			Fields:     e.Fields,
		}
		protoEvents = append(protoEvents, pe)
	}

	req := &storepb.WriteRequest{
		Index:  index,
		Events: protoEvents,
	}

	writeCtx, cancel := context.WithTimeout(ctx, c.cfg.WriteTimeout)
	defer cancel()

	resp, err := c.stub.Write(writeCtx, req)
	if err != nil {
		if st, ok := status.FromError(err); ok {
			if st.Code() == codes.Unavailable {
				return fmt.Errorf("store_client: store unavailable: %w", err)
			}
		}
		return fmt.Errorf("store_client: write: %w", err)
	}

	c.log.Debug("store write ok",
		zap.String("index", index),
		zap.Uint64("events_written", resp.EventsWritten),
		zap.String("bucket_id", resp.BucketId),
	)
	return nil
}

func (c *grpcStoreClient) Close() error {
	return c.conn.Close()
}

// ---------------------------------------------------------------------------
// NoOpStoreClient — used in unit tests and CI without a real store service.
// ---------------------------------------------------------------------------

// NoOpStoreClient discards all writes. It records the number of events
// received so tests can assert that events reached the client.
type NoOpStoreClient struct {
	written int64
}

func NewNoOp() *NoOpStoreClient { return &NoOpStoreClient{} }

func (n *NoOpStoreClient) Write(_ context.Context, events []event.RawEvent) error {
	n.written += int64(len(events))
	return nil
}

func (n *NoOpStoreClient) Close() error { return nil }

// Written returns the total number of events received by Write calls.
func (n *NoOpStoreClient) Written() int64 { return n.written }
