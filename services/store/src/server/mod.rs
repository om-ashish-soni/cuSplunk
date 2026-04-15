//! cuSplunk Store — tonic gRPC server.
//!
//! R2: tier-aware Write + Scan. Hot tier (in-memory), warm tier (NVMe disk).
//! Cold tier and distributed scan fan-out land in R3.

use std::sync::Arc;
use std::time::{Duration, Instant};

use tokio::sync::{mpsc, RwLock};
use tokio_stream::wrappers::ReceiverStream;
use tonic::{Request, Response, Status};
use tracing::{info, warn};

use crate::bucket::Event;
use crate::catalog::BucketCatalog;
use crate::config::Config;
use crate::hot::{batch_approx_bytes, events_to_record_batch, HotBatch, HotTier};
use crate::proto::{
    store_server::Store, BucketInfo, BucketListRequest, BucketListResponse, DeleteRequest,
    DeleteResponse, ScanRequest, ScanResponse, WriteRequest, WriteResponse,
};
use crate::warm::{batch_to_ipc_bytes, WarmTier};

// ---------------------------------------------------------------------------
// StoreService
// ---------------------------------------------------------------------------

pub struct StoreService {
    hot: Arc<RwLock<HotTier>>,
    warm: Arc<WarmTier>,
    catalog: Arc<RwLock<BucketCatalog>>,
    hot_max_age: Duration,
}

impl StoreService {
    pub fn new(config: Config) -> Result<Self, crate::error::StoreError> {
        std::fs::create_dir_all(&config.warm_tier.path)?;

        let catalog = BucketCatalog::build_from_dir(&config.warm_tier.path)?;
        info!(
            bucket_count = catalog.bucket_count(),
            "Catalog rebuilt from warm tier"
        );

        Ok(Self {
            hot: Arc::new(RwLock::new(HotTier::new(config.hot_tier.max_bytes))),
            warm: Arc::new(WarmTier::new(&config.warm_tier.path)),
            catalog: Arc::new(RwLock::new(catalog)),
            hot_max_age: Duration::from_secs(config.hot_tier.max_age_secs),
        })
    }

    /// Expose catalog and warm tier for the retention engine background task.
    pub fn catalog(&self) -> Arc<RwLock<BucketCatalog>> {
        self.catalog.clone()
    }

    pub fn warm_tier(&self) -> Arc<WarmTier> {
        self.warm.clone()
    }
}

// ---------------------------------------------------------------------------
// tonic trait impl
// ---------------------------------------------------------------------------

#[tonic::async_trait]
impl Store for StoreService {
    // ----- Write ------------------------------------------------------------

    async fn write(
        &self,
        request: Request<WriteRequest>,
    ) -> Result<Response<WriteResponse>, Status> {
        let req = request.into_inner();

        if req.index.is_empty() {
            return Err(Status::invalid_argument("index must not be empty"));
        }
        if req.events.is_empty() {
            return Err(Status::invalid_argument("events must not be empty"));
        }

        info!(index = %req.index, n = req.events.len(), "Write");

        // Convert proto → bucket::Event, sort by time.
        let mut events: Vec<Event> = req
            .events
            .iter()
            .map(|e| Event {
                time_ns: e.time_ns,
                raw: e.raw.clone(),
                host: e.host.clone(),
                source: e.source.clone(),
                sourcetype: e.sourcetype.clone(),
            })
            .collect();
        events.sort_unstable_by_key(|e| e.time_ns);

        // 1. Persist to warm tier (durability first).
        let meta = self
            .warm
            .write_events(&req.index, &events)
            .map_err(|e| Status::internal(e.to_string()))?;

        let bucket_id = meta.bucket_id.clone();
        let events_written = meta.event_count;

        // 2. Register in catalog.
        self.catalog.write().await.add(meta);

        // 3. Insert into hot tier for sub-ms recent-data queries.
        let hot_batch_result = events_to_record_batch(&events);
        if let Ok(batch) = hot_batch_result {
            let approx = batch_approx_bytes(&batch);
            let start_ns = events.first().map(|e| e.time_ns).unwrap_or(0);
            let end_ns = events.last().map(|e| e.time_ns + 1).unwrap_or(0);
            let entry = HotBatch {
                index: req.index.clone(),
                start_time_ns: start_ns,
                end_time_ns: end_ns,
                batch,
                inserted_at: Instant::now(),
                approx_bytes: approx,
            };
            // Evicted batches are already on warm — safe to drop.
            let _ = self.hot.write().await.insert(entry);
        }

        Ok(Response::new(WriteResponse {
            events_written,
            bucket_id,
        }))
    }

