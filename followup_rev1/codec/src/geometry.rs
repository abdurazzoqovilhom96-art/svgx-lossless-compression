//! Shared-geometry block records (FORMAT.md §7): predictors, exact bounded arithmetic,
//! encoder search and the MSB-first block bitstream.
use crate::bits::{leb_get_bits, leb_len, BitReader, BitWriter};
use crate::error::{err, Result};
use crate::path::V2;

pub const WINDOW: usize = 4096;
pub const TOP_CANDIDATES: usize = 8;
const BOUND: u128 = 1u128 << 126;
const COORD_LIMIT: u128 = 1u128 << 96;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Block {
    pub j: [V2; 5],
    pub h0: [V2; 4],
    pub h1: [V2; 4],
}

impl Block {
    pub fn p1(&self, s: usize) -> V2 {
        [self.j[s][0] + self.h0[s][0], self.j[s][1] + self.h0[s][1]]
    }
    pub fn p2(&self, s: usize) -> V2 {
        [self.j[s + 1][0] - self.h1[s][0], self.j[s + 1][1] - self.h1[s][1]]
    }
}

#[inline]
fn bd(x: i128) -> Option<i128> {
    if x.unsigned_abs() < BOUND {
        Some(x)
    } else {
        None
    }
}
#[inline]
fn mul(a: i128, b: i128) -> Option<i128> {
    bd(a.checked_mul(b)?)
}
#[inline]
fn add(a: i128, b: i128) -> Option<i128> {
    bd(a.checked_add(b)?)
}
#[inline]
fn sub(a: i128, b: i128) -> Option<i128> {
    bd(a.checked_sub(b)?)
}

/// Signed nearest-even rounding of n/d, d > 0.
pub fn round_div(n: i128, d: i128) -> i128 {
    let q = n.div_euclid(d);
    let r = n.rem_euclid(d);
    let twice = r * 2;
    if twice > d || (twice == d && q.rem_euclid(2) == 1) {
        q + 1
    } else {
        q
    }
}

fn third(c: V2) -> V2 {
    [round_div(c[0], 3), round_div(c[1], 3)]
}

fn diff(a: V2, b: V2) -> Option<V2> {
    Some([sub(a[0], b[0])?, sub(a[1], b[1])?])
}

/// Target triple with maximal |det|, ties lexicographic; None if any determinant is out of
/// bounds or all are zero.
pub fn target_triple(j: &[V2; 5]) -> Option<(usize, usize, usize)> {
    let mut best: Option<((usize, usize, usize), u128)> = None;
    for a in 0..5 {
        for b in a + 1..5 {
            for c in b + 1..5 {
                let u = diff(j[b], j[a])?;
                let v = diff(j[c], j[a])?;
                let d = sub(mul(u[0], v[1])?, mul(v[0], u[1])?)?;
                let ad = d.unsigned_abs();
                if best.map(|(_, m)| ad > m).unwrap_or(true) {
                    best = Some(((a, b, c), ad));
                }
            }
        }
    }
    match best {
        Some((t, m)) if m > 0 => Some(t),
        _ => None,
    }
}

/// Columns (J_b - J_a, J_c - J_a) as [m00, m01, m10, m11] with column 0 = (m00, m10).
fn triple_matrix(j: &[V2; 5], t: (usize, usize, usize)) -> Option<[i128; 4]> {
    let u = diff(j[t.1], j[t.0])?;
    let v = diff(j[t.2], j[t.0])?;
    Some([u[0], v[0], u[1], v[1]])
}

fn det(m: &[i128; 4]) -> Option<i128> {
    sub(mul(m[0], m[3])?, mul(m[1], m[2])?)
}

#[derive(Clone, Copy, Debug)]
pub struct Affine {
    t: [i128; 4],
    q: [i128; 4],
    det: i128,
}

impl Affine {
    pub fn new(target_j: &[V2; 5], ref_j: &[V2; 5], tri: (usize, usize, usize)) -> Option<Affine> {
        let t = triple_matrix(target_j, tri)?;
        let q = triple_matrix(ref_j, tri)?;
        let d = det(&q)?;
        if d == 0 {
            return None;
        }
        Some(Affine { t, q, det: d })
    }
    /// R(T adj(Q) h / det(Q)) with all intermediates bounded.
    pub fn map(&self, h: V2) -> Option<V2> {
        let q = &self.q;
        // q = [q00, q01, q10, q11]
        let ux = sub(mul(q[3], h[0])?, mul(q[1], h[1])?)?;
        let uy = sub(mul(q[0], h[1])?, mul(q[2], h[0])?)?;
        let t = &self.t;
        let mut nx = add(mul(t[0], ux)?, mul(t[1], uy)?)?;
        let mut ny = add(mul(t[2], ux)?, mul(t[3], uy)?)?;
        let mut d = self.det;
        if d < 0 {
            nx = -nx;
            ny = -ny;
            d = -d;
        }
        Some([round_div(nx, d), round_div(ny, d)])
    }
}

