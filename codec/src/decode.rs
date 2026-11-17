//! Strict decoder for the SVGX v1 union (FORMAT.md §1, §11, §12).
use crate::bits::check_padding;
use crate::brotli;
use crate::container::{Header, Schedule, HEADER_LEN, MAX_SOURCE};
use crate::crc32::crc32;
use crate::error::{err, Error, Result};
use crate::geometry;
use crate::numeric::{self, grid_value, parse_lexeme};
use crate::path::{self, Tok, V2};
use crate::spelling::{self, HoleCtx, Profile};

pub fn decode(f: &[u8]) -> Result<Vec<u8>> {
    if f.is_empty() {
        return err("empty compressed stream");
    }
    match f[0] {
        0x11 => decode_structured(f),
        0x91 => err("large-window Brotli marker 0x91 is rejected"),
        _ => brotli::decompress_strict(f, MAX_SOURCE as usize),
    }
}

struct HoleSlot {
    block: usize,
    seg: usize,
    arg: usize,
    rel: bool,
}

pub fn decode_structured(f: &[u8]) -> Result<Vec<u8>> {
    let h = Header::parse(f)?;
    let profile = Profile::from_u8(h.profile).ok_or_else(|| Error("bad profile".into()))?;
    let lens = [h.literal_len, h.schedule_len, h.geometry_len, h.spelling_len, h.escape_len];
    let mut secs: Vec<&[u8]> = Vec::with_capacity(5);
    let mut off = HEADER_LEN;
    for n in lens {
        secs.push(&f[off..off + n as usize]);
        off += n as usize;
    }
    let (lit, sch, geo, spl, esc) = (secs[0], secs[1], secs[2], secs[3], secs[4]);
    check_padding(geo, h.geometry_bits, "geometry")?;
    if profile == Profile::D || h.hole_count == 0 {
        if h.spelling_len != 0 || h.spelling_bits != 0 {
            return err("spelling section must be empty");
        }
    } else {
        check_padding(spl, h.spelling_bits, "spelling")?;
        if h.spelling_bits == 0 {
            return err("spelling section missing");
        }
    }
    let u = brotli::decompress_strict(lit, h.source_length as usize)?;
    let sched_raw = brotli::decompress_strict(sch, 1 << 31)?;
    let sched = Schedule::parse(&sched_raw, h.hole_count)?;
    // escape descriptors
    let mut escapes = Vec::new();
    if h.escape_count == 0 {
        if h.escape_len != 0 {
            return err("escape section must be empty");
        }
    } else {
        if h.escape_len == 0 {
            return err("escape section missing");
        }
        let raw = brotli::decompress_strict(esc, 64 * (h.escape_count as usize + 1))?;
        let mut p = 0;
        for _ in 0..h.escape_count {
            escapes.push(numeric::deserialize(&raw, &mut p)?);
        }
        if p != raw.len() {
            return err("escape stream: trailing bytes");
        }
    }
    if profile == Profile::D && h.escape_count != h.hole_count {
        return err("D profile: escape count must equal hole count");
    }
    // hole positions in U
    let mut pos = Vec::with_capacity(sched.gaps.len());
    let mut acc: u64 = 0;
    for &g in &sched.gaps {
        acc += g;
        if acc > u.len() as u64 {
            return err("schedule: hole position beyond U");
        }
        pos.push(acc as usize);
    }
    // per path: masked parse, junctions, hole slots
    let mut junctions: Vec<[V2; 5]> = Vec::new();
    let mut slots: Vec<HoleSlot> = Vec::with_capacity(pos.len());
    let mut hole_k: Vec<u32> = Vec::with_capacity(pos.len());
    let mut prev_end: u64 = 0;
    let mut hi = 0usize;
    for pe in &sched.paths {
        let start = prev_end + pe.start_delta;
        let end = start + pe.u_len;
        if end > u.len() as u64 {
            return err("schedule: path span beyond U");
        }
        prev_end = end;
        let (start, end) = (start as usize, end as usize);
        let nh = (pe.n_blocks * 16) as usize;
        let own = &pos[hi..hi + nh];
        let mut rel = Vec::with_capacity(nh);
        for &p in own {
            if p < start || p > end {
                return err("schedule: hole outside its path span");
            }
            rel.push(p - start);
        }
        let span = &u[start..end];
        let groups = path::parse(span, &rel).map_err(|_| Error("masked path grammar mismatch".into()))?;
        let blocks = path::blocks(&groups);
        if blocks.len() as u64 != pe.n_blocks {
            return err("masked path: block count mismatch");
        }
        let mut in_block = vec![usize::MAX; groups.len()];
        for (bi, b) in blocks.iter().enumerate() {
            for &g in b {
                in_block[g] = bi;
            }
        }
        // holes exactly at block control slots, in order
        let mut expect = 0usize;
        for (gi, g) in groups.iter().enumerate() {
            for (a, t) in g.args.iter().enumerate() {
                let should = in_block[gi] != usize::MAX && a < 4;
                match (t, should) {
                    (Tok::Hole(i), true) => {
                        if *i != expect {
                            return err("masked path: hole order mismatch");
                        }
                        expect += 1;
                    }
                    (Tok::Hole(_), false) => return err("masked path: hole outside a block control slot"),
                    (Tok::Lit { .. }, true) => return err("masked path: missing hole"),
                    _ => {}
                }
            }
        }
        let k = pe.k;
        let pts = path::walk(&groups, |g, a| match groups[g].args[a] {
            Tok::Lit { start: s, end: e } => {
                let l = parse_lexeme(&span[s..e]).map_err(|_| path::PathErr)?;
                grid_value(&l, k).ok_or(path::PathErr)
            }
            Tok::Hole(_) => Err(path::PathErr),
        })
        .map_err(|_| Error("masked path: literal coordinate off-grid or out of bounds".into()))?;
        let base_block = junctions.len();
        for (bi, b) in blocks.iter().enumerate() {
            let mut j = [[0i128; 2]; 5];
            for (s, &gi) in b.iter().enumerate() {
                j[s] = pts[gi].0;
                if s == 3 {
                    j[4] = pts[gi].1;
                }
                for a in 0..4 {
                    slots.push(HoleSlot { block: base_block + bi, seg: s, arg: a, rel: groups[gi].rel });
                    hole_k.push(k);
                }
            }
            junctions.push(j);
        }
        hi += nh;
    }
    if hi != pos.len() {
        return err("schedule: unassigned holes");
    }
    let blocks = geometry::decode_blocks(geo, h.geometry_bits, &junctions)?;
    // hole values X and roles
    let mut ctx = Vec::with_capacity(slots.len());
    for (i, s) in slots.iter().enumerate() {
        let b = &blocks[s.block];
        let p = if s.arg < 2 { b.p1(s.seg) } else { b.p2(s.seg) };
        let p0 = b.j[s.seg];
        let comp = s.arg % 2;
        let x = if s.rel { p[comp] - p0[comp] } else { p[comp] };
        let role = 4 * s.rel as usize + 2 * (s.arg >= 2) as usize + comp;
        ctx.push(HoleCtx { role, x, k: hole_k[i] });
    }
    let lexemes = spelling::decode(profile, &ctx, spl, h.spelling_bits, &escapes)?;
    // reconstruct
    let total: usize = u.len() + lexemes.iter().map(|l| l.len()).sum::<usize>();
    if total as u64 != h.source_length {
        return err("reconstruction length mismatch");
    }
    let mut out = Vec::with_capacity(total);
    let mut cur = 0usize;
    for (i, &p) in pos.iter().enumerate() {
        out.extend_from_slice(&u[cur..p]);
        out.extend_from_slice(&lexemes[i]);
        cur = p;
    }
    out.extend_from_slice(&u[cur..]);
    if crc32(&out) != h.crc32 {
        return err("CRC-32 mismatch");
    }
    Ok(out)
}
