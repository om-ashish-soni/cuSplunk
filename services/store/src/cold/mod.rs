//! Cold tier — object storage (S3/GCS/Azure Blob).
//!
//! R2 status: API defined, implementation stubbed.
//! Full implementation ships in R3 under the `cold-tier` feature flag.
//!
//! The cold tier handles buckets older than 30 days. Buckets are stored as
//! Parquet files (Zstd-compressed) in an object store bucket. On first query
//! hit, the Parquet file is fetched, cached on the warm tier, and served.

use arrow::record_batch::RecordBatch;

use crate::error::StoreError;

/// Cold tier client — wraps the `object_store` crate.
///
/// Enabled at compile time with `--features cold-tier`.
pub struct ColdTier {
    _config: ColdTierConfig,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, Default)]
pub struct ColdTierConfig {
    #[serde(default = "default_provider")]
    pub provider: String, // "s3" | "gcs" | "azure"
    #[serde(default)]
    pub bucket: String,
    #[serde(default)]
    pub prefix: String,
    #[serde(default)]
    pub region: String,
}

fn default_provider() -> String {
    "s3".into()
}

impl ColdTier {
    pub fn new(config: ColdTierConfig) -> Self {
        Self { _config: config }
    }

    /// Fetch and return batches from cold storage.
    /// Returns `Unimplemented` until R3.
    pub async fn scan(
        &self,
        _index: &str,
        _start_ns: i64,
        _end_ns: i64,
        _columns: &[String],
    ) -> Result<Vec<RecordBatch>, StoreError> {
        Err(StoreError::Other(
            "Cold tier fetch not yet implemented (R3: feat/r3-c2-replication)".into(),
        ))
    }

    /// Tier a warm-tier bucket to cold storage.
    /// Returns `Unimplemented` until R3.
    pub async fn tier_bucket(
        &self,
        _bucket_id: &str,
        _parquet_bytes: &[u8],
    ) -> Result<String, StoreError> {
        Err(StoreError::Other(
            "Cold tier upload not yet implemented (R3)".into(),
        ))
    }
}