    // ----- Scan -------------------------------------------------------------

    type ScanStream = ReceiverStream<Result<ScanResponse, Status>>;

    async fn scan(
        &self,
        request: Request<ScanRequest>,
    ) -> Result<Response<Self::ScanStream>, Status> {
        let req = request.into_inner();

        if req.index.is_empty() {
            return Err(Status::invalid_argument("index must not be empty"));
        }

        info!(
            index = %req.index,
            start_ns = req.start_time_ns,
            end_ns = req.end_time_ns,
            "Scan"
        );

        let cols: Vec<String> = req.columns.clone();
        let (tx, rx) = mpsc::channel(32);

        // Clone Arcs for the spawned task.
        let hot = self.hot.clone();
        let warm = self.warm.clone();
        let catalog = self.catalog.clone();
        let hot_max_age = self.hot_max_age;
        let start_ns = req.start_time_ns;
        let end_ns = req.end_time_ns;
        let index = req.index.clone();

        tokio::spawn(async move {
            // --- Hot tier (recent data in RAM) ---
            let hot_cutoff_ns = {
                let cutoff = Instant::now()
                    .checked_sub(hot_max_age)
                    .map(|_| {
                        // Convert hot_max_age to nanoseconds and subtract from now.
                        let now_ns = std::time::SystemTime::now()
                            .duration_since(std::time::UNIX_EPOCH)
                            .unwrap_or_default()
                            .as_nanos() as i64;
                        now_ns - hot_max_age.as_nanos() as i64
                    })
                    .unwrap_or(0);
                cutoff
            };

            // Query hot tier only for ranges that overlap the hot window.
            if end_ns == 0 || end_ns > hot_cutoff_ns {
                let hot_scan_start = start_ns.max(hot_cutoff_ns);
                let batches = hot.read().await.scan(&index, hot_scan_start, end_ns, &cols);
                for batch in batches {
                    match batch_to_ipc_bytes(&batch) {
                        Ok(bytes) => {
                            let row_count = batch.num_rows() as u64;
                            if tx
                                .send(Ok(ScanResponse {
                                    arrow_ipc_batch: bytes,
                                    event_count: row_count,
                                    bucket_id: "hot".into(),
                                }))
                                .await
                                .is_err()
                            {
                                return; // client disconnected
                            }
                        }
                        Err(e) => {
                            let _ = tx.send(Err(Status::internal(e.to_string()))).await;
                            return;
                        }
                    }
                }
            }

            // --- Warm tier (NVMe disk) ---
            let cat = catalog.read().await;
            let warm_batches = warm.scan(&cat, &index, start_ns, end_ns, &cols);
            drop(cat);

            match warm_batches {
                Err(e) => {
                    let _ = tx.send(Err(Status::internal(e.to_string()))).await;
                }
                Ok(batches) => {
                    for batch in batches {
                        match batch_to_ipc_bytes(&batch) {
                            Ok(bytes) => {
                                let row_count = batch.num_rows() as u64;
                                if tx
                                    .send(Ok(ScanResponse {
                                        arrow_ipc_batch: bytes,
                                        event_count: row_count,
                                        bucket_id: "warm".into(),
                                    }))
                                    .await
                                    .is_err()
                                {
                                    return;
                                }
                            }
                            Err(e) => {
                                let _ = tx.send(Err(Status::internal(e.to_string()))).await;
                                return;
                            }
                        }
                    }
                }
            }

            // Cold tier: R3
        });

        Ok(Response::new(ReceiverStream::new(rx)))
    }