/// Mode-10 second-handle prediction from c and the actual h0.
fn smooth_h1(c: V2, h0: V2) -> Option<V2> {
    let dd = add(mul(c[0], c[0])?, mul(c[1], c[1])?)?;
    if dd == 0 {
        return Some([0, 0]);
    }
    let dot = add(mul(c[0], h0[0])?, mul(c[1], h0[1])?)?;
    let mut out = [0i128; 2];
    for i in 0..2 {
        let p = mul(c[i], dot)?;
        let p2 = mul(2, p)?;
        let q = mul(h0[i], dd)?;
        let n = sub(p2, q)?;
        out[i] = round_div(n, dd);
    }
    Some(out)
}

#[derive(Clone, Copy, Debug)]
pub enum Predictor {
    Zero,
    Third,
    Smooth,
    Ref { dist: usize, aff: Affine },
}

impl Predictor {
    pub fn mode(&self) -> u32 {
        match self {
            Predictor::Zero => 0,
            Predictor::Third => 1,
            Predictor::Smooth => 2,
            Predictor::Ref { .. } => 3,
        }
    }
    fn pred_h0(&self, s: usize, j: &[V2; 5], h1_prev: Option<V2>, refb: Option<&Block>) -> Option<V2> {
        let c = [j[s + 1][0] - j[s][0], j[s + 1][1] - j[s][1]];
        match self {
            Predictor::Zero => Some([0, 0]),
            Predictor::Third => Some(third(c)),
            Predictor::Smooth => {
                if s == 0 {
                    Some(third(c))
                } else {
                    h1_prev
                }
            }
            Predictor::Ref { aff, .. } => aff.map(refb?.h0[s]),
        }
    }
    fn pred_h1(&self, s: usize, j: &[V2; 5], h0_actual: V2, refb: Option<&Block>) -> Option<V2> {
        let c = [j[s + 1][0] - j[s][0], j[s + 1][1] - j[s][1]];
        match self {
            Predictor::Zero => Some([0, 0]),
            Predictor::Third => Some(third(c)),
            Predictor::Smooth => smooth_h1(c, h0_actual),
            Predictor::Ref { aff, .. } => aff.map(refb?.h1[s]),
        }
    }
}

#[inline]
pub fn zig(r: i128) -> u128 {
    if r >= 0 {
        (r as u128) << 1
    } else {
        ((-(r + 1)) as u128) * 2 + 1
    }
}
#[inline]
pub fn unzig(z: u128) -> i128 {
    if z & 1 == 0 {
        (z >> 1) as i128
    } else {
        -((z >> 1) as i128) - 1
    }
}

/// Residuals (zigzag) of a block under a predictor, None if unavailable.
fn residuals(pred: &Predictor, b: &Block, refb: Option<&Block>) -> Option<[u128; 16]> {
    let mut z = [0u128; 16];
    for s in 0..4 {
        let h1_prev = if s > 0 { Some(b.h1[s - 1]) } else { None };
        let p0 = pred.pred_h0(s, &b.j, h1_prev, refb)?;
        let p1 = pred.pred_h1(s, &b.j, b.h0[s], refb)?;
        let r = [sub(b.h0[s][0], p0[0])?, sub(b.h0[s][1], p0[1])?, sub(b.h1[s][0], p1[0])?, sub(b.h1[s][1], p1[1])?];
        for i in 0..4 {
            z[4 * s + i] = zig(r[i]);
        }
    }
    Some(z)
}

#[inline]
fn gamma_len(n: u128) -> u64 {
    (2 * (127 - n.leading_zeros()) + 1) as u64
}

/// Best p and residual bits for 16 zigzag values.
fn residual_cost(z: &[u128; 16]) -> (u32, u64) {
    let mut best = (0u32, u64::MAX);
    for p in 0..16u32 {
        let mut bits = 0u64;
        for &v in z {
            bits += gamma_len((v >> p) + 1) + p as u64;
        }
        if bits < best.1 {
            best = (p, bits);
        }
    }
    best
}

