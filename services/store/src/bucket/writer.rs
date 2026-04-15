use std::path::{Path, PathBuf};
use std::sync::Arc;

use arrow::array::{
    ArrayRef, BinaryBuilder, Int64Builder, StringDictionaryBuilder,
};
use arrow::datatypes::{DataType, Field, Int32Type, Schema};
use arrow::ipc::writer::FileWriter;
use arrow::record_batch::RecordBatch;

use crate::bloom::BloomFilter;
use crate::bucket::meta::BucketMeta;
use crate::error::StoreError;

/// A single event to be stored.
#[derive(Debug, Clone)]
pub struct Event {
    /// Unix nanoseconds.
    pub time_ns: i64,
    /// Raw event bytes. (nvCOMP compression applied in R2 GPU pipeline.)
    pub raw: Vec<u8>,
    pub host: String,
    pub source: String,
    pub sourcetype: String,
}

/// Writes a batch of events to a new bucket directory.
///
/// Usage:
/// ```ignore
/// let events: Vec<Event> = collect_events();
/// let writer = BucketWriter::new("/var/lib/cusplunk/warm", "main", 0, 3_600_000_000_000);
/// let meta = writer.write(&events)?;
/// ```
pub struct BucketWriter {
    base_dir: PathBuf,
    meta: BucketMeta,
    /// False-positive rate for the bloom filter.
    bloom_fpr: f64,
}

impl BucketWriter {
    pub fn new(
        base_dir: impl AsRef<Path>,
        index: &str,
        start_time_ns: i64,
        end_time_ns: i64,
    ) -> Self {
        Self {
            base_dir: base_dir.as_ref().to_path_buf(),
            meta: BucketMeta::new(index, start_time_ns, end_time_ns),
            bloom_fpr: 0.01,
        }
    }

    /// Override the bloom filter false-positive rate (default: 1%).
    pub fn with_bloom_fpr(mut self, fpr: f64) -> Self {
        self.bloom_fpr = fpr;
        self
    }

    /// Write `events` to disk. Returns the finalised `BucketMeta`.
    pub fn write(mut self, events: &[Event]) -> Result<BucketMeta, StoreError> {
        // Events must be sorted ascending by time for correct scan semantics.
        // Caller is responsible; we assert in debug builds.
        debug_assert!(
            events.windows(2).all(|w| w[0].time_ns <= w[1].time_ns),
            "events must be sorted ascending by time_ns"
        );

        if events.is_empty() {
            return Err(StoreError::Other("cannot write an empty event batch".into()));
        }

        let bucket_dir = self.base_dir.join(self.meta.dir_name());
        std::fs::create_dir_all(&bucket_dir)?;

        let n = events.len();

        write_time_col(&bucket_dir, events)?;
        write_raw_col(&bucket_dir, events)?;
        write_dict_col(&bucket_dir, "host", events, |e| e.host.as_str())?;
        write_dict_col(&bucket_dir, "source", events, |e| e.source.as_str())?;
        write_dict_col(&bucket_dir, "sourcetype", events, |e| e.sourcetype.as_str())?;

        write_bloom(&bucket_dir, events, self.bloom_fpr)?;

        // Finalise metadata
        self.meta.event_count = n as u64;
        self.meta.size_bytes = dir_size_bytes(&bucket_dir)?;

        let meta_json = serde_json::to_string_pretty(&self.meta)?;
        std::fs::write(bucket_dir.join("meta.json"), meta_json.as_bytes())?;

        Ok(self.meta)
    }
}

// ---------------------------------------------------------------------------
// Column writers
// ---------------------------------------------------------------------------

fn write_time_col(bucket_dir: &Path, events: &[Event]) -> Result<(), StoreError> {
    let mut builder = Int64Builder::with_capacity(events.len());
    for e in events {
        builder.append_value(e.time_ns);
    }
    let array = Arc::new(builder.finish()) as ArrayRef;
    let schema = Arc::new(Schema::new(vec![
        Field::new("_time", DataType::Int64, false),
    ]));
    write_col_file(bucket_dir, "_time", schema, array)
}

fn write_raw_col(bucket_dir: &Path, events: &[Event]) -> Result<(), StoreError> {
    let total_bytes: usize = events.iter().map(|e| e.raw.len()).sum();
    let mut builder = BinaryBuilder::with_capacity(events.len(), total_bytes);
    for e in events {
        builder.append_value(&e.raw);
    }
    let array = Arc::new(builder.finish()) as ArrayRef;
    let schema = Arc::new(Schema::new(vec![
        Field::new("_raw", DataType::Binary, false),
    ]));
    write_col_file(bucket_dir, "_raw", schema, array)
}

