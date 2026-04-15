//! Hot tier — in-memory ring buffer for recent events.
//!
//! Represents the GPU memory pool described in S2.2. In this implementation
//! we use system RAM so the service can run without a GPU. The interface is
//! identical to what a cuDF-backed pool would expose; swapping the backing
//! store in R3 requires no changes to the callers.
//!
//! Eviction policy: oldest batch first when `max_bytes` is exceeded or when
//! `evict_older_than()` is called by the retention background task.

use std::collections::VecDeque;
use std::sync::Arc;
use std::time::Instant;

use arrow::array::{
    ArrayRef, BinaryBuilder, Int64Builder, StringDictionaryBuilder,
};
use arrow::datatypes::{DataType, Field, Int32Type, Schema};
use arrow::record_batch::RecordBatch;

use crate::bucket::Event;
use crate::error::StoreError;

/// Default hot tier size: 512 MB (configurable via `HotTierConfig`).
pub const DEFAULT_MAX_BYTES: usize = 512 * 1024 * 1024;

/// A single in-memory batch with its routing metadata.
#[derive(Debug)]
pub struct HotBatch {
    pub index: String,
    pub start_time_ns: i64,
    pub end_time_ns: i64,
    /// Arrow RecordBatch with schema: _time, _raw, host, source, sourcetype.
    pub batch: RecordBatch,
    /// Wall-clock time when this batch was inserted.
    pub inserted_at: Instant,
    /// Approximate heap size used for eviction accounting.
    pub approx_bytes: usize,
}

/// In-memory ring buffer bounded by `max_bytes`.
///
/// Wrapped in `Arc<RwLock<HotTier>>` inside the server.
pub struct HotTier {
    entries: VecDeque<HotBatch>,
    current_bytes: usize,
    max_bytes: usize,
}

impl HotTier {
    pub fn new(max_bytes: usize) -> Self {
        Self {
            entries: VecDeque::new(),
            current_bytes: 0,
            max_bytes,
        }
    }

    // -------------------------------------------------------------------------
    // Insert
    // -------------------------------------------------------------------------

    /// Insert a batch. Returns any evicted batches (LRU — oldest first).
    ///
    /// Evicted batches are already on the warm tier and can be dropped.
    pub fn insert(&mut self, entry: HotBatch) -> Vec<HotBatch> {
        self.current_bytes += entry.approx_bytes;
        self.entries.push_back(entry);

        let mut evicted = Vec::new();
        while self.current_bytes > self.max_bytes {
            if let Some(oldest) = self.entries.pop_front() {
                self.current_bytes = self.current_bytes.saturating_sub(oldest.approx_bytes);
                evicted.push(oldest);
            } else {
                break;
            }
        }
        evicted
    }

    // -------------------------------------------------------------------------
    // Scan
    // -------------------------------------------------------------------------

    /// Return all batches for `index` whose time range overlaps `[start_ns, end_ns)`.
    /// Batches are projected to the requested columns; empty `columns` = all columns.
    pub fn scan(
        &self,
        index: &str,
        start_ns: i64,
        end_ns: i64,
        columns: &[String],
    ) -> Vec<RecordBatch> {
        self.entries
            .iter()
            .filter(|e| e.index == index)
            .filter(|e| e.end_time_ns > start_ns && (end_ns == 0 || e.start_time_ns < end_ns))
            .filter_map(|e| project_batch(&e.batch, columns).ok())
            .collect()
    }

    // -------------------------------------------------------------------------
    // Eviction
    // -------------------------------------------------------------------------

    /// Remove all batches inserted before `cutoff`. Returns the removed batches.
    pub fn evict_older_than(&mut self, cutoff: Instant) -> Vec<HotBatch> {
        let mut evicted = Vec::new();
        while let Some(front) = self.entries.front() {
            if front.inserted_at < cutoff {
                let batch = self.entries.pop_front().unwrap();
                self.current_bytes = self.current_bytes.saturating_sub(batch.approx_bytes);
                evicted.push(batch);
            } else {
                break; // ring buffer is insertion-ordered → once we hit a recent entry, done
            }
        }
        evicted
    }

