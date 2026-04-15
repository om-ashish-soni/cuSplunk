//! Bloom filter backed by xxh3 hashing.
//!
//! Stores a compact bit array that answers "definitely not present" vs.
//! "possibly present" for arbitrary byte slices. Used per bucket to skip
//! buckets that cannot contain a query token — the primary I/O optimisation
//! for sparse keyword searches.
//!
//! Serialisation format (little-endian):
//!   [0..8]   num_bits  (u64)
//!   [8..16]  num_hashes (u64)
//!   [16..]   bit words  (num_words × u64)

use xxhash_rust::xxh3::xxh3_64_with_seed;

/// A classic Bloom filter using k independent xxh3 hashes.
#[derive(Debug, Clone)]
pub struct BloomFilter {
    /// Packed bit array.
    bits: Vec<u64>,
    num_bits: usize,
    num_hashes: usize,
}

impl BloomFilter {
    // ---------------------------------------------------------------------------
    // Construction
    // ---------------------------------------------------------------------------

    /// Create an empty filter with an explicit bit count and hash count.
    pub fn new(num_bits: usize, num_hashes: usize) -> Self {
        assert!(num_bits > 0, "num_bits must be > 0");
        assert!(num_hashes > 0, "num_hashes must be > 0");
        let words = (num_bits + 63) / 64;
        Self {
            bits: vec![0u64; words],
            num_bits,
            num_hashes,
        }
    }

    /// Create a filter sized for `n_items` expected insertions at a given
    /// false-positive rate `fpr` (e.g. `0.01` for 1%).
    pub fn with_fpr(n_items: usize, fpr: f64) -> Self {
        assert!(n_items > 0);
        assert!((0.0..1.0).contains(&fpr), "fpr must be in (0, 1)");

        let num_bits = optimal_num_bits(n_items, fpr).max(64);
        let num_hashes = optimal_num_hashes(num_bits, n_items).max(1);
        Self::new(num_bits, num_hashes)
    }

    /// Build a filter from a pre-collected token list.
    pub fn build_from_tokens(tokens: &[Vec<u8>], fpr: f64) -> Self {
        let mut f = Self::with_fpr(tokens.len().max(1000), fpr);
        for t in tokens {
            f.insert(t);
        }
        f
    }

    // ---------------------------------------------------------------------------
    // Mutation / query
    // ---------------------------------------------------------------------------

    /// Insert an item into the filter.
    pub fn insert(&mut self, item: &[u8]) {
        for seed in 0..self.num_hashes as u64 {
            let bit = self.hash(item, seed);
            self.bits[bit / 64] |= 1u64 << (bit % 64);
        }
    }

    /// Return `true` if the item *might* be present, `false` if definitely absent.
    pub fn contains(&self, item: &[u8]) -> bool {
        for seed in 0..self.num_hashes as u64 {
            let bit = self.hash(item, seed);
            if self.bits[bit / 64] & (1u64 << (bit % 64)) == 0 {
                return false;
            }
        }
        true
    }

    // ---------------------------------------------------------------------------
    // Serialisation
    // ---------------------------------------------------------------------------

    pub fn to_bytes(&self) -> Vec<u8> {
        let mut out = Vec::with_capacity(16 + self.bits.len() * 8);
        out.extend_from_slice(&(self.num_bits as u64).to_le_bytes());
        out.extend_from_slice(&(self.num_hashes as u64).to_le_bytes());
        for &word in &self.bits {
            out.extend_from_slice(&word.to_le_bytes());
        }
        out
    }

    pub fn from_bytes(bytes: &[u8]) -> Option<Self> {
        if bytes.len() < 16 {
            return None;
        }
        let num_bits = u64::from_le_bytes(bytes[0..8].try_into().ok()?) as usize;
        let num_hashes = u64::from_le_bytes(bytes[8..16].try_into().ok()?) as usize;

        if num_bits == 0 || num_hashes == 0 {
            return None;
        }

        let words = (num_bits + 63) / 64;
        if bytes.len() < 16 + words * 8 {
            return None;
        }

        let mut bits = Vec::with_capacity(words);
        for i in 0..words {
            let start = 16 + i * 8;
            bits.push(u64::from_le_bytes(bytes[start..start + 8].try_into().ok()?));
        }

        Some(Self {
            bits,
            num_bits,
            num_hashes,
        })
    }