    // ----- Delete -----------------------------------------------------------

    async fn delete(
        &self,
        request: Request<DeleteRequest>,
    ) -> Result<Response<DeleteResponse>, Status> {
        let req = request.into_inner();

        info!(index = %req.index, "Delete range");

        let metas: Vec<_> = {
            let cat = self.catalog.read().await;
            cat.scan_range(&req.index, req.start_time_ns, req.end_time_ns)
                .iter()
                .map(|m| (*m).clone())
                .collect()
        };

        let now_secs = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs() as i64;

        let mut deleted = 0u64;
        let buckets_deleted = metas.len() as u64;
        for meta in metas {
            // Tombstone first (soft delete), then hard delete immediately for
            // explicit delete requests (no grace period needed).
            self.warm
                .write_tombstone(&meta, now_secs)
                .map_err(|e| Status::internal(e.to_string()))?;
            self.warm
                .hard_delete(&meta)
                .map_err(|e| Status::internal(e.to_string()))?;

            let mut cat = self.catalog.write().await;
            if let Some(removed) = cat.remove(&meta.bucket_id) {
                deleted += removed.event_count;
            }

            warn!(bucket_id = %meta.bucket_id, "Bucket deleted on demand");
        }

        Ok(Response::new(DeleteResponse {
            buckets_deleted,
            events_deleted: deleted,
        }))
    }

    // ----- BucketList -------------------------------------------------------