fn header_bits(pred: &Predictor) -> u64 {
    match pred {
        Predictor::Ref { dist, .. } => 2 + 8 * leb_len((*dist - 1) as u64) as u64 + 4,
        _ => 6,
    }
}

/// Affine coordinates of the 8 control points of a block under a triple (IEEE double).
fn affine_coords(b: &Block, tri: (usize, usize, usize)) -> Option<[f64; 16]> {
    let m = triple_matrix(&b.j, tri)?;
    let d = det(&m)?;
    if d == 0 {
        return None;
    }
    let (m00, m01, m10, m11, df) = (m[0] as f64, m[1] as f64, m[2] as f64, m[3] as f64, d as f64);
    let ja = b.j[tri.0];
    let mut out = [0f64; 16];
    for s in 0..4 {
        for (k, p) in [b.p1(s), b.p2(s)].iter().enumerate() {
            let dx = (p[0] - ja[0]) as f64;
            let dy = (p[1] - ja[1]) as f64;
            out[4 * s + 2 * k] = (m11 * dx - m01 * dy) / df;
            out[4 * s + 2 * k + 1] = (m00 * dy - m10 * dx) / df;
        }
    }
    Some(out)
}

pub const TRIPLES: [(usize, usize, usize); 10] = [
    (0, 1, 2), (0, 1, 3), (0, 1, 4), (0, 2, 3), (0, 2, 4), (0, 3, 4), (1, 2, 3), (1, 2, 4), (1, 3, 4), (2, 3, 4),
];

fn triple_index(t: (usize, usize, usize)) -> usize {
    TRIPLES.iter().position(|&x| x == t).unwrap()
}

#[derive(Clone, Debug, Default)]
pub struct GeomStats {
    pub blocks: u64,
    pub mode_counts: [u64; 4],
    pub residual_bits: u64,
    pub header_bits: u64,
    pub ref_candidates_evaluated: u64,
}

/// Bit mask of the prediction modes the encoder may choose (bit m = mode m; 00=bit0 … 11=bit3).
/// REV1 ablation option. The default (all modes) reproduces the frozen SVGX v1 encoder exactly.
/// Mode 00 must always be allowed: it is the predictor that is always available.
pub const ALL_MODES: u8 = 0b1111;

pub struct Encoder {
    window: Vec<Block>,
    coords: Vec<[Option<[f64; 16]>; 10]>,
    pub w: BitWriter,
    pub stats: GeomStats,
    allowed: u8,
}

impl Default for Encoder {
    fn default() -> Self {
        Self::new()
    }
}

impl Encoder {
    pub fn new() -> Self {
        Self::with_modes(ALL_MODES)
    }

    /// Encoder restricted to the modes in `mask`; mode 00 is always included.
    pub fn with_modes(mask: u8) -> Self {
        Encoder {
            window: Vec::new(),
            coords: Vec::new(),
            w: BitWriter::new(),
            stats: GeomStats::default(),
            allowed: (mask & ALL_MODES) | 1,
        }
    }

