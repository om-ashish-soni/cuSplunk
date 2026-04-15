//! In-memory bucket catalog, rebuilt from disk on startup.
//!
//! Tracks which buckets exist, their time ranges, and tombstone state.
//! Acts as the routing table for the tier-aware scan path.

use std::collections::HashMap;
use std::path::Path;

use crate::bucket::meta::BucketMeta;
use crate::error::StoreError;

/// Tombstone record written alongside a bucket marked for deletion.
#[derive(Debug, Clone)]
pub struct TombstoneEntry {
    pub bucket_id: String,
    /// When the tombstone was placed (Unix seconds).
    pub tombstoned_at: i64,
}

/// Catalog entry — a bucket plus its tombstone state.
#[derive(Debug, Clone)]
struct CatalogEntry {
    meta: BucketMeta,
    tombstone: Option<TombstoneEntry>,
}

/// Bucket catalog keyed by index name.
///
/// All mutation is synchronous; callers hold an `RwLock<BucketCatalog>`.
#[derive(Debug, Default)]
pub struct BucketCatalog {
    // index → entries sorted ascending by start_time_ns
    entries: HashMap<String, Vec<CatalogEntry>>,
}

impl BucketCatalog {
    pub fn new() -> Self {
        Self::default()
    }

    /// Add a newly written bucket to the catalog.
    pub fn add(&mut self, meta: BucketMeta) {
        let list = self.entries.entry(meta.index.clone()).or_default();
        // Keep sorted by start_time_ns for efficient range queries.
        let pos = list
            .binary_search_by_key(&meta.start_time_ns, |e| e.meta.start_time_ns)
            .unwrap_or_else(|i| i);
        list.insert(pos, CatalogEntry { meta, tombstone: None });
    }

    /// Return all non-tombstoned buckets whose time range overlaps `[start_ns, end_ns)`.
    /// `end_ns == 0` means open-ended (no upper bound).
    pub fn scan_range<'a>(
        &'a self,
        index: &str,
        start_ns: i64,
        end_ns: i64,
    ) -> Vec<&'a BucketMeta> {
        let Some(list) = self.entries.get(index) else {
            return vec![];
        };
        list.iter()
            .filter(|e| e.tombstone.is_none())
            .filter(|e| {
                let m = &e.meta;
                m.end_time_ns > start_ns && (end_ns == 0 || m.start_time_ns < end_ns)
            })
            .map(|e| &e.meta)
            .collect()
    }

    /// Return every non-tombstoned bucket for an index.
    pub fn list_index<'a>(&'a self, index: &str) -> Vec<&'a BucketMeta> {
        self.scan_range(index, i64::MIN, 0)
    }

    /// Return every non-tombstoned bucket across all indexes.
    pub fn list_all<'a>(&'a self) -> Vec<&'a BucketMeta> {
        self.entries
            .values()
            .flatten()
            .filter(|e| e.tombstone.is_none())
            .map(|e| &e.meta)
            .collect()
    }

    /// Mark a bucket for deletion. Returns `false` if not found.
    pub fn tombstone(&mut self, bucket_id: &str, now_unix_secs: i64) -> bool {
        for list in self.entries.values_mut() {
            if let Some(entry) = list.iter_mut().find(|e| e.meta.bucket_id == bucket_id) {
                entry.tombstone = Some(TombstoneEntry {
                    bucket_id: bucket_id.to_string(),
                    tombstoned_at: now_unix_secs,
                });
                return true;
            }
        }
        false
    }

    /// Permanently remove a bucket from the catalog. Called after hard delete.
    pub fn remove(&mut self, bucket_id: &str) -> Option<BucketMeta> {
        for list in self.entries.values_mut() {
            if let Some(pos) = list.iter().position(|e| e.meta.bucket_id == bucket_id) {
                return Some(list.remove(pos).meta);
            }
        }
        None
    }

    /// Return tombstoned entries whose grace period has elapsed.
    /// `grace_secs` is typically 86_400 (24 h).
    pub fn ready_for_hard_delete(&self, now_unix_secs: i64, grace_secs: i64) -> Vec<BucketMeta> {
        self.entries
            .values()
            .flatten()
            .filter(|e| {
                e.tombstone
                    .as_ref()
                    .map(|t| now_unix_secs - t.tombstoned_at >= grace_secs)
                    .unwrap_or(false)
            })
            .map(|e| e.meta.clone())
            .collect()
    }

    /// Return all tombstoned entries regardless of age.
    pub fn tombstoned(&self) -> Vec<(BucketMeta, i64)> {
        self.entries
            .values()
            .flatten()
            .filter_map(|e| {
                e.tombstone
                    .as_ref()
                    .map(|t| (e.meta.clone(), t.tombstoned_at))
            })
            .collect()
    }

    pub fn bucket_count(&self) -> usize {
        self.entries.values().map(|v| v.len()).sum()
    }

    // -------------------------------------------------------------------------
    // Startup rebuild
    // -------------------------------------------------------------------------

    /// Scan `warm_path` for existing bucket directories and rebuild the catalog.
    /// Called on startup; does not block normal operation if a bucket is unreadable.
    pub fn build_from_dir(warm_path: &Path) -> Result<Self, StoreError> {
        let mut catalog = Self::new();
        if !warm_path.exists() {
            return Ok(catalog);
        }

        for entry in std::fs::read_dir(warm_path)? {
            let entry = entry?;
            let path = entry.path();
            if !path.is_dir() {
                continue;
            }
            let meta_path = path.join("meta.json");
            if !meta_path.exists() {
                continue;
            }
            match std::fs::read(&meta_path)
                .map_err(StoreError::Io)
                .and_then(|b| serde_json::from_slice::<BucketMeta>(&b).map_err(StoreError::Json))
            {
                Ok(meta) => {
                    // Check for existing tombstone file.
                    let ts_path = path.join("tombstone.json");
                    let mut ce = CatalogEntry { meta, tombstone: None };
                    if ts_path.exists() {
                        if let Ok(ts_bytes) = std::fs::read(&ts_path) {
                            if let Ok(ts) = serde_json::from_slice::<TombstoneEntry>(&ts_bytes) {
                                ce.tombstone = Some(ts);
                            }
                        }
                    }
                    let list = catalog.entries.entry(ce.meta.index.clone()).or_default();
                    list.push(ce);
                }
                Err(e) => {
                    tracing::warn!(
                        path = %path.display(),
                        error = %e,
                        "Skipping unreadable bucket on catalog rebuild"
                    );
                }
            }
        }

        // Sort each index's list by start_time_ns.
        for list in catalog.entries.values_mut() {
            list.sort_unstable_by_key(|e| e.meta.start_time_ns);
        }

        Ok(catalog)
    }
}

