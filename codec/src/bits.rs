//! MSB-first bit packing and canonical LEB128.
use crate::error::{err, Result};

#[derive(Default, Clone)]
pub struct BitWriter {
    pub buf: Vec<u8>,
    pub nbits: u64,
}

impl BitWriter {
    pub fn new() -> Self {
        Self::default()
    }
    #[inline]
    pub fn put_bit(&mut self, bit: u32) {
        let idx = (self.nbits >> 3) as usize;
        if idx == self.buf.len() {
            self.buf.push(0);
        }
        if bit != 0 {
            self.buf[idx] |= 0x80 >> (self.nbits & 7);
        }
        self.nbits += 1;
    }
    /// Write the `n` low bits of `v`, most significant first.
    pub fn put_bits(&mut self, v: u128, n: u32) {
        let mut i = n;
        while i > 0 {
            i -= 1;
            self.put_bit(((v >> i) & 1) as u32);
        }
    }
    /// Elias gamma code of n >= 1.
    pub fn put_gamma(&mut self, n: u128) {
        debug_assert!(n >= 1);
        let l = 127 - n.leading_zeros();
        for _ in 0..l {
            self.put_bit(0);
        }
        self.put_bits(n, l + 1);
    }
    pub fn into_parts(self) -> (Vec<u8>, u64) {
        (self.buf, self.nbits)
    }
}

/// Strict reader: reading past `valid` bits is an error.
pub struct BitReader<'a> {
    data: &'a [u8],
    valid: u64,
    pub pos: u64,
}

impl<'a> BitReader<'a> {
    pub fn new(data: &'a [u8], valid: u64) -> Self {
        BitReader { data, valid, pos: 0 }
    }
    #[inline]
    pub fn bit(&mut self) -> Result<u32> {
        if self.pos >= self.valid {
            return err("geometry: read past valid bits");
        }
        let b = (self.data[(self.pos >> 3) as usize] >> (7 - (self.pos & 7))) & 1;
        self.pos += 1;
        Ok(b as u32)
    }
    pub fn bits(&mut self, n: u32) -> Result<u128> {
        let mut v: u128 = 0;
        for _ in 0..n {
            v = (v << 1) | self.bit()? as u128;
        }
        Ok(v)
    }
    pub fn gamma(&mut self) -> Result<u128> {
        let mut zeros = 0u32;
        while self.bit()? == 0 {
            zeros += 1;
            if zeros > 127 {
                return err("geometry: gamma code too long");
            }
        }
        let rest = self.bits(zeros)?;
        Ok((1u128 << zeros) | rest)
    }
    pub fn remaining(&self) -> u64 {
        self.valid - self.pos
    }
}

/// Validate section length vs. valid bits and zero padding.
pub fn check_padding(data: &[u8], valid: u64, what: &str) -> Result<()> {
    let need = (valid + 7) / 8;
    if need != data.len() as u64 {
        return err(&format!("{}: length {} does not match {} valid bits", what, data.len(), valid));
    }
    if valid % 8 != 0 {
        let last = data[data.len() - 1];
        let used = (valid % 8) as u32;
        let mask: u8 = 0xFFu8 >> used;
        if last & mask != 0 {
            return err(&format!("{}: non-zero padding bits", what));
        }
    }
    Ok(())
}

pub fn leb_put(out: &mut Vec<u8>, mut v: u64) {
    loop {
        let b = (v & 0x7F) as u8;
        v >>= 7;
        if v == 0 {
            out.push(b);
            return;
        }
        out.push(b | 0x80);
    }
}

pub fn leb_len(mut v: u64) -> u32 {
    let mut n = 1;
    while v >= 0x80 {
        v >>= 7;
        n += 1;
    }
    n
}

/// Canonical LEB128 read from a byte slice.
pub fn leb_get(data: &[u8], pos: &mut usize) -> Result<u64> {
    let mut v: u64 = 0;
    let mut shift = 0u32;
    let start = *pos;
    loop {
        if *pos >= data.len() {
            return err("leb128: truncated");
        }
        let b = data[*pos];
        *pos += 1;
        if shift >= 63 && (b & 0x7F) > 1 {
            return err("leb128: overflow");
        }
        v |= ((b & 0x7F) as u64) << shift;
        if b & 0x80 == 0 {
            if b == 0 && *pos - start > 1 {
                return err("leb128: non-canonical");
            }
            return Ok(v);
        }
        shift += 7;
        if shift > 63 {
            return err("leb128: too long");
        }
    }
}

/// Canonical LEB128 read from a bit stream (each octet as 8 bits MSB-first).
pub fn leb_get_bits(r: &mut BitReader) -> Result<u64> {
    let mut v: u64 = 0;
    let mut shift = 0u32;
    let mut count = 0;
    loop {
        let b = r.bits(8)? as u8;
        count += 1;
        if shift >= 63 && (b & 0x7F) > 1 {
            return err("leb128: overflow");
        }
        v |= ((b & 0x7F) as u64) << shift;
        if b & 0x80 == 0 {
            if b == 0 && count > 1 {
                return err("leb128: non-canonical");
            }
            return Ok(v);
        }
        shift += 7;
        if shift > 63 {
            return err("leb128: too long");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn leb_roundtrip() {
        for v in [0u64, 1, 127, 128, 300, 4095, u32::MAX as u64, u64::MAX] {
            let mut o = Vec::new();
            leb_put(&mut o, v);
            assert_eq!(o.len() as u32, leb_len(v));
            let mut p = 0;
            assert_eq!(leb_get(&o, &mut p).unwrap(), v);
            assert_eq!(p, o.len());
        }
        let mut p = 0;
        assert!(leb_get(&[0x80, 0x00], &mut p).is_err());
    }
    #[test]
    fn gamma_roundtrip() {
        let mut w = BitWriter::new();
        let vals = [1u128, 2, 3, 4, 5, 1000, 1u128 << 100, (1u128 << 127)];
        for &v in &vals {
            w.put_gamma(v);
        }
        let (buf, n) = w.into_parts();
        let mut r = BitReader::new(&buf, n);
        for &v in &vals {
            assert_eq!(r.gamma().unwrap(), v);
        }
        assert_eq!(r.remaining(), 0);
    }
}