    pub fn encode_block(&mut self, b: Block) {
        let n = self.window.len();
        // (total bits, mode, dist, p, predictor, residuals)
        let mut best: Option<(u64, u32, usize, u32, Predictor, [u128; 16])> = None;
        let consider = |pred: Predictor, z: [u128; 16], best: &mut Option<(u64, u32, usize, u32, Predictor, [u128; 16])>| {
            let (p, rb) = residual_cost(&z);
            let total = header_bits(&pred) + rb;
            let dist = if let Predictor::Ref { dist, .. } = pred { dist } else { 0 };
            let key = (total, pred.mode(), dist, p);
            let better = match best {
                None => true,
                Some((bt, bm, bd, bp, _, _)) => key < (*bt, *bm, *bd, *bp),
            };
            if better {
                *best = Some((total, pred.mode(), dist, p, pred, z));
            }
        };
        for pred in [Predictor::Zero, Predictor::Third, Predictor::Smooth] {
            if self.allowed & (1 << pred.mode()) == 0 {
                continue;
            }
            if let Some(z) = residuals(&pred, &b, None) {
                consider(pred, z, &mut best);
            }
        }
        let tri_opt = if self.allowed & (1 << 3) != 0 { target_triple(&b.j) } else { None };
        if let Some(tri) = tri_opt {
            let ti = triple_index(tri);
            if let Some(tc) = affine_coords(&b, tri) {
                let maxd = n.min(WINDOW);
                let mut ranked: Vec<(f64, usize)> = Vec::with_capacity(maxd);
                for d in 1..=maxd {
                    if let Some(rc) = &self.coords[n - d][ti] {
                        let mut ssd = 0f64;
                        for i in 0..16 {
                            let e = tc[i] - rc[i];
                            ssd += e * e;
                        }
                        if ssd.is_nan() {
                            ssd = f64::INFINITY;
                        }
                        ranked.push((ssd, d));
                    }
                }
                ranked.sort_by(|a, b| a.0.total_cmp(&b.0).then(a.1.cmp(&b.1)));
                let mut used = 0;
                for &(_, d) in &ranked {
                    if used >= TOP_CANDIDATES {
                        break;
                    }
                    let refb = &self.window[n - d];
                    let aff = match Affine::new(&b.j, &refb.j, tri) {
                        Some(a) => a,
                        None => continue,
                    };
                    let pred = Predictor::Ref { dist: d, aff };
                    if let Some(z) = residuals(&pred, &b, Some(refb)) {
                        consider(pred, z, &mut best);
                        used += 1;
                        self.stats.ref_candidates_evaluated += 1;
                    }
                }
            }
        }
        let (total, mode, dist, p, _pred, z) = best.expect("mode 00 is always available");
        let start = self.w.nbits;
        self.w.put_bits(mode as u128, 2);
        if mode == 3 {
            let mut v = (dist - 1) as u64;
            loop {
                let byte = (v & 0x7F) as u8;
                v >>= 7;
                if v == 0 {
                    self.w.put_bits(byte as u128, 8);
                    break;
                }
                self.w.put_bits((byte | 0x80) as u128, 8);
            }
        }
        self.w.put_bits(p as u128, 4);
        let hb = self.w.nbits - start;
        for &v in &z {
            self.w.put_gamma((v >> p) + 1);
            if p > 0 {
                self.w.put_bits(v & ((1u128 << p) - 1), p);
            }
        }
        debug_assert_eq!(self.w.nbits - start, total);
        self.stats.blocks += 1;
        self.stats.mode_counts[mode as usize] += 1;
        self.stats.header_bits += hb;
        self.stats.residual_bits += total - hb;
        let tri_coords: [Option<[f64; 16]>; 10] = std::array::from_fn(|i| affine_coords(&b, TRIPLES[i]));
        self.coords.push(tri_coords);
        self.window.push(b);
    }
}

/// Decode `count` blocks given their junctions (from the masked grammar).
pub fn decode_blocks(data: &[u8], valid_bits: u64, junctions: &[[V2; 5]]) -> Result<Vec<Block>> {
    let mut r = BitReader::new(data, valid_bits);
    let mut out: Vec<Block> = Vec::with_capacity(junctions.len());
    for (bi, j) in junctions.iter().enumerate() {
        let mode = r.bits(2)? as u32;
        let pred = match mode {
            0 => Predictor::Zero,
            1 => Predictor::Third,
            2 => Predictor::Smooth,
            _ => {
                let d = leb_get_bits(&mut r)? + 1;
                if d as usize > bi.min(WINDOW) {
                    return err("geometry: reference distance outside window");
                }
                let d = d as usize;
                let tri = match target_triple(j) {
                    Some(t) => t,
                    None => return err("geometry: mode 11 unavailable for singular target"),
                };
                let aff = match Affine::new(j, &out[bi - d].j, tri) {
                    Some(a) => a,
                    None => return err("geometry: singular or overflowing reference"),
                };
                Predictor::Ref { dist: d, aff }
            }
        };
        let p = r.bits(4)? as u32;
        let refb = if let Predictor::Ref { dist, .. } = pred { Some(out[bi - dist].clone()) } else { None };
        let mut blk = Block { j: *j, h0: [[0; 2]; 4], h1: [[0; 2]; 4] };
        for s in 0..4 {
            let h1_prev = if s > 0 { Some(blk.h1[s - 1]) } else { None };
            let ph0 = match pred.pred_h0(s, j, h1_prev, refb.as_ref()) {
                Some(v) => v,
                None => return err("geometry: predictor unavailable"),
            };
            for i in 0..2 {
                let rr = read_residual(&mut r, p)?;
                blk.h0[s][i] = add_res(ph0[i], rr)?;
            }
            let ph1 = match pred.pred_h1(s, j, blk.h0[s], refb.as_ref()) {
                Some(v) => v,
                None => return err("geometry: predictor unavailable"),
            };
            for i in 0..2 {
                let rr = read_residual(&mut r, p)?;
                blk.h1[s][i] = add_res(ph1[i], rr)?;
            }
            for pt in [blk.p1(s), blk.p2(s)] {
                if pt[0].unsigned_abs() >= COORD_LIMIT || pt[1].unsigned_abs() >= COORD_LIMIT {
                    return err("geometry: control point out of bounds");
                }
            }
        }
        out.push(blk);
    }
    if r.remaining() != 0 {
        return err("geometry: leftover bits");
    }
    Ok(out)
}