    // ---------------------------------------------------------------------------
    // Introspection
    // ---------------------------------------------------------------------------

    pub fn num_bits(&self) -> usize {
        self.num_bits
    }

    pub fn num_hashes(&self) -> usize {
        self.num_hashes
    }

    /// Approximate fill ratio (set bits / total bits). As this approaches 1.0
    /// the false positive rate climbs toward 1.0.
    pub fn fill_ratio(&self) -> f64 {
        let set: u64 = self.bits.iter().map(|w| w.count_ones() as u64).sum();
        set as f64 / self.num_bits as f64
    }

    // ---------------------------------------------------------------------------
    // Private
    // ---------------------------------------------------------------------------

    #[inline]
    fn hash(&self, item: &[u8], seed: u64) -> usize {
        (xxh3_64_with_seed(item, seed) as usize) % self.num_bits
    }
}

// ---------------------------------------------------------------------------
// Optimal parameter formulae (standard Bloom filter maths)
// ---------------------------------------------------------------------------

/// Optimal number of bits: m = -(n * ln(p)) / (ln(2))^2
fn optimal_num_bits(n: usize, fpr: f64) -> usize {
    let ln2 = std::f64::consts::LN_2;
    (-(n as f64) * fpr.ln() / (ln2 * ln2)).ceil() as usize
}

/// Optimal number of hashes: k = (m/n) * ln(2)
fn optimal_num_hashes(m: usize, n: usize) -> usize {
    ((m as f64 / n as f64) * std::f64::consts::LN_2)
        .round()
        .max(1.0) as usize
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn inserted_item_always_found() {
        let mut f = BloomFilter::with_fpr(1000, 0.01);
        let items: Vec<Vec<u8>> = (0..500)
            .map(|i| format!("token-{}", i).into_bytes())
            .collect();
        for item in &items {
            f.insert(item);
        }
        for item in &items {
            assert!(f.contains(item), "false negative for {:?}", item);
        }
    }

    #[test]
    fn non_inserted_item_false_positive_rate() {
        let mut f = BloomFilter::with_fpr(1000, 0.01);
        for i in 0..1000u64 {
            f.insert(&i.to_le_bytes());
        }
        // Check 10_000 items that were never inserted.
        let mut fp = 0usize;
        for i in 2000u64..12_000 {
            if f.contains(&i.to_le_bytes()) {
                fp += 1;
            }
        }
        let actual_fpr = fp as f64 / 10_000.0;
        // Allow generous 5× headroom over target 1% FPR.
        assert!(
            actual_fpr < 0.05,
            "FPR too high: {:.3} (expected < 0.05)",
            actual_fpr
        );
    }

    #[test]
    fn serialisation_roundtrip() {
        let mut f = BloomFilter::with_fpr(500, 0.01);
        f.insert(b"hello");
        f.insert(b"world");

        let bytes = f.to_bytes();
        let f2 = BloomFilter::from_bytes(&bytes).unwrap();

        assert!(f2.contains(b"hello"));
        assert!(f2.contains(b"world"));
        assert_eq!(f2.num_bits(), f.num_bits());
        assert_eq!(f2.num_hashes(), f.num_hashes());
    }

    #[test]
    fn from_bytes_truncated_returns_none() {
        assert!(BloomFilter::from_bytes(&[0u8; 4]).is_none());
        assert!(BloomFilter::from_bytes(&[]).is_none());
    }

    #[test]
    fn fill_ratio_increases_with_inserts() {
        let mut f = BloomFilter::with_fpr(100, 0.01);
        let r0 = f.fill_ratio();
        for i in 0..50u64 {
            f.insert(&i.to_le_bytes());
        }
        assert!(f.fill_ratio() > r0);
    }

    #[test]
    fn build_from_tokens() {
        let tokens: Vec<Vec<u8>> = vec![
            b"src_ip=10.0.0.1".to_vec(),
            b"action=accept".to_vec(),
            b"bytes=1234".to_vec(),
        ];
        let f = BloomFilter::build_from_tokens(&tokens, 0.01);
        assert!(f.contains(b"src_ip=10.0.0.1"));
        assert!(f.contains(b"action=accept"));
    }
}