// Tombstone serde for disk persistence.
impl serde::Serialize for TombstoneEntry {
    fn serialize<S: serde::Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        use serde::ser::SerializeStruct;
        let mut st = s.serialize_struct("TombstoneEntry", 2)?;
        st.serialize_field("bucket_id", &self.bucket_id)?;
        st.serialize_field("tombstoned_at", &self.tombstoned_at)?;
        st.end()
    }
}

impl<'de> serde::Deserialize<'de> for TombstoneEntry {
    fn deserialize<D: serde::Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        #[derive(serde::Deserialize)]
        struct Helper {
            bucket_id: String,
            tombstoned_at: i64,
        }
        let h = Helper::deserialize(d)?;
        Ok(TombstoneEntry {
            bucket_id: h.bucket_id,
            tombstoned_at: h.tombstoned_at,
        })
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn make_meta(index: &str, start: i64, end: i64) -> BucketMeta {
        BucketMeta::new(index, start, end)
    }

    #[test]
    fn add_and_scan_range() {
        let mut cat = BucketCatalog::new();
        cat.add(make_meta("main", 0, 100));
        cat.add(make_meta("main", 100, 200));
        cat.add(make_meta("main", 200, 300));

        let results = cat.scan_range("main", 50, 150);
        assert_eq!(results.len(), 2); // buckets [0,100) and [100,200) overlap
    }

    #[test]
    fn tombstoned_bucket_excluded_from_scan() {
        let mut cat = BucketCatalog::new();
        let meta = make_meta("main", 0, 100);
        let id = meta.bucket_id.clone();
        cat.add(meta);

        cat.tombstone(&id, 1_000_000);
        assert_eq!(cat.scan_range("main", 0, 200).len(), 0);
    }

    #[test]
    fn remove_drops_entry() {
        let mut cat = BucketCatalog::new();
        let meta = make_meta("main", 0, 100);
        let id = meta.bucket_id.clone();
        cat.add(meta);

        let removed = cat.remove(&id);
        assert!(removed.is_some());
        assert_eq!(cat.bucket_count(), 0);
    }

    #[test]
    fn ready_for_hard_delete_respects_grace_period() {
        let mut cat = BucketCatalog::new();
        let meta = make_meta("main", 0, 100);
        let id = meta.bucket_id.clone();
        cat.add(meta);
        cat.tombstone(&id, 1000);

        // Not ready yet (now = 1001, grace = 86400)
        assert!(cat.ready_for_hard_delete(1001, 86_400).is_empty());
        // Ready after grace period
        assert_eq!(cat.ready_for_hard_delete(1000 + 86_401, 86_400).len(), 1);
    }

    #[test]
    fn build_from_empty_dir() {
        let tmp = tempfile::TempDir::new().unwrap();
        let cat = BucketCatalog::build_from_dir(tmp.path()).unwrap();
        assert_eq!(cat.bucket_count(), 0);
    }

    #[test]
    fn build_from_dir_loads_written_bucket() {
        use crate::bucket::{BucketWriter, Event};
        let tmp = tempfile::TempDir::new().unwrap();
        let events = vec![Event {
            time_ns: 1_000_000,
            raw: b"test".to_vec(),
            host: "h".into(),
            source: "s".into(),
            sourcetype: "st".into(),
        }];
        BucketWriter::new(tmp.path(), "myindex", 0, 3_600_000_000_000)
            .write(&events)
            .unwrap();

        let cat = BucketCatalog::build_from_dir(tmp.path()).unwrap();
        assert_eq!(cat.bucket_count(), 1);
        assert_eq!(cat.list_index("myindex").len(), 1);
    }
}
