use std::path::{Path, PathBuf};
use std::sync::Arc;

use arrow::datatypes::Schema;
use arrow::ipc::reader::FileReader;
use arrow::record_batch::RecordBatch;

use crate::bloom::BloomFilter;
use crate::bucket::meta::BucketMeta;
use crate::error::StoreError;

/// Opens an on-disk bucket for reading.
pub struct BucketReader {
    bucket_dir: PathBuf,
    pub meta: BucketMeta,
}

impl BucketReader {
    /// Open a bucket by its on-disk directory path.
    pub fn open(bucket_dir: impl AsRef<Path>) -> Result<Self, StoreError> {
        let bucket_dir = bucket_dir.as_ref().to_path_buf();
        let meta_bytes = std::fs::read(bucket_dir.join("meta.json"))?;
        let meta: BucketMeta = serde_json::from_slice(&meta_bytes)?;
        Ok(Self { bucket_dir, meta })
    }

    /// Read a single named column and return it as a single-column `RecordBatch`.
    ///
    /// Column files are: `_time.col`, `_raw.col`, `host.col`, `source.col`,
    /// `sourcetype.col`, and any extracted sub-columns under `extracted/`.
    pub fn read_column(&self, col_name: &str) -> Result<RecordBatch, StoreError> {
        let path = self.column_path(col_name);
        if !path.exists() {
            return Err(StoreError::ColumnNotFound(col_name.to_string()));
        }

        let file = std::fs::File::open(&path)?;
        let mut reader = FileReader::try_new(file, None)?;

        // Buckets always contain exactly one batch per column file.
        reader
            .next()
            .ok_or_else(|| StoreError::Other(format!("column file is empty: {}", col_name)))?
            .map_err(StoreError::Arrow)
    }

    /// Read multiple columns and assemble them into a single `RecordBatch`.
    ///
    /// The row count across all columns must match (guaranteed by `BucketWriter`).
    pub fn read_columns(&self, col_names: &[&str]) -> Result<RecordBatch, StoreError> {
        if col_names.is_empty() {
            return Err(StoreError::Other("col_names must not be empty".into()));
        }

        let mut fields = Vec::with_capacity(col_names.len());
        let mut arrays = Vec::with_capacity(col_names.len());

        for &name in col_names {
            let batch = self.read_column(name)?;
            let schema = batch.schema();
            fields.push(schema.field(0).clone());
            arrays.push(batch.column(0).clone());
        }

        let schema = Arc::new(Schema::new(fields));
        RecordBatch::try_new(schema, arrays).map_err(StoreError::Arrow)
    }

    /// Load the bucket's bloom filter.
    pub fn bloom_filter(&self) -> Result<BloomFilter, StoreError> {
        let path = self.bucket_dir.join("bloom.bin");
        let bytes = std::fs::read(&path)?;
        BloomFilter::from_bytes(&bytes)
            .ok_or_else(|| StoreError::BloomCorrupt(self.meta.bucket_id.clone()))
    }

    /// Returns true if the bloom filter indicates the bucket *might* contain
    /// the given token. Returns false if it definitely does not.
    pub fn bloom_contains(&self, token: &[u8]) -> Result<bool, StoreError> {
        let filter = self.bloom_filter()?;
        Ok(filter.contains(token))
    }

    // ---------------------------------------------------------------------------
    // Helpers
    // ---------------------------------------------------------------------------

    fn column_path(&self, col_name: &str) -> PathBuf {
        // Extracted sub-columns live under extracted/
        if col_name.contains('/') || (!self.meta.columns.contains(&col_name.to_string())) {
            self.bucket_dir
                .join("extracted")
                .join(format!("{}.col", col_name))
        } else {
            self.bucket_dir.join(format!("{}.col", col_name))
        }
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::bucket::writer::{BucketWriter, Event};
    use tempfile::TempDir;

    fn make_events(n: usize) -> Vec<Event> {
        (0..n)
            .map(|i| Event {
                time_ns: 1_700_000_000_000_000_000i64 + i as i64 * 1_000_000,
                raw: format!("msg=hello idx={}", i).into_bytes(),
                host: format!("host-{}", i % 3),
                source: "test".into(),
                sourcetype: "test_event".into(),
            })
            .collect()
    }

    fn write_and_open(tmp: &TempDir, n: usize) -> (BucketMeta, BucketReader) {
        let events = make_events(n);
        let writer = BucketWriter::new(tmp.path(), "test", 0, 3_600_000_000_000);
        let meta = writer.write(&events).unwrap();
        let bucket_dir = tmp.path().join(meta.dir_name());
        let reader = BucketReader::open(&bucket_dir).unwrap();
        (meta, reader)
    }

    #[test]
    fn read_time_column_row_count() {
        let tmp = TempDir::new().unwrap();
        let n = 20;
        let (meta, reader) = write_and_open(&tmp, n);
        let batch = reader.read_column("_time").unwrap();
        assert_eq!(batch.num_rows(), n);
        assert_eq!(meta.event_count, n as u64);
    }

    #[test]
    fn read_raw_column_content() {
        let tmp = TempDir::new().unwrap();
        let (_, reader) = write_and_open(&tmp, 5);
        let batch = reader.read_column("_raw").unwrap();
        assert_eq!(batch.num_rows(), 5);
        // First raw event should contain "msg=hello idx=0"
        let arr = batch
            .column(0)
            .as_any()
            .downcast_ref::<arrow::array::BinaryArray>()
            .unwrap();
        assert!(std::str::from_utf8(arr.value(0))
            .unwrap()
            .contains("msg=hello idx=0"));
    }

    #[test]
    fn read_dict_column_host() {
        let tmp = TempDir::new().unwrap();
        let n = 9; // 3 unique hosts each repeated 3 times
        let (_, reader) = write_and_open(&tmp, n);
        let batch = reader.read_column("host").unwrap();
        assert_eq!(batch.num_rows(), n);
    }

    #[test]
    fn read_multi_column_batch() {
        let tmp = TempDir::new().unwrap();
        let (_, reader) = write_and_open(&tmp, 10);
        let batch = reader.read_columns(&["_time", "host", "sourcetype"]).unwrap();
        assert_eq!(batch.num_rows(), 10);
        assert_eq!(batch.num_columns(), 3);
    }

    #[test]
    fn missing_column_returns_error() {
        let tmp = TempDir::new().unwrap();
        let (_, reader) = write_and_open(&tmp, 5);
        let result = reader.read_column("nonexistent");
        assert!(matches!(result, Err(StoreError::ColumnNotFound(_))));
    }

    #[test]
    fn bloom_filter_roundtrip() {
        let tmp = TempDir::new().unwrap();
        let (_, reader) = write_and_open(&tmp, 10);

        // Raw events are "msg=hello idx=N"; whitespace-tokenised → "msg=hello".
        assert!(reader.bloom_contains(b"msg=hello").unwrap());
        // Definitely absent token should return false (with overwhelming probability).
        assert!(!reader.bloom_contains(b"zzz_never_inserted_xqz").unwrap());
    }

    #[test]
    fn meta_roundtrip_from_disk() {
        let tmp = TempDir::new().unwrap();
        let (written_meta, reader) = write_and_open(&tmp, 7);
        assert_eq!(reader.meta.bucket_id, written_meta.bucket_id);
        assert_eq!(reader.meta.event_count, 7);
        assert_eq!(reader.meta.index, "test");
    }
}