    async fn bucket_list(
        &self,
        request: Request<BucketListRequest>,
    ) -> Result<Response<BucketListResponse>, Status> {
        let req = request.into_inner();
        let cat = self.catalog.read().await;

        let metas = if req.start_time_ns == 0 && req.end_time_ns == 0 {
            cat.list_index(&req.index)
        } else {
            cat.scan_range(&req.index, req.start_time_ns, req.end_time_ns)
        };

        let buckets: Vec<BucketInfo> = metas
            .into_iter()
            .map(|m| BucketInfo {
                bucket_id: m.bucket_id.clone(),
                index: m.index.clone(),
                start_time_ns: m.start_time_ns,
                end_time_ns: m.end_time_ns,
                event_count: m.event_count,
                size_bytes: m.size_bytes,
                tier: "warm".into(),
                schema_version: m.schema_version,
            })
            .collect();

        Ok(Response::new(BucketListResponse { buckets }))
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::{GrpcConfig, HotTierConfig, RetentionConfig, WarmTierConfig};
    use crate::proto::{store_server::Store, Event as ProtoEvent, ScanRequest, WriteRequest};
    use crate::warm::ipc_bytes_to_batch;
    use tempfile::TempDir;
    use tokio_stream::StreamExt;

    fn make_service(tmp: &TempDir) -> StoreService {
        let config = Config {
            grpc: GrpcConfig {
                port: 50051,
                bind: "127.0.0.1".into(),
            },
            hot_tier: HotTierConfig {
                max_bytes: 256 * 1024 * 1024,
                max_age_secs: 300,
            },
            warm_tier: WarmTierConfig {
                path: tmp.path().to_path_buf(),
                gds_enabled: false,
            },
            retention: RetentionConfig::default(),
        };
        StoreService::new(config).unwrap()
    }

    fn proto_event(i: u64) -> ProtoEvent {
        ProtoEvent {
            time_ns: 1_700_000_000_000_000_000i64 + i as i64 * 1_000_000,
            raw: format!("src_ip=10.0.0.{} bytes={}", i % 256, i * 100).into_bytes(),
            host: format!("fw-{}", i % 4),
            source: "syslog".into(),
            sourcetype: "firewall".into(),
            index: "main".into(),
            fields: Default::default(),
        }
    }

    #[tokio::test]
    async fn write_and_bucket_list() {
        let tmp = TempDir::new().unwrap();
        let svc = make_service(&tmp);

        svc.write(Request::new(WriteRequest {
            index: "main".into(),
            events: (0..10).map(proto_event).collect(),
        }))
        .await
        .unwrap();

        let resp = svc
            .bucket_list(Request::new(BucketListRequest {
                index: "main".into(),
                start_time_ns: 0,
                end_time_ns: 0,
            }))
            .await
            .unwrap()
            .into_inner();

        assert_eq!(resp.buckets.len(), 1);
        assert_eq!(resp.buckets[0].event_count, 10);
    }

    #[tokio::test]
    async fn scan_returns_arrow_ipc_bytes() {
        let tmp = TempDir::new().unwrap();
        let svc = make_service(&tmp);

        svc.write(Request::new(WriteRequest {
            index: "firewall".into(),
            events: (0..20).map(proto_event).collect(),
        }))
        .await
        .unwrap();

        let stream = svc
            .scan(Request::new(ScanRequest {
                index: "firewall".into(),
                start_time_ns: 0,
                end_time_ns: i64::MAX,
                columns: vec![],
                filter_expr: "".into(),
                limit: 0,
            }))
            .await
            .unwrap()
            .into_inner();

        let responses: Vec<ScanResponse> = stream
            .collect::<Vec<_>>()
            .await
            .into_iter()
            .map(|r| r.unwrap())
            .collect();

        assert!(!responses.is_empty());

        // Decode first response and verify row count.
        let batches = ipc_bytes_to_batch(&responses[0].arrow_ipc_batch).unwrap();
        assert!(!batches.is_empty());
        assert!(batches.iter().map(|b| b.num_rows()).sum::<usize>() > 0);
    }

    #[tokio::test]
    async fn scan_empty_index_returns_no_responses() {
        let tmp = TempDir::new().unwrap();
        let svc = make_service(&tmp);

        let stream = svc
            .scan(Request::new(ScanRequest {
                index: "nonexistent".into(),
                start_time_ns: 0,
                end_time_ns: i64::MAX,
                columns: vec![],
                filter_expr: "".into(),
                limit: 0,
            }))
            .await
            .unwrap()
            .into_inner();

        let responses: Vec<_> = stream.collect().await;
        assert!(responses.is_empty());
    }

    #[tokio::test]
    async fn delete_removes_bucket() {
        let tmp = TempDir::new().unwrap();
        let svc = make_service(&tmp);

        svc.write(Request::new(WriteRequest {
            index: "main".into(),
            events: (0..5).map(proto_event).collect(),
        }))
        .await
        .unwrap();

        // Verify it exists.
        let before = svc
            .bucket_list(Request::new(BucketListRequest {
                index: "main".into(),
                ..Default::default()
            }))
            .await
            .unwrap()
            .into_inner();
        assert_eq!(before.buckets.len(), 1);

        // Delete it.
        svc.delete(Request::new(DeleteRequest {
            index: "main".into(),
            start_time_ns: 0,
            end_time_ns: i64::MAX,
        }))
        .await
        .unwrap();

        // Verify it's gone.
        let after = svc
            .bucket_list(Request::new(BucketListRequest {
                index: "main".into(),
                ..Default::default()
            }))
            .await
            .unwrap()
            .into_inner();
        assert_eq!(after.buckets.len(), 0);
    }

    #[tokio::test]
    async fn catalog_rebuilt_on_startup() {
        let tmp = TempDir::new().unwrap();

        // Write bucket with first service instance.
        {
            let svc = make_service(&tmp);
            svc.write(Request::new(WriteRequest {
                index: "main".into(),
                events: (0..7).map(proto_event).collect(),
            }))
            .await
            .unwrap();
        }

        // New service instance rebuilds catalog from disk.
        let svc2 = make_service(&tmp);
        let resp = svc2
            .bucket_list(Request::new(BucketListRequest {
                index: "main".into(),
                ..Default::default()
            }))
            .await
            .unwrap()
            .into_inner();
        assert_eq!(resp.buckets.len(), 1);
        assert_eq!(resp.buckets[0].event_count, 7);
    }
}