fn read_residual(r: &mut BitReader, p: u32) -> Result<i128> {
    let n = r.gamma()?;
    let hi = n - 1;
    if p > 0 && hi.leading_zeros() < p {
        return err("geometry: residual too large");
    }
    let z = (hi << p) | r.bits(p)?;
    if z >= (1u128 << 127) {
        return err("geometry: residual too large");
    }
    let v = unzig(z);
    if v.unsigned_abs() >= BOUND {
        return err("geometry: residual out of bounds");
    }
    Ok(v)
}

fn add_res(pred: i128, r: i128) -> Result<i128> {
    match pred.checked_add(r) {
        Some(v) if v.unsigned_abs() < COORD_LIMIT * 2 => Ok(v),
        _ => err("geometry: handle out of bounds"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rounding() {
        assert_eq!(round_div(3, 2), 2);
        assert_eq!(round_div(5, 2), 2);
        assert_eq!(round_div(-3, 2), -2);
        assert_eq!(round_div(-5, 2), -2);
        assert_eq!(round_div(-7, 3), -2);
        assert_eq!(round_div(7, 3), 2);
        assert_eq!(round_div(8, 3), 3);
    }
    #[test]
    fn zigzag() {
        for v in [0i128, 1, -1, 2, -2, i64::MAX as i128, -(1i128 << 120)] {
            assert_eq!(unzig(zig(v)), v);
        }
    }
    fn blk(seed: i128) -> Block {
        let j = [[0, 0], [100 + seed, 7], [200, 50 - seed], [260, 160], [300 + seed, 300]];
        Block { j, h0: [[10, 3], [20 + seed, -4], [5, 9], [-3, 2]], h1: [[7, -1], [3, 3 + seed], [0, 0], [11, 12]] }
    }
    #[test]
    fn encode_decode_blocks() {
        let mut enc = Encoder::new();
        let mut js = Vec::new();
        let mut bs = Vec::new();
        for i in 0..40 {
            let b = blk(i % 5);
            js.push(b.j);
            bs.push(b.clone());
            enc.encode_block(b);
        }
        let (buf, bits) = enc.w.clone().into_parts();
        let dec = decode_blocks(&buf, bits, &js).unwrap();
        assert_eq!(dec, bs);
        assert!(enc.stats.mode_counts[3] > 0);
    }

    /// REV1 lemma check: for nested mode sets M ⊆ M', every block costs at most as many bits under M',
    /// so the total is monotone; every restricted stream decodes exactly; only allowed modes are used.
    #[test]
    fn restricted_modes_monotone_and_decodable() {
        let masks = [0b0001u8, 0b0011, 0b0111, 0b1111];
        let mut totals = Vec::new();
        for &m in &masks {
            let mut enc = Encoder::with_modes(m);
            let mut js = Vec::new();
            let mut bs = Vec::new();
            for i in 0..60 {
                let b = blk((i * 7) % 11 - 3);
                js.push(b.j);
                bs.push(b.clone());
                enc.encode_block(b);
            }
            for mode in 0..4 {
                if m & (1 << mode) == 0 {
                    assert_eq!(enc.stats.mode_counts[mode], 0, "mode {} used although not allowed", mode);
                }
            }
            let (buf, bits) = enc.w.clone().into_parts();
            assert_eq!(decode_blocks(&buf, bits, &js).unwrap(), bs);
            totals.push(bits);
        }
        for w in totals.windows(2) {
            assert!(w[1] <= w[0], "bits not monotone over nested mode sets: {:?}", totals);
        }
        // the default encoder is the all-modes encoder
        let mut a = Encoder::new();
        let mut b = Encoder::with_modes(ALL_MODES);
        for i in 0..20 {
            a.encode_block(blk(i % 4));
            b.encode_block(blk(i % 4));
        }
        assert_eq!(a.w.clone().into_parts(), b.w.clone().into_parts());
    }
}
