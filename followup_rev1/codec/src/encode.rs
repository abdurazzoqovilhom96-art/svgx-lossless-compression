//! Encoder pipeline: XML scan → path models → shared sections → per-profile spelling → container.
use crate::brotli;
use crate::container::{Header, PathEntry, Schedule, HEADER_LEN, MAX_SOURCE};
use crate::crc32::crc32;
use crate::geometry::{self, Block, GeomStats};
use crate::numeric::{self, grid_value, k_minus_e, parse_lexeme, Descriptor, LexErr, Lexeme, MAX_K};
use crate::path::{self, Tok, V2};
use crate::spelling::{self, HoleCtx, Profile, RoleStats};
use crate::xml;
use std::collections::BTreeMap;

pub const MAX_PATH_VALUE: usize = 16 << 20;

#[derive(Clone, Debug)]
pub struct Hole {
    pub start: usize,
    pub end: usize,
    pub role: usize,
    pub x: i128,
    pub k: u32,
    pub desc: Descriptor,
}

#[derive(Clone, Debug)]
pub struct PathModel {
    pub span: (usize, usize),
    pub k: u32,
    pub blocks: Vec<Block>,
    pub holes: Vec<Hole>,
}

#[derive(Debug, Default)]
pub struct Analysis {
    pub file_reason: Option<&'static str>,
    pub candidates: u64,
    pub paths: Vec<PathModel>,
    pub path_reasons: BTreeMap<&'static str, u64>,
}

/// Analyse one candidate `d` value (absolute span in the input).
pub fn analyze_path(input: &[u8], span: (usize, usize)) -> Result<PathModel, &'static str> {
    let v = &input[span.0..span.1];
    if v.contains(&b'&') {
        return Err("entity");
    }
    if v.len() > MAX_PATH_VALUE {
        return Err("oversized_path");
    }
    let groups = path::parse(v, &[]).map_err(|_| "grammar")?;
    let blocks = path::blocks(&groups);
    if blocks.is_empty() {
        return Err("no_block");
    }
    let mut in_block = vec![false; groups.len()];
    for b in &blocks {
        for &g in b {
            in_block[g] = true;
        }
    }
    // parse every geometry-relevant lexeme
    let mut lex: BTreeMap<(usize, usize), Lexeme> = BTreeMap::new();
    let mut kmax: i32 = 0;
    for (gi, g) in groups.iter().enumerate() {
        let mut rel_args: Vec<usize> = path::endpoint_args(g.cmd).to_vec();
        if in_block[gi] {
            rel_args.extend_from_slice(&[0, 1, 2, 3]);
        }
        for a in rel_args {
            let (s, e) = match g.args[a] {
                Tok::Lit { start, end } => (start, end),
                Tok::Hole(_) => return Err("grammar"),
            };
            let l = match parse_lexeme(&v[s..e]) {
                Ok(l) => l,
                Err(LexErr::Bounds) => return Err("numeric_bounds"),
                Err(LexErr::Syntax) => return Err("grammar"),
            };
            kmax = kmax.max(k_minus_e(&l));
            lex.insert((gi, a), l);
        }
    }
    if kmax as u32 > MAX_K {
        return Err("grid_bounds");
    }
    let k = kmax.max(0) as u32;
    let mut vals: BTreeMap<(usize, usize), i128> = BTreeMap::new();
    for (key, l) in &lex {
        match grid_value(l, k) {
            Some(x) => {
                vals.insert(*key, x);
            }
            None => return Err("coordinate_bounds"),
        }
    }
    let pts = path::walk(&groups, |g, a| vals.get(&(g, a)).copied().ok_or(path::PathErr))
        .map_err(|_| "coordinate_bounds")?;
    let lim = 1u128 << 96;
    let ok = |p: V2| p[0].unsigned_abs() < lim && p[1].unsigned_abs() < lim;
    let mut models = Vec::with_capacity(blocks.len());
    let mut holes = Vec::with_capacity(blocks.len() * 16);
    for b in &blocks {
        let mut j = [[0i128; 2]; 5];
        let mut h0 = [[0i128; 2]; 4];
        let mut h1 = [[0i128; 2]; 4];
        for (s, &gi) in b.iter().enumerate() {
            let g = &groups[gi];
            let (p0, p3) = pts[gi];
            j[s] = p0;
            if s == 3 {
                j[4] = p3;
            }
            let x = |a: usize| vals[&(gi, a)];
            let base = if g.rel { p0 } else { [0, 0] };
            let p1 = [base[0] + x(0), base[1] + x(1)];
            let p2 = [base[0] + x(2), base[1] + x(3)];
            if !ok(p1) || !ok(p2) {
                return Err("coordinate_bounds");
            }
            h0[s] = [p1[0] - p0[0], p1[1] - p0[1]];
            h1[s] = [p3[0] - p2[0], p3[1] - p2[1]];
            for a in 0..4 {
                let (st, en) = match g.args[a] {
                    Tok::Lit { start, end } => (start, end),
                    _ => unreachable!(),
                };
                holes.push(Hole {
                    start: span.0 + st,
                    end: span.0 + en,
                    role: 4 * g.rel as usize + 2 * (a >= 2) as usize + (a % 2),
                    x: x(a),
                    k,
                    desc: lex[&(gi, a)].desc.clone(),
                });
            }
        }
        models.push(Block { j, h0, h1 });
    }
    Ok(PathModel { span, k, blocks: models, holes })
}

