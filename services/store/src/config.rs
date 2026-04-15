use serde::{Deserialize, Serialize};
use std::path::PathBuf;

use crate::error::StoreError;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Config {
    #[serde(default = "default_grpc")]
    pub grpc: GrpcConfig,

    #[serde(default)]
    pub hot_tier: HotTierConfig,

    #[serde(default)]
    pub warm_tier: WarmTierConfig,

    #[serde(default)]
    pub retention: RetentionConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GrpcConfig {
    #[serde(default = "default_grpc_port")]
    pub port: u16,
    #[serde(default = "default_bind")]
    pub bind: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HotTierConfig {
    /// Maximum bytes to keep in-memory (default: 512 MB).
    #[serde(default = "default_hot_max_bytes")]
    pub max_bytes: usize,
    /// Evict batches older than this many seconds (default: 300 = 5 min).
    #[serde(default = "default_hot_max_age_secs")]
    pub max_age_secs: u64,
}

impl Default for HotTierConfig {
    fn default() -> Self {
        Self {
            max_bytes: default_hot_max_bytes(),
            max_age_secs: default_hot_max_age_secs(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WarmTierConfig {
    #[serde(default = "default_warm_path")]
    pub path: PathBuf,
    #[serde(default)]
    pub gds_enabled: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RetentionConfig {
    #[serde(default = "default_retention_days")]
    pub default_days: u32,
    #[serde(default = "default_check_interval")]
    pub check_interval_hours: u32,
}

// ---------------------------------------------------------------------------
// Defaults
// ---------------------------------------------------------------------------

fn default_hot_max_bytes() -> usize {
    512 * 1024 * 1024 // 512 MB
}

fn default_hot_max_age_secs() -> u64 {
    300 // 5 minutes
}

fn default_grpc() -> GrpcConfig {
    GrpcConfig {
        port: 50051,
        bind: "0.0.0.0".into(),
    }
}

fn default_grpc_port() -> u16 {
    50051
}

fn default_bind() -> String {
    "0.0.0.0".into()
}

fn default_warm_path() -> PathBuf {
    PathBuf::from("/var/lib/cusplunk/warm")
}

fn default_retention_days() -> u32 {
    90
}

fn default_check_interval() -> u32 {
    1
}

impl Default for WarmTierConfig {
    fn default() -> Self {
        Self {
            path: default_warm_path(),
            gds_enabled: false,
        }
    }
}

impl Default for RetentionConfig {
    fn default() -> Self {
        Self {
            default_days: default_retention_days(),
            check_interval_hours: default_check_interval(),
        }
    }
}

impl Config {
    pub fn grpc_addr(&self) -> String {
        format!("{}:{}", self.grpc.bind, self.grpc.port)
    }
}

impl Default for Config {
    fn default() -> Self {
        Self {
            grpc: default_grpc(),
            hot_tier: HotTierConfig::default(),
            warm_tier: WarmTierConfig::default(),
            retention: RetentionConfig::default(),
        }
    }
}

impl Config {
    pub fn from_file(path: &str) -> Result<Self, StoreError> {
        let content = std::fs::read_to_string(path)?;
        let cfg = serde_yaml::from_str(&content)?;
        Ok(cfg)
    }
}
