//! Warm tier — NVMe-backed columnar bucket store.
//!
//! Wraps the bucket reader/writer from R1. In production, bucket reads go via
//! cuFile (GPUDirect Storage) when `gds_enabled = true`; without GDS the data
//! path is a standard `read(2)` into system memory.
//!
//! Write path: ingest → `write_events()` → bucket on disk → catalog entry added.
//! Read path: scan → catalog lookup → `BucketReader::read_columns()` per bucket.

use std::path::{Path, PathBuf};
use std::sync::Arc;

use arrow::array::RecordBatch;
use arrow::compute::cast;
use arrow::datatypes::{Field, Schema};

use crate::bucket::{BucketMeta, BucketReader, BucketWriter, Event};
use crate::catalog::BucketCatalog;
use crate::error::StoreError;

pub struct WarmTier {
    path: PathBuf,
}

impl WarmTier {
    pub fn new(path: impl AsRef<Path>) -> Self {
        Self {
            path: path.as_ref().to_path_buf(),
        }
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    // -------------------------------------------------------------------------
    // Write
    // -------------------------------------------------------------------------

    /// Persist `events` as a new bucket on the warm tier.
    /// Events must be sorted ascending by `time_ns`.
    pub fn write_events(
        &self,
        index: &str,
        events: &[Event],
    ) -> Result<BucketMeta, StoreError> {
        if events.is_empty() {
            return Err(StoreError::Other("events must not be empty".into()));
        }
        let start_ns = events.first().unwrap().time_ns;
        let end_ns = events.last().unwrap().time_ns + 1;

        let writer = BucketWriter::new(&self.path, index, start_ns, end_ns);
        writer.write(events)
    }

    // -------------------------------------------------------------------------
    // Scan
    // -------------------------------------------------------------------------

    /// Read matching columns from all warm-tier buckets that overlap the time
    /// range. Uses the catalog for bucket discovery; falls back to a directory
    /// scan if the catalog is not provided.
    ///
    /// `columns` — requested column names. Empty → returns `_time` + `_raw` +
    /// `host` + `source` + `sourcetype`.
    pub fn scan(
        &self,
        catalog: &BucketCatalog,
        index: &str,
        start_ns: i64,
        end_ns: i64,
        columns: &[String],
    ) -> Result<Vec<RecordBatch>, StoreError> {
        let effective_cols: Vec<&str> = if columns.is_empty() {
            vec!["_time", "_raw", "host", "source", "sourcetype"]
        } else {
            columns.iter().map(String::as_str).collect()
        };

        let metas = catalog.scan_range(index, start_ns, end_ns);
        let mut results = Vec::with_capacity(metas.len());

        for meta in metas {
            let bucket_dir = self.path.join(meta.dir_name());
            if !bucket_dir.exists() {
                tracing::warn!(
                    bucket_id = %meta.bucket_id,
                    "Catalog references a bucket directory that no longer exists — skipping"
                );
                continue;
            }

            let reader = BucketReader::open(&bucket_dir)?;

            // Column projection: only request columns that exist in this bucket.
            let available: Vec<&str> = effective_cols
                .iter()
                .copied()
                .filter(|&c| meta.columns.contains(&c.to_string()))
                .collect();

            if available.is_empty() {
                continue;
            }

            match reader.read_columns(&available).and_then(decode_dict_columns) {
                Ok(batch) => results.push(batch),
                Err(e) => {
                    tracing::warn!(
                        bucket_id = %meta.bucket_id,
                        error = %e,
                        "Failed to read bucket during scan — skipping"
                    );
                }
            }
        }

        Ok(results)
    }

    // -------------------------------------------------------------------------
    // Tombstone / Delete
    // -------------------------------------------------------------------------

    /// Write a `tombstone.json` file inside the bucket directory.
    pub fn write_tombstone(
        &self,
        meta: &BucketMeta,
        tombstoned_at: i64,
    ) -> Result<(), StoreError> {
        let dir = self.path.join(meta.dir_name());
        if !dir.exists() {
            return Ok(()); // already gone
        }
        let ts = serde_json::json!({
            "bucket_id": meta.bucket_id,
            "tombstoned_at": tombstoned_at,
        });
        std::fs::write(dir.join("tombstone.json"), ts.to_string().as_bytes())?;
        Ok(())
    }

    /// Hard-delete a bucket directory from disk.
    pub fn hard_delete(&self, meta: &BucketMeta) -> Result<(), StoreError> {
        let dir = self.path.join(meta.dir_name());
        if dir.exists() {
            std::fs::remove_dir_all(&dir)?;
            tracing::info!(bucket_id = %meta.bucket_id, "Hard deleted bucket");
        }
        Ok(())
    }
}

// -------------------------------------------------------------------------
// IPC serialisation helper (shared by warm scan + server streaming)
// -------------------------------------------------------------------------

/// Cast dictionary-encoded columns to their plain value type.
///
/// Dictionary encoding is a storage optimisation. When streaming batches via
/// Arrow IPC the dict-tracking protocol can break when columns originate from
/// independent IPC files (each with their own dict IDs). Casting to plain
/// arrays is safe — the query executor never needs the dict encoding.
pub fn decode_dict_columns(batch: RecordBatch) -> Result<RecordBatch, StoreError> {
    use arrow::datatypes::DataType;

    let schema = batch.schema();
    let mut fields: Vec<Field> = Vec::with_capacity(schema.fields().len());
    let mut arrays = Vec::with_capacity(schema.fields().len());

    for (field, col) in schema.fields().iter().zip(batch.columns().iter()) {
        match field.data_type() {
            DataType::Dictionary(_, value_type) => {
                let target = value_type.as_ref().clone();
                let plain = cast(col.as_ref(), &target)?;
                fields.push(Field::new(field.name(), target, field.is_nullable()));
                arrays.push(plain);
            }
            _ => {
                fields.push(field.as_ref().clone());
                arrays.push(col.clone());
            }
        }
    }

    RecordBatch::try_new(Arc::new(Schema::new(fields)), arrays).map_err(StoreError::Arrow)
}

/// Serialise a `RecordBatch` as Arrow IPC stream-format bytes.
pub fn batch_to_ipc_bytes(batch: &RecordBatch) -> Result<Vec<u8>, StoreError> {
    use arrow::ipc::writer::StreamWriter;

    let mut buf = Vec::new();
    let mut writer = StreamWriter::try_new(&mut buf, batch.schema().as_ref())?;
    writer.write(batch)?;
    writer.finish()?;
    Ok(buf)
}

/// Deserialise Arrow IPC stream-format bytes back to a `RecordBatch`.
/// Used in tests to verify round-trip fidelity.
pub fn ipc_bytes_to_batch(bytes: &[u8]) -> Result<Vec<RecordBatch>, StoreError> {
    use arrow::ipc::reader::StreamReader;
    use std::io::Cursor;
    let cursor = Cursor::new(bytes);
    let reader = StreamReader::try_new(cursor, None)?;
    reader
        .collect::<Result<Vec<_>, _>>()
        .map_err(StoreError::Arrow)
}

// -------------------------------------------------------------------------
// Tests
// -------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn sample_events(n: usize) -> Vec<Event> {
        (0..n)
            .map(|i| Event {
                time_ns: 1_700_000_000_000_000_000i64 + i as i64 * 1_000_000,
                raw: format!("action=accept src={}", i).into_bytes(),
                host: format!("fw-{}", i % 3),
                source: "syslog".into(),
                sourcetype: "firewall".into(),
            })
            .collect()
    }

    fn setup(tmp: &TempDir) -> (WarmTier, BucketCatalog) {
        let tier = WarmTier::new(tmp.path());
        let cat = BucketCatalog::build_from_dir(tmp.path()).unwrap();
        (tier, cat)
    }

    #[test]
    fn write_and_scan_returns_events() {
        let tmp = TempDir::new().unwrap();
        let (tier, mut cat) = setup(&tmp);
        let events = sample_events(20);
        let meta = tier.write_events("main", &events).unwrap();
        cat.add(meta);

        let batches = tier
            .scan(&cat, "main", 0, i64::MAX, &[])
            .unwrap();
        assert_eq!(batches.len(), 1);
        assert_eq!(batches[0].num_rows(), 20);
    }

    #[test]
    fn scan_with_column_projection() {
        let tmp = TempDir::new().unwrap();
        let (tier, mut cat) = setup(&tmp);
        let meta = tier.write_events("main", &sample_events(10)).unwrap();
        cat.add(meta);

        let batches = tier
            .scan(&cat, "main", 0, i64::MAX, &["_time".into(), "host".into()])
            .unwrap();
        assert_eq!(batches[0].num_columns(), 2);
    }

    #[test]
    fn scan_time_range_excludes_non_overlapping_bucket() {
        let tmp = TempDir::new().unwrap();
        let tier = WarmTier::new(tmp.path());
        let mut cat = BucketCatalog::new();

        // Write two non-overlapping buckets.
        let e1 = sample_events(5); // times near 1_700_000_000_000_000_000
        let m1 = tier.write_events("main", &e1).unwrap();
        let far_future = 9_000_000_000_000_000_000i64;
        let e2: Vec<Event> = (0..5)
            .map(|i| Event {
                time_ns: far_future + i,
                raw: b"x".to_vec(),
                host: "h".into(),
                source: "s".into(),
                sourcetype: "st".into(),
            })
            .collect();
        let m2 = tier.write_events("main", &e2).unwrap();

        cat.add(m1);
        cat.add(m2);

        // Only query early time range.
        let batches = tier
            .scan(&cat, "main", 0, 2_000_000_000_000_000_000i64, &[])
            .unwrap();
        assert_eq!(batches.len(), 1);
    }

    #[test]
    fn write_and_hard_delete() {
        let tmp = TempDir::new().unwrap();
        let tier = WarmTier::new(tmp.path());
        let meta = tier.write_events("main", &sample_events(5)).unwrap();
        let bucket_dir = tmp.path().join(meta.dir_name());

        assert!(bucket_dir.exists());
        tier.hard_delete(&meta).unwrap();
        assert!(!bucket_dir.exists());
    }

    #[test]
    fn tombstone_file_created() {
        let tmp = TempDir::new().unwrap();
        let tier = WarmTier::new(tmp.path());
        let meta = tier.write_events("main", &sample_events(5)).unwrap();

        tier.write_tombstone(&meta, 1_000_000).unwrap();
        let ts_path = tmp.path().join(meta.dir_name()).join("tombstone.json");
        assert!(ts_path.exists());
    }

    #[test]
    fn ipc_roundtrip() {
        let tmp = TempDir::new().unwrap();
        let (tier, mut cat) = setup(&tmp);
        let meta = tier.write_events("main", &sample_events(8)).unwrap();
        cat.add(meta);

        let batches = tier.scan(&cat, "main", 0, i64::MAX, &[]).unwrap();
        let bytes = batch_to_ipc_bytes(&batches[0]).unwrap();
        let recovered = ipc_bytes_to_batch(&bytes).unwrap();

        assert_eq!(recovered.len(), 1);
        assert_eq!(recovered[0].num_rows(), 8);
    }
}
