use thiserror::Error;

#[derive(Debug, Error)]
pub enum StoreError {
    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),

    #[error("Arrow error: {0}")]
    Arrow(#[from] arrow::error::ArrowError),

    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),

    #[error("YAML error: {0}")]
    Yaml(#[from] serde_yaml::Error),

    #[error("Bucket not found: {0}")]
    BucketNotFound(String),

    #[error("Invalid time range: start={start} end={end}")]
    InvalidTimeRange { start: i64, end: i64 },

    #[error("Column not found: {0}")]
    ColumnNotFound(String),

    #[error("Bloom filter corrupt: {0}")]
    BloomCorrupt(String),

    #[error("{0}")]
    Other(String),
}

impl From<StoreError> for tonic::Status {
    fn from(e: StoreError) -> Self {
        match e {
            StoreError::BucketNotFound(msg) => tonic::Status::not_found(msg),
            StoreError::InvalidTimeRange { .. } => {
                tonic::Status::invalid_argument(e.to_string())
            }
            StoreError::ColumnNotFound(msg) => tonic::Status::not_found(msg),
            _ => tonic::Status::internal(e.to_string()),
        }
    }
}