    // -------------------------------------------------------------------------
    // Introspection
    // -------------------------------------------------------------------------

    pub fn current_bytes(&self) -> usize {
        self.current_bytes
    }

    pub fn batch_count(&self) -> usize {
        self.entries.len()
    }

    /// Fill ratio (0.0–1.0). Above ~0.80 the server starts applying backpressure.
    pub fn fill_ratio(&self) -> f64 {
        self.current_bytes as f64 / self.max_bytes as f64
    }
}

// -------------------------------------------------------------------------
// Build a hot-tier RecordBatch from ingested events
// -------------------------------------------------------------------------

/// Convert a slice of ingest `Event`s into an Arrow `RecordBatch` for the hot tier.
/// Schema: `_time` (Int64), `_raw` (Binary), `host`/`source`/`sourcetype` (Dict<Int32, Utf8>).
pub fn events_to_record_batch(events: &[Event]) -> Result<RecordBatch, StoreError> {
    let n = events.len();
    let dict_type = DataType::Dictionary(Box::new(DataType::Int32), Box::new(DataType::Utf8));

    let schema = Arc::new(Schema::new(vec![
        Field::new("_time", DataType::Int64, false),
        Field::new("_raw", DataType::Binary, false),
        Field::new("host", dict_type.clone(), false),
        Field::new("source", dict_type.clone(), false),
        Field::new("sourcetype", dict_type.clone(), false),
    ]));

    // _time
    let mut time_b = Int64Builder::with_capacity(n);
    for e in events {
        time_b.append_value(e.time_ns);
    }
    let time_arr = Arc::new(time_b.finish()) as ArrayRef;

    // _raw
    let total_raw: usize = events.iter().map(|e| e.raw.len()).sum();
    let mut raw_b = BinaryBuilder::with_capacity(n, total_raw);
    for e in events {
        raw_b.append_value(&e.raw);
    }
    let raw_arr = Arc::new(raw_b.finish()) as ArrayRef;

    // dict columns
    let host_arr = build_dict_array(events, |e| e.host.as_str())?;
    let source_arr = build_dict_array(events, |e| e.source.as_str())?;
    let st_arr = build_dict_array(events, |e| e.sourcetype.as_str())?;

    RecordBatch::try_new(schema, vec![time_arr, raw_arr, host_arr, source_arr, st_arr])
        .map_err(StoreError::Arrow)
}

