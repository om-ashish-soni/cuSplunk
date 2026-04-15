//! Retention engine — background task that tombstones and hard-deletes expired buckets.
//!
//! Implements S2.6:
//!   1. Every `check_interval_hours`, scan the catalog for buckets older than
//!      `retention_days` (per index, defaulting to `config.default_days`).
//!   2. Write a `tombstone.json` file and mark the catalog entry.
//!   3. After a 24-hour grace period, hard-delete the bucket directory and
//!      remove the catalog entry.
//!
//! Metrics emitted:
//!   - `cusplunk_store_retention_tombstoned_total`
//!   - `cusplunk_store_retention_deleted_events_total`

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use tokio::sync::RwLock;

use crate::catalog::BucketCatalog;
use crate::config::RetentionConfig;
use crate::error::StoreError;
use crate::warm::WarmTier;

const GRACE_PERIOD_SECS: i64 = 86_400; // 24 hours

/// Statistics from a single retention sweep.
#[derive(Debug, Default, Clone)]
pub struct RetentionStats {
    pub tombstoned: u64,
    pub hard_deleted: u64,
    pub events_deleted: u64,
}

/// Retention engine. Run via `tokio::spawn(engine.run_loop())`.
pub struct RetentionEngine {
    warm: Arc<WarmTier>,
    catalog: Arc<RwLock<BucketCatalog>>,
    config: RetentionConfig,
    /// Per-index override: index name → retention days.
    index_overrides: HashMap<String, u32>,
}

impl RetentionEngine {
    pub fn new(
        warm: Arc<WarmTier>,
        catalog: Arc<RwLock<BucketCatalog>>,
        config: RetentionConfig,
    ) -> Self {
        Self {
            warm,
            catalog,
            config,
            index_overrides: HashMap::new(),
        }
    }

    pub fn with_index_override(mut self, index: &str, days: u32) -> Self {
        self.index_overrides.insert(index.to_string(), days);
        self
    }

    // -------------------------------------------------------------------------
    // Main loop
    // -------------------------------------------------------------------------

    /// Run the retention loop forever. Meant to be spawned as a background task.
    pub async fn run_loop(&self) {
        let interval = Duration::from_secs(self.config.check_interval_hours as u64 * 3600);
        loop {
            tokio::time::sleep(interval).await;
            match self.check_and_evict().await {
                Ok(stats) => {
                    tracing::info!(
                        tombstoned = stats.tombstoned,
                        hard_deleted = stats.hard_deleted,
                        events_deleted = stats.events_deleted,
                        "Retention sweep completed"
                    );
                }
                Err(e) => {
                    tracing::error!(error = %e, "Retention sweep failed");
                }
            }
        }
    }

    // -------------------------------------------------------------------------
    // Single sweep — also callable from tests
    // -------------------------------------------------------------------------

    /// Perform one retention sweep. Returns statistics about what was done.
    pub async fn check_and_evict(&self) -> Result<RetentionStats, StoreError> {
        let now_secs = unix_now_secs();
        let mut stats = RetentionStats::default();

        // --- Phase 1: tombstone buckets past their retention window --------
        {
            let mut cat = self.catalog.write().await;
            let all_buckets: Vec<_> = cat.list_all().iter().map(|m| (*m).clone()).collect();

            for meta in &all_buckets {
                let retention_days = self
                    .index_overrides
                    .get(&meta.index)
                    .copied()
                    .unwrap_or(self.config.default_days);

                let retention_ns = retention_days as i64 * 86_400 * 1_000_000_000;
                let cutoff_ns = (now_secs * 1_000_000_000) - retention_ns;

                if meta.end_time_ns < cutoff_ns {
                    if cat.tombstone(&meta.bucket_id, now_secs) {
                        self.warm.write_tombstone(meta, now_secs)?;
                        stats.tombstoned += 1;
                        tracing::info!(
                            bucket_id = %meta.bucket_id,
                            index = %meta.index,
                            "Bucket tombstoned for retention"
                        );
                    }
                }
            }
        }

        // --- Phase 2: hard-delete grace-period-elapsed tombstoned buckets --
        {
            let ready: Vec<_> = {
                let cat = self.catalog.read().await;
                cat.ready_for_hard_delete(now_secs, GRACE_PERIOD_SECS)
            };

            for meta in ready {
                self.warm.hard_delete(&meta)?;
                stats.events_deleted += meta.event_count;

                let mut cat = self.catalog.write().await;
                cat.remove(&meta.bucket_id);
                stats.hard_deleted += 1;
            }
        }

        Ok(stats)
    }
}

