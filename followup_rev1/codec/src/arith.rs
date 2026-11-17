//! Witten–Neal–Cleary 32-bit integer arithmetic coder with canonical termination (FORMAT.md §10).
use crate::bits::BitWriter;
use crate::error::{err, Result};

const TOP: u64 = 0xFFFF_FFFF;
const HALF: u64 = 1 << 31;
const Q1: u64 = 1 << 30;
const Q3: u64 = 3 << 30;
pub const MAX_TOTAL: u64 = 1 << 16;

pub struct Encoder {
    low: u64,
    high: u64,
    pending: u64,
    out: BitWriter,
}

impl Default for Encoder {
    fn default() -> Self {
        Self::new()
    }
}

impl Encoder {
    pub fn new() -> Self {
        Encoder { low: 0, high: TOP, pending: 0, out: BitWriter::new() }
    }
    fn emit(&mut self, bit: u32) {
        self.out.put_bit(bit);
        while self.pending > 0 {
            self.out.put_bit(bit ^ 1);
            self.pending -= 1;
        }
    }
    pub fn encode(&mut self, cl: u64, ch: u64, total: u64) {
        debug_assert!(cl < ch && ch <= total && total <= MAX_TOTAL);
        let range = self.high - self.low + 1;
        self.high = self.low + range * ch / total - 1;
        self.low += range * cl / total;
        loop {
            if self.high < HALF {
                self.emit(0);
            } else if self.low >= HALF {
                self.emit(1);
                self.low -= HALF;
                self.high -= HALF;
            } else if self.low >= Q1 && self.high < Q3 {
                self.pending += 1;
                self.low -= Q1;
                self.high -= Q1;
            } else {
                break;
            }
            self.low <<= 1;
            self.high = (self.high << 1) | 1;
        }
    }
    pub fn finish(mut self) -> (Vec<u8>, u64) {
        self.pending += 1;
        if self.low < Q1 {
            self.emit(0);
        } else {
            self.emit(1);
        }
        self.out.into_parts()
    }
}

pub struct Decoder<'a> {
    data: &'a [u8],
    valid: u64,
    pos: u64,
    low: u64,
    high: u64,
    value: u64,
    shifts: u64,
}

impl<'a> Decoder<'a> {
    pub fn new(data: &'a [u8], valid: u64) -> Self {
        let mut d = Decoder { data, valid, pos: 0, low: 0, high: TOP, value: 0, shifts: 0 };
        for _ in 0..32 {
            d.value = (d.value << 1) | d.next_bit();
        }
        d
    }
    fn next_bit(&mut self) -> u64 {
        let b = if self.pos < self.valid {
            ((self.data[(self.pos >> 3) as usize] >> (7 - (self.pos & 7))) & 1) as u64
        } else {
            0
        };
        self.pos += 1;
        b
    }
    /// Cumulative target in [0, total).
    pub fn target(&self, total: u64) -> u64 {
        let range = self.high - self.low + 1;
        ((self.value - self.low + 1) * total - 1) / range
    }
    pub fn consume(&mut self, cl: u64, ch: u64, total: u64) {
        let range = self.high - self.low + 1;
        self.high = self.low + range * ch / total - 1;
        self.low += range * cl / total;
        loop {
            if self.high < HALF {
            } else if self.low >= HALF {
                self.low -= HALF;
                self.high -= HALF;
                self.value -= HALF;
            } else if self.low >= Q1 && self.high < Q3 {
                self.low -= Q1;
                self.high -= Q1;
                self.value -= Q1;
            } else {
                break;
            }
            self.low <<= 1;
            self.high = (self.high << 1) | 1;
            self.value = (self.value << 1) | self.next_bit();
            self.shifts += 1;
        }
    }
    /// Decode one symbol given cumulative frequencies `cum` (len = nsym+1, cum[0]=0).
    pub fn decode(&mut self, cum: &[u64]) -> Result<usize> {
        let total = *cum.last().unwrap();
        let t = self.target(total);
        // linear scan; alphabets are tiny (<= 9 symbols)
        let mut s = 0;
        while s + 1 < cum.len() && cum[s + 1] <= t {
            s += 1;
        }
        if s + 1 >= cum.len() {
            return err("arith: target outside alphabet");
        }
        self.consume(cum[s], cum[s + 1], total);
        Ok(s)
    }
    /// Canonical termination check (FORMAT.md §10).
    pub fn finish(&self) -> Result<()> {
        let expect = if self.low < Q1 { Q1 } else { HALF };
        if self.valid != self.shifts + 2 {
            return err("arith: bit count does not match canonical termination");
        }
        if self.value != expect {
            return err("arith: non-canonical termination bits");
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn roundtrip_random() {
        let mut seed: u64 = 12345;
        for trial in 0..200 {
            let n = (trial * 7) % 300;
            let mut syms = Vec::new();
            let mut freqs: Vec<Vec<u64>> = Vec::new();
            let mut enc = Encoder::new();
            for _ in 0..n {
                seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
                let k = 2 + (seed >> 60) as usize % 7;
                let f: Vec<u64> = (0..k).map(|i| 1 + ((seed >> (i * 5)) & 0x3FF)).collect();
                let s = ((seed >> 33) as usize) % k;
                let cl: u64 = f[..s].iter().sum();
                let total: u64 = f.iter().sum();
                enc.encode(cl, cl + f[s], total);
                syms.push(s);
                freqs.push(f);
            }
            let (buf, bits) = enc.finish();
            assert!(bits >= 2);
            let mut dec = Decoder::new(&buf, bits);
            for (i, f) in freqs.iter().enumerate() {
                let mut cum = vec![0u64];
                for &x in f {
                    cum.push(cum.last().unwrap() + x);
                }
                assert_eq!(dec.decode(&cum).unwrap(), syms[i]);
            }
            dec.finish().unwrap();
        }
    }
    #[test]
    fn golden_empty() {
        let (buf, bits) = Encoder::new().finish();
        assert_eq!(bits, 2);
        assert_eq!(buf, vec![0b0100_0000]);
    }
}