fn build_dict_array<'a, F>(events: &'a [Event], get: F) -> Result<ArrayRef, StoreError>
where
    F: Fn(&'a Event) -> &'a str,
{
    let mut b: StringDictionaryBuilder<Int32Type> = StringDictionaryBuilder::new();
    for e in events {
        b.append_value(get(e));
    }
    Ok(Arc::new(b.finish()) as ArrayRef)
}

/// Approximate byte size of a RecordBatch for eviction accounting.
pub fn batch_approx_bytes(batch: &RecordBatch) -> usize {
    batch
        .columns()
        .iter()
        .map(|c| c.get_buffer_memory_size())
        .sum()
}

// -------------------------------------------------------------------------
// Column projection helper
// -------------------------------------------------------------------------

fn project_batch(batch: &RecordBatch, columns: &[String]) -> Result<RecordBatch, StoreError> {
    if columns.is_empty() {
        return Ok(batch.clone());
    }
    let indices: Result<Vec<usize>, _> = columns
        .iter()
        .map(|name| {
            batch
                .schema()
                .index_of(name)
                .map_err(|_| StoreError::ColumnNotFound(name.clone()))
        })
        .collect();
    let indices = indices?;

    let projected_schema = Arc::new(batch.schema().project(&indices)?);
    let projected_cols: Vec<ArrayRef> = indices.iter().map(|&i| batch.column(i).clone()).collect();

    RecordBatch::try_new(projected_schema, projected_cols).map_err(StoreError::Arrow)
}

// -------------------------------------------------------------------------
// Tests
// -------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn make_events(n: usize) -> Vec<Event> {
        (0..n)
            .map(|i| Event {
                time_ns: 1_000_000i64 * i as i64,
                raw: format!("raw-{}", i).into_bytes(),
                host: format!("h-{}", i % 2),
                source: "src".into(),
                sourcetype: "st".into(),
            })
            .collect()
    }

    fn make_hot_batch(index: &str, start_ns: i64, end_ns: i64, n: usize) -> HotBatch {
        let events = make_events(n);
        let batch = events_to_record_batch(&events).unwrap();
        let bytes = batch_approx_bytes(&batch);
        HotBatch {
            index: index.to_string(),
            start_time_ns: start_ns,
            end_time_ns: end_ns,
            batch,
            inserted_at: Instant::now(),
            approx_bytes: bytes,
        }
    }

    #[test]
    fn events_to_record_batch_schema() {
        let events = make_events(5);
        let batch = events_to_record_batch(&events).unwrap();
        assert_eq!(batch.num_rows(), 5);
        assert_eq!(batch.num_columns(), 5);
        let schema = batch.schema();
        assert!(schema.index_of("_time").is_ok());
        assert!(schema.index_of("_raw").is_ok());
        assert!(schema.index_of("host").is_ok());
    }

    #[test]
    fn insert_and_scan_hot_tier() {
        let mut tier = HotTier::new(DEFAULT_MAX_BYTES);
        tier.insert(make_hot_batch("main", 0, 1000, 10));
        tier.insert(make_hot_batch("main", 1000, 2000, 10));
        tier.insert(make_hot_batch("other", 0, 1000, 5));

        let batches = tier.scan("main", 500, 1500, &[]);
        assert_eq!(batches.len(), 2); // both main batches overlap [500, 1500)
    }

    #[test]
    fn scan_different_index_excluded() {
        let mut tier = HotTier::new(DEFAULT_MAX_BYTES);
        tier.insert(make_hot_batch("main", 0, 1000, 5));

        assert_eq!(tier.scan("other", 0, 1000, &[]).len(), 0);
    }

    #[test]
    fn scan_with_column_projection() {
        let mut tier = HotTier::new(DEFAULT_MAX_BYTES);
        tier.insert(make_hot_batch("main", 0, 1000, 5));

        let batches = tier.scan("main", 0, 1000, &["_time".into(), "host".into()]);
        assert_eq!(batches[0].num_columns(), 2);
    }

    #[test]
    fn eviction_on_capacity_breach() {
        // Set a tiny max to force eviction.
        let mut tier = HotTier::new(1); // 1 byte max → every insert evicts
        let b = make_hot_batch("main", 0, 100, 5);
        let b_size = b.approx_bytes;
        assert!(b_size > 1);

        let evicted = tier.insert(b);
        assert_eq!(evicted.len(), 1);
        // Tier is empty after eviction restores below limit.
        assert_eq!(tier.batch_count(), 0);
    }

    #[test]
    fn evict_older_than() {
        let mut tier = HotTier::new(DEFAULT_MAX_BYTES);
        let then = Instant::now();
        std::thread::sleep(std::time::Duration::from_millis(5));
        let now = Instant::now();

        // Insert a batch "in the past" by using a pre-captured Instant.
        tier.entries.push_back(HotBatch {
            index: "main".into(),
            start_time_ns: 0,
            end_time_ns: 100,
            batch: events_to_record_batch(&make_events(1)).unwrap(),
            inserted_at: then,
            approx_bytes: 100,
        });
        tier.current_bytes = 100;

        let evicted = tier.evict_older_than(now);
        assert_eq!(evicted.len(), 1);
        assert_eq!(tier.batch_count(), 0);
    }

    #[test]
    fn fill_ratio_tracks_usage() {
        let mut tier = HotTier::new(DEFAULT_MAX_BYTES);
        assert_eq!(tier.fill_ratio(), 0.0);
        tier.insert(make_hot_batch("main", 0, 100, 10));
        assert!(tier.fill_ratio() > 0.0);
        assert!(tier.fill_ratio() < 1.0);
    }
}