fn unix_now_secs() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs() as i64
}

// -------------------------------------------------------------------------
// Tests
// -------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::bucket::Event;
    use tempfile::TempDir;

    fn make_engine(
        tmp: &TempDir,
        default_days: u32,
    ) -> (Arc<WarmTier>, Arc<RwLock<BucketCatalog>>, RetentionEngine) {
        let warm = Arc::new(WarmTier::new(tmp.path()));
        let catalog = Arc::new(RwLock::new(BucketCatalog::new()));
        let config = RetentionConfig {
            default_days,
            check_interval_hours: 1,
        };
        let engine = RetentionEngine::new(warm.clone(), catalog.clone(), config);
        (warm, catalog, engine)
    }

    async fn write_bucket_with_time(
        warm: &WarmTier,
        cat: &Arc<RwLock<BucketCatalog>>,
        index: &str,
        time_ns: i64,
    ) -> crate::bucket::BucketMeta {
        let events = vec![Event {
            time_ns,
            raw: b"x".to_vec(),
            host: "h".into(),
            source: "s".into(),
            sourcetype: "st".into(),
        }];
        let meta = warm.write_events(index, &events).unwrap();
        cat.write().await.add(meta.clone());
        meta
    }

    #[tokio::test]
    async fn retention_tombstones_expired_bucket() {
        let tmp = TempDir::new().unwrap();
        let (warm, cat, engine) = make_engine(&tmp, 1); // 1-day retention

        // Write a bucket with a timestamp 2 days in the past.
        let two_days_ago_ns = unix_now_secs() * 1_000_000_000 - 2 * 86_400 * 1_000_000_000i64;
        write_bucket_with_time(&warm, &cat, "main", two_days_ago_ns).await;

        let stats = engine.check_and_evict().await.unwrap();
        assert_eq!(stats.tombstoned, 1);
    }

    #[tokio::test]
    async fn retention_skips_recent_bucket() {
        let tmp = TempDir::new().unwrap();
        let (warm, cat, engine) = make_engine(&tmp, 90);

        // Recent bucket — should not be tombstoned.
        let recent_ns = unix_now_secs() * 1_000_000_000 - 1_000_000_000i64; // 1 second ago
        write_bucket_with_time(&warm, &cat, "main", recent_ns).await;

        let stats = engine.check_and_evict().await.unwrap();
        assert_eq!(stats.tombstoned, 0);
    }

    #[tokio::test]
    async fn hard_delete_after_grace_period() {
        let tmp = TempDir::new().unwrap();
        let warm = Arc::new(WarmTier::new(tmp.path()));
        let catalog = Arc::new(RwLock::new(BucketCatalog::new()));
        let config = RetentionConfig {
            default_days: 1,
            check_interval_hours: 1,
        };
        let engine = RetentionEngine::new(warm.clone(), catalog.clone(), config);

        // Write an expired bucket.
        let old_ns = unix_now_secs() * 1_000_000_000 - 2 * 86_400 * 1_000_000_000i64;
        let meta = write_bucket_with_time(&warm, &catalog, "main", old_ns).await;
        let bucket_dir = tmp.path().join(meta.dir_name());
        assert!(bucket_dir.exists());

        // Manually tombstone with a timestamp far in the past to skip grace period.
        {
            let mut cat = catalog.write().await;
            cat.tombstone(&meta.bucket_id, 1); // tombstoned at unix second 1
        }
        warm.write_tombstone(&meta, 1).unwrap();

        // Sweep: grace period (86400s) long since elapsed.
        let stats = engine.check_and_evict().await.unwrap();
        assert_eq!(stats.hard_deleted, 1);
        assert_eq!(stats.events_deleted, 1);
        assert!(!bucket_dir.exists());
    }

    #[tokio::test]
    async fn index_override_respected() {
        let tmp = TempDir::new().unwrap();
        let (warm, cat, engine) =
            make_engine(&tmp, 90); // default 90 days

        // Override "logs" index to 1-day retention.
        let engine = engine.with_index_override("logs", 1);

        // Bucket 2 days old under "logs" — should be tombstoned.
        let old_ns = unix_now_secs() * 1_000_000_000 - 2 * 86_400 * 1_000_000_000i64;
        write_bucket_with_time(&warm, &cat, "logs", old_ns).await;

        // Bucket 2 days old under "main" — should NOT be tombstoned (90-day default).
        write_bucket_with_time(&warm, &cat, "main", old_ns).await;

        let stats = engine.check_and_evict().await.unwrap();
        assert_eq!(stats.tombstoned, 1); // only "logs" bucket
    }
}
