use serde::{Deserialize, Serialize};
use uuid::Uuid;

pub const SCHEMA_VERSION: u32 = 1;

/// Metadata persisted alongside each bucket as `meta.json`.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct BucketMeta {
    pub bucket_id: String,
    pub index: String,
    /// Unix nanoseconds, inclusive.
    pub start_time_ns: i64,
    /// Unix nanoseconds, exclusive.
    pub end_time_ns: i64,
    pub event_count: u64,
    /// Total on-disk size in bytes, computed after write.
    pub size_bytes: u64,
    pub schema_version: u32,
    /// Whether `_raw.col` is nvCOMP-compressed (false until R2 GPU pipeline).
    pub compressed: bool,
    /// Columns present in this bucket (excluding extracted/ sub-columns).
    pub columns: Vec<String>,
}

impl BucketMeta {
    pub fn new(index: &str, start_time_ns: i64, end_time_ns: i64) -> Self {
        Self {
            bucket_id: Uuid::new_v4().to_string(),
            index: index.to_string(),
            start_time_ns,
            end_time_ns,
            event_count: 0,
            size_bytes: 0,
            schema_version: SCHEMA_VERSION,
            compressed: false,
            columns: vec![
                "_time".into(),
                "_raw".into(),
                "host".into(),
                "source".into(),
                "sourcetype".into(),
            ],
        }
    }

    /// The directory name used on disk:
    /// `bucket_<index>_<start_ns>_<end_ns>_<uuid>`
    pub fn dir_name(&self) -> String {
        format!(
            "bucket_{}_{}_{}_{}",
            self.index, self.start_time_ns, self.end_time_ns, self.bucket_id
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dir_name_format() {
        let meta = BucketMeta {
            bucket_id: "abc-123".into(),
            index: "main".into(),
            start_time_ns: 1_000_000,
            end_time_ns: 2_000_000,
            event_count: 0,
            size_bytes: 0,
            schema_version: SCHEMA_VERSION,
            compressed: false,
            columns: vec![],
        };
        assert_eq!(meta.dir_name(), "bucket_main_1000000_2000000_abc-123");
    }

    #[test]
    fn serde_roundtrip() {
        let meta = BucketMeta::new("firewall", 0, 3_600_000_000_000);
        let json = serde_json::to_string(&meta).unwrap();
        let back: BucketMeta = serde_json::from_str(&json).unwrap();
        assert_eq!(meta, back);
    }
}