pub fn analyze(input: &[u8]) -> Analysis {
    let mut a = Analysis::default();
    if input.len() as u64 > MAX_SOURCE {
        a.file_reason = Some("too_large");
        return a;
    }
    let sc = xml::scan(input);
    if let Some(r) = sc.reason {
        a.file_reason = Some(r);
        return a;
    }
    a.candidates = sc.paths.len() as u64;
    for span in sc.paths {
        match analyze_path(input, span) {
            Ok(m) => {
                *a.path_reasons.entry("modeled").or_insert(0) += 1;
                a.paths.push(m);
            }
            Err(r) => *a.path_reasons.entry(r).or_insert(0) += 1,
        }
    }
    if a.paths.is_empty() && a.file_reason.is_none() {
        a.file_reason = Some(if a.candidates == 0 { "no_svg_paths" } else { "no_eligible_blocks" });
    }
    a
}

pub struct Common {
    pub literal: Vec<u8>,
    pub schedule: Vec<u8>,
    pub geometry: Vec<u8>,
    pub geometry_bits: u64,
    pub hole_count: u32,
    pub u_len: usize,
    pub gstats: GeomStats,
    pub ctx: Vec<HoleCtx>,
    pub ys: Vec<Vec<u8>>,
    pub ds: Vec<Descriptor>,
}

pub fn build_common(input: &[u8], a: &Analysis) -> Common {
    build_common_modes(input, a, geometry::ALL_MODES)
}

/// As `build_common`, with the geometry encoder restricted to the prediction modes in `modes` (REV1 ablation).
pub fn build_common_modes(input: &[u8], a: &Analysis, modes: u8) -> Common {
    let mut u: Vec<u8> = Vec::with_capacity(input.len());
    let mut sched = Schedule::default();
    let mut cursor = 0usize; // next input byte not yet copied into U
    let mut removed = 0usize;
    let mut prev_u_end = 0usize;
    let mut prev_hole_u = 0usize;
    let mut genc = geometry::Encoder::with_modes(modes);
    let mut ctx = Vec::new();
    let mut ys = Vec::new();
    let mut ds = Vec::new();
    for p in &a.paths {
        let u_start = p.span.0 - removed;
        let hole_bytes: usize = p.holes.iter().map(|h| h.end - h.start).sum();
        let u_end = p.span.1 - removed - hole_bytes;
        sched.paths.push(PathEntry {
            start_delta: (u_start - prev_u_end) as u64,
            u_len: (u_end - u_start) as u64,
            k: p.k,
            n_blocks: p.blocks.len() as u64,
        });
        prev_u_end = u_end;
        for h in &p.holes {
            u.extend_from_slice(&input[cursor..h.start]);
            cursor = h.end;
            let pos = h.start - removed;
            sched.gaps.push((pos - prev_hole_u) as u64);
            prev_hole_u = pos;
            removed += h.end - h.start;
            ctx.push(HoleCtx { role: h.role, x: h.x, k: h.k });
            ys.push(input[h.start..h.end].to_vec());
            ds.push(h.desc.clone());
        }
        for b in &p.blocks {
            genc.encode_block(b.clone());
        }
    }
    u.extend_from_slice(&input[cursor..]);
    let gstats = genc.stats.clone();
    let (geometry, geometry_bits) = genc.w.into_parts();
    Common {
        literal: brotli::compress(&u),
        schedule: brotli::compress(&sched.serialize()),
        geometry,
        geometry_bits,
        hole_count: ctx.len() as u32,
        u_len: u.len(),
        gstats,
        ctx,
        ys,
        ds,
    }
}

pub struct ProfileOut {
    pub profile: Profile,
    pub stream: Vec<u8>,
    pub spelling_len: usize,
    pub spelling_bits: u64,
    pub escape_len: usize,
    pub escape_count: usize,
    pub stats: Vec<RoleStats>,
}

pub fn build_profile(input: &[u8], c: &Common, profile: Profile) -> ProfileOut {
    let sp = spelling::encode(profile, &c.ctx, &c.ys, &c.ds);
    let escape = if sp.escapes.is_empty() {
        Vec::new()
    } else {
        let mut raw = Vec::new();
        for d in &sp.escapes {
            numeric::serialize(d, &mut raw);
        }
        brotli::compress(&raw)
    };
    let h = Header {
        profile: profile as u8,
        source_length: input.len() as u64,
        crc32: crc32(input),
        literal_len: c.literal.len() as u32,
        schedule_len: c.schedule.len() as u32,
        geometry_len: c.geometry.len() as u32,
        geometry_bits: c.geometry_bits,
        spelling_len: sp.bytes.len() as u32,
        spelling_bits: sp.bits,
        escape_len: escape.len() as u32,
        escape_count: sp.escapes.len() as u32,
        hole_count: c.hole_count,
    };
    let mut out = Vec::with_capacity(HEADER_LEN + c.literal.len() + c.schedule.len() + c.geometry.len() + sp.bytes.len() + escape.len());
    h.write(&mut out);
    out.extend_from_slice(&c.literal);
    out.extend_from_slice(&c.schedule);
    out.extend_from_slice(&c.geometry);
    out.extend_from_slice(&sp.bytes);
    out.extend_from_slice(&escape);
    ProfileOut {
        profile,
        stream: out,
        spelling_len: sp.bytes.len(),
        spelling_bits: sp.bits,
        escape_len: escape.len(),
        escape_count: sp.escapes.len(),
        stats: sp.stats,
    }
}

/// Final emitted stream: structured only when strictly smaller than raw Brotli (ties → raw).
pub fn choose_final<'a>(raw: &'a [u8], structured: Option<&'a [u8]>, force: bool) -> &'a [u8] {
    match structured {
        Some(s) if force || s.len() < raw.len() => s,
        _ => raw,
    }
}
