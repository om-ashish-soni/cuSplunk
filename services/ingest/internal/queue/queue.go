// Package queue provides the event queue between protocol servers and the GPU
// parse pipeline.
//
// R1 stub: uses a plain Go channel. R2 replaces this with a CUDA pinned-memory
// ring buffer that batches at 10,000 events OR 100 ms (whichever comes first).
package queue

import (
	"context"
	"fmt"
	"time"

	"github.com/om-ashish-soni/cusplunk/ingest/internal/event"
)

// Queue is the interface both the stub and the real GPU queue implement.
// Protocol servers call Enqueue; the GPU batch processor calls Drain.
type Queue interface {
	// Enqueue adds an event. Blocks when the queue is full (backpressure).
	Enqueue(ctx context.Context, e event.RawEvent) error

	// Drain returns a channel that yields batches ready for GPU processing.
	// Each batch contains up to BatchSize events or is flushed after FlushInterval.
	Drain() <-chan []event.RawEvent

	// Close shuts down the queue and flushes any pending events.
	Close() error
}

// ChannelQueue is the R1 stub implementation backed by a buffered Go channel.
type ChannelQueue struct {
	ch     chan event.RawEvent
	out    chan []event.RawEvent
	done   chan struct{}
	size   int
}

// NewChannelQueue creates a ChannelQueue with capacity cap.
func NewChannelQueue(cap int) *ChannelQueue {
	q := &ChannelQueue{
		ch:   make(chan event.RawEvent, cap),
		out:  make(chan []event.RawEvent, 16),
		done: make(chan struct{}),
		size: cap,
	}
	go q.batcher()
	return q
}

func (q *ChannelQueue) Enqueue(ctx context.Context, e event.RawEvent) error {
	select {
	case q.ch <- e:
		return nil
	case <-ctx.Done():
		return fmt.Errorf("enqueue: %w", ctx.Err())
	case <-q.done:
		return fmt.Errorf("enqueue: queue closed")
	}
}

func (q *ChannelQueue) Drain() <-chan []event.RawEvent { return q.out }

func (q *ChannelQueue) Close() error {
	close(q.done)
	return nil
}

// batcher collects up to 10,000 events OR flushes every 100 ms, whichever
// comes first. R2 will replace this with the real CUDA ring-buffer accumulator.
func (q *ChannelQueue) batcher() {
	const (
		batchMax      = 10_000
		flushInterval = 100 * time.Millisecond
	)
	batch := make([]event.RawEvent, 0, batchMax)
	ticker := time.NewTicker(flushInterval)
	defer ticker.Stop()

	flush := func() {
		if len(batch) > 0 {
			q.out <- batch
			batch = make([]event.RawEvent, 0, batchMax)
		}
	}

	for {
		select {
		case e, ok := <-q.ch:
			if !ok {
				flush()
				close(q.out)
				return
			}
			batch = append(batch, e)
			if len(batch) >= batchMax {
				flush()
			}
		case <-ticker.C:
			flush()
		case <-q.done:
			flush()
			close(q.out)
			return
		}
	}
}