fn write_dict_col<'a, F>(
    bucket_dir: &Path,
    col_name: &str,
    events: &'a [Event],
    get: F,
) -> Result<(), StoreError>
where
    F: Fn(&'a Event) -> &'a str,
{
    let mut builder: StringDictionaryBuilder<Int32Type> = StringDictionaryBuilder::new();
    for e in events {
        builder.append_value(get(e));
    }
    let array = Arc::new(builder.finish()) as ArrayRef;
    let dict_type = DataType::Dictionary(
        Box::new(DataType::Int32),
        Box::new(DataType::Utf8),
    );
    let schema = Arc::new(Schema::new(vec![
        Field::new(col_name, dict_type, false),
    ]));
    write_col_file(bucket_dir, col_name, schema, array)
}

fn write_col_file(
    bucket_dir: &Path,
    col_name: &str,
    schema: Arc<Schema>,
    array: ArrayRef,
) -> Result<(), StoreError> {
    let batch = RecordBatch::try_new(schema.clone(), vec![array])?;
    let file = std::fs::File::create(bucket_dir.join(format!("{}.col", col_name)))?;
    let mut writer = FileWriter::try_new(file, &schema)?;
    writer.write(&batch)?;
    writer.finish()?;
    Ok(())
}

// ---------------------------------------------------------------------------
// Bloom filter
// ---------------------------------------------------------------------------

fn write_bloom(bucket_dir: &Path, events: &[Event], fpr: f64) -> Result<(), StoreError> {
    // Tokenise every raw event by whitespace — bloom filter covers all tokens.
    let tokens: Vec<Vec<u8>> = events
        .iter()
        .flat_map(|e| {
            let s = std::str::from_utf8(&e.raw).unwrap_or("");
            s.split_whitespace()
                .map(|t| t.as_bytes().to_vec())
                .collect::<Vec<_>>()
        })
        .collect();

    let expected = tokens.len().max(1000);
    let mut filter = BloomFilter::with_fpr(expected, fpr);
    for token in &tokens {
        filter.insert(token);
    }

    std::fs::write(bucket_dir.join("bloom.bin"), filter.to_bytes())?;
    Ok(())
}

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------

fn dir_size_bytes(path: &Path) -> Result<u64, StoreError> {
    let mut total = 0u64;
    for entry in std::fs::read_dir(path)? {
        let entry = entry?;
        let meta = entry.metadata()?;
        if meta.is_file() {
            total += meta.len();
        }
    }
    Ok(total)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn sample_events(n: usize) -> Vec<Event> {
        (0..n)
            .map(|i| Event {
                time_ns: 1_700_000_000_000_000_000i64 + i as i64 * 1_000_000,
                raw: format!("src_ip=10.0.0.{} action=accept bytes={}", i % 256, i * 100)
                    .into_bytes(),
                host: format!("fw-{}", i % 4),
                source: "syslog".into(),
                sourcetype: "firewall".into(),
            })
            .collect()
    }

    #[test]
    fn write_creates_expected_files() {
        let tmp = TempDir::new().unwrap();
        let events = sample_events(10);
        let writer = BucketWriter::new(tmp.path(), "main", 0, 3_600_000_000_000);
        let meta = writer.write(&events).unwrap();

        let bucket_dir = tmp.path().join(meta.dir_name());
        assert!(bucket_dir.join("meta.json").exists(), "meta.json missing");
        assert!(bucket_dir.join("_time.col").exists(), "_time.col missing");
        assert!(bucket_dir.join("_raw.col").exists(), "_raw.col missing");
        assert!(bucket_dir.join("host.col").exists(), "host.col missing");
        assert!(bucket_dir.join("source.col").exists(), "source.col missing");
        assert!(bucket_dir.join("sourcetype.col").exists(), "sourcetype.col missing");
        assert!(bucket_dir.join("bloom.bin").exists(), "bloom.bin missing");
    }

    #[test]
    fn write_meta_event_count() {
        let tmp = TempDir::new().unwrap();
        let n = 42;
        let events = sample_events(n);
        let writer = BucketWriter::new(tmp.path(), "firewall", 0, 3_600_000_000_000);
        let meta = writer.write(&events).unwrap();

        assert_eq!(meta.event_count, n as u64);
        assert_eq!(meta.index, "firewall");
        assert!(meta.size_bytes > 0);
    }

    #[test]
    fn write_empty_events_returns_error() {
        let tmp = TempDir::new().unwrap();
        let writer = BucketWriter::new(tmp.path(), "main", 0, 3_600_000_000_000);
        assert!(writer.write(&[]).is_err());
    }
}
