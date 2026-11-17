//! Fixed 60-byte SVGX v1 header (FORMAT.md §2) and the schedule section (§4).
use crate::bits::{leb_get, leb_put};
use crate::error::{err, Result};

pub const MARKER: u8 = 0x11;
pub const VERSION: u8 = 0x01;
pub const HEADER_LEN: usize = 60;
pub const MAX_SOURCE: u64 = 1 << 30;

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Header {
    pub profile: u8,
    pub source_length: u64,
    pub crc32: u32,
    pub literal_len: u32,
    pub schedule_len: u32,
    pub geometry_len: u32,
    pub geometry_bits: u64,
    pub spelling_len: u32,
    pub spelling_bits: u64,
    pub escape_len: u32,
    pub escape_count: u32,
    pub hole_count: u32,
}

impl Header {
    pub fn write(&self, out: &mut Vec<u8>) {
        out.push(MARKER);
        out.push(VERSION);
        out.push(self.profile);
        out.push(0);
        out.extend_from_slice(&self.source_length.to_le_bytes());
        out.extend_from_slice(&self.crc32.to_le_bytes());
        out.extend_from_slice(&self.literal_len.to_le_bytes());
        out.extend_from_slice(&self.schedule_len.to_le_bytes());
        out.extend_from_slice(&self.geometry_len.to_le_bytes());
        out.extend_from_slice(&self.geometry_bits.to_le_bytes());
        out.extend_from_slice(&self.spelling_len.to_le_bytes());
        out.extend_from_slice(&self.spelling_bits.to_le_bytes());
        out.extend_from_slice(&self.escape_len.to_le_bytes());
        out.extend_from_slice(&self.escape_count.to_le_bytes());
        out.extend_from_slice(&self.hole_count.to_le_bytes());
    }

    pub fn parse(f: &[u8]) -> Result<Header> {
        if f.len() < HEADER_LEN {
            return err("header: truncated");
        }
        if f[0] != MARKER {
            return err("header: bad marker");
        }
        if f[1] != VERSION {
            return err("header: unsupported version");
        }
        if !(1..=5).contains(&f[2]) {
            return err("header: bad profile");
        }
        if f[3] != 0 {
            return err("header: non-zero flags");
        }
        let u32_at = |o: usize| u32::from_le_bytes([f[o], f[o + 1], f[o + 2], f[o + 3]]);
        let u64_at = |o: usize| u64::from_le_bytes(f[o..o + 8].try_into().unwrap());
        let h = Header {
            profile: f[2],
            source_length: u64_at(4),
            crc32: u32_at(12),
            literal_len: u32_at(16),
            schedule_len: u32_at(20),
            geometry_len: u32_at(24),
            geometry_bits: u64_at(28),
            spelling_len: u32_at(36),
            spelling_bits: u64_at(40),
            escape_len: u32_at(48),
            escape_count: u32_at(52),
            hole_count: u32_at(56),
        };
        if h.source_length > MAX_SOURCE {
            return err("header: source too large");
        }
        let total = HEADER_LEN as u64
            + h.literal_len as u64
            + h.schedule_len as u64
            + h.geometry_len as u64
            + h.spelling_len as u64
            + h.escape_len as u64;
        if total != f.len() as u64 {
            return err("header: section lengths do not reconcile with file length");
        }
        if h.hole_count % 16 != 0 {
            return err("header: hole count not a multiple of 16");
        }
        Ok(h)
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PathEntry {
    pub start_delta: u64,
    pub u_len: u64,
    pub k: u32,
    pub n_blocks: u64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Schedule {
    pub paths: Vec<PathEntry>,
    pub gaps: Vec<u64>,
}

impl Schedule {
    pub fn serialize(&self) -> Vec<u8> {
        let mut o = Vec::new();
        leb_put(&mut o, self.paths.len() as u64);
        for p in &self.paths {
            leb_put(&mut o, p.start_delta);
            leb_put(&mut o, p.u_len);
            leb_put(&mut o, p.k as u64);
            leb_put(&mut o, p.n_blocks);
        }
        for &g in &self.gaps {
            leb_put(&mut o, g);
        }
        o
    }

    pub fn parse(data: &[u8], hole_count: u32) -> Result<Schedule> {
        let mut pos = 0;
        let lim = 1u64 << 32;
        let np = leb_get(data, &mut pos)?;
        if np >= lim {
            return err("schedule: too many paths");
        }
        let mut paths = Vec::new();
        let mut total_blocks: u64 = 0;
        for _ in 0..np {
            let start_delta = leb_get(data, &mut pos)?;
            let u_len = leb_get(data, &mut pos)?;
            let k = leb_get(data, &mut pos)?;
            let n_blocks = leb_get(data, &mut pos)?;
            if start_delta >= lim || u_len >= lim || n_blocks >= lim {
                return err("schedule: field out of bounds");
            }
            if k > 18 {
                return err("schedule: K out of bounds");
            }
            if n_blocks == 0 {
                return err("schedule: path without blocks");
            }
            total_blocks += n_blocks;
            paths.push(PathEntry { start_delta, u_len, k: k as u32, n_blocks });
        }
        if total_blocks * 16 != hole_count as u64 {
            return err("schedule: hole count mismatch");
        }
        let mut gaps = Vec::with_capacity(hole_count as usize);
        for _ in 0..hole_count {
            let g = leb_get(data, &mut pos)?;
            if g >= lim {
                return err("schedule: gap out of bounds");
            }
            gaps.push(g);
        }
        if pos != data.len() {
            return err("schedule: trailing bytes");
        }
        Ok(Schedule { paths, gaps })
    }
}
