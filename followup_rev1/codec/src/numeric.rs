//! Number lexemes, descriptors (sign, w, k, dot, exponent bytes), grid values and exact rendering.
use crate::error::{err, Result};

pub const MAX_W: usize = 38;
pub const MAX_EXP_DIGITS: usize = 6;
pub const MAX_E: i32 = 18;
pub const MAX_K: u32 = 18;
pub const MAX_TOKEN: usize = 64;
pub const GRID_LIMIT: u128 = 1u128 << 96;

const fn make_pow10() -> [u128; 39] {
    let mut t = [0u128; 39];
    let mut i = 0;
    let mut v: u128 = 1;
    while i < 39 {
        t[i] = v;
        if i < 38 {
            v *= 10;
        }
        i += 1;
    }
    t
}
pub static POW10: [u128; 39] = make_pow10();

#[inline]
pub fn pow10(n: u32) -> Option<u128> {
    POW10.get(n as usize).copied()
}

#[derive(Clone, PartialEq, Eq, Debug, Hash)]
pub struct Descriptor {
    pub sign: u8, // 0 none, 1 '-', 2 '+'
    pub w: u8,
    pub k: u8,
    pub dot: bool,
    pub exp: Vec<u8>,
}

#[derive(Clone, Debug)]
pub struct Lexeme {
    pub desc: Descriptor,
    pub mant: u128,
    pub e: i32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LexErr {
    Syntax,
    Bounds,
}

#[inline]
pub fn is_digit(b: u8) -> bool {
    b.is_ascii_digit()
}

/// Greedy scan of a number per the SVG 1.1 grammar in `bytes[start..limit]`; returns the end.
pub fn scan_number(bytes: &[u8], start: usize, limit: usize, allow_sign: bool) -> Option<usize> {
    let mut p = start;
    if allow_sign && p < limit && (bytes[p] == b'+' || bytes[p] == b'-') {
        p += 1;
    }
    let int_start = p;
    while p < limit && is_digit(bytes[p]) {
        p += 1;
    }
    let nint = p - int_start;
    let mut nfrac = 0;
    if p < limit && bytes[p] == b'.' {
        let q = p + 1;
        let mut r = q;
        while r < limit && is_digit(bytes[r]) {
            r += 1;
        }
        nfrac = r - q;
        if nint > 0 || nfrac > 0 {
            p = r;
        }
    }
    if nint + nfrac == 0 {
        return None;
    }
    if p < limit && (bytes[p] == b'e' || bytes[p] == b'E') {
        let mut q = p + 1;
        if q < limit && (bytes[q] == b'+' || bytes[q] == b'-') {
            q += 1;
        }
        if q < limit && is_digit(bytes[q]) {
            while q < limit && is_digit(bytes[q]) {
                q += 1;
            }
            p = q;
        }
    }
    Some(p)
}

/// Parse an exact lexeme (whole slice) with the frozen bounds.
pub fn parse_lexeme(b: &[u8]) -> std::result::Result<Lexeme, LexErr> {
    if b.is_empty() || b.len() > MAX_TOKEN {
        return Err(if b.is_empty() { LexErr::Syntax } else { LexErr::Bounds });
    }
    let mut p = 0;
    let sign = match b[0] {
        b'-' => {
            p = 1;
            1
        }
        b'+' => {
            p = 1;
            2
        }
        _ => 0,
    };
    let mut digits: Vec<u8> = Vec::new();
    while p < b.len() && is_digit(b[p]) {
        digits.push(b[p]);
        p += 1;
    }
    let nint = digits.len();
    let mut dot = false;
    if p < b.len() && b[p] == b'.' {
        dot = true;
        p += 1;
        while p < b.len() && is_digit(b[p]) {
            digits.push(b[p]);
            p += 1;
        }
    }
    let w = digits.len();
    let k = w - nint;
    if w == 0 {
        return Err(LexErr::Syntax);
    }
    let mut exp: Vec<u8> = Vec::new();
    let mut e: i32 = 0;
    if p < b.len() {
        if b[p] != b'e' && b[p] != b'E' {
            return Err(LexErr::Syntax);
        }
        let es = p;
        p += 1;
        let mut neg = false;
        if p < b.len() && (b[p] == b'+' || b[p] == b'-') {
            neg = b[p] == b'-';
            p += 1;
        }
        let ds = p;
        while p < b.len() && is_digit(b[p]) {
            p += 1;
        }
        let nd = p - ds;
        if nd == 0 || p != b.len() {
            return Err(LexErr::Syntax);
        }
        if nd > MAX_EXP_DIGITS {
            return Err(LexErr::Bounds);
        }
        let mut v: i32 = 0;
        for &c in &b[ds..p] {
            v = v * 10 + (c - b'0') as i32;
        }
        e = if neg { -v } else { v };
        exp.extend_from_slice(&b[es..p]);
    }
    if w > MAX_W {
        return Err(LexErr::Bounds);
    }
    if e.abs() > MAX_E {
        return Err(LexErr::Bounds);
    }
    let mut mant: u128 = 0;
    for &c in &digits {
        mant = mant * 10 + (c - b'0') as u128;
    }
    Ok(Lexeme { desc: Descriptor { sign, w: w as u8, k: k as u8, dot, exp }, mant, e })
}

/// `k - e` of a lexeme (used for the path grid K).
pub fn k_minus_e(l: &Lexeme) -> i32 {
    l.desc.k as i32 - l.e
}

/// Grid value X = v * 10^K; None if off-grid or out of bounds.
pub fn grid_value(l: &Lexeme, kgrid: u32) -> Option<i128> {
    let s = l.e - l.desc.k as i32 + kgrid as i32;
    if s < 0 {
        return None;
    }
    let p = pow10(s as u32)?;
    let m = l.mant.checked_mul(p)?;
    if m >= GRID_LIMIT {
        return None;
    }
    let x = m as i128;
    Some(if l.desc.sign == 1 { -x } else { x })
}

pub fn exp_value(exp: &[u8]) -> i32 {
    if exp.is_empty() {
        return 0;
    }
    let mut p = 1;
    let mut neg = false;
    if exp[p] == b'+' || exp[p] == b'-' {
        neg = exp[p] == b'-';
        p += 1;
    }
    let mut v: i32 = 0;
    for &c in &exp[p..] {
        v = v * 10 + (c - b'0') as i32;
    }
    if neg {
        -v
    } else {
        v
    }
}

/// Render a descriptor exactly at (X, K); None when inapplicable.
pub fn render(d: &Descriptor, x: i128, kgrid: u32) -> Option<Vec<u8>> {
    let e = exp_value(&d.exp);
    let t = d.k as i32 - e - kgrid as i32;
    let ax = x.unsigned_abs();
    let m: u128 = if t >= 0 {
        if ax == 0 {
            0
        } else {
            let p = pow10(t as u32)?;
            ax.checked_mul(p)?
        }
    } else {
        let p = pow10((-t) as u32)?;
        if ax % p != 0 {
            return None;
        }
        ax / p
    };
    if m >= POW10[d.w as usize] {
        return None;
    }
    if x < 0 && d.sign != 1 {
        return None;
    }
    if x > 0 && d.sign == 1 {
        return None;
    }
    let mut out = Vec::with_capacity(d.w as usize + 3 + d.exp.len());
    match d.sign {
        1 => out.push(b'-'),
        2 => out.push(b'+'),
        _ => {}
    }
    let s = m.to_string();
    let w = d.w as usize;
    let mut digits = Vec::with_capacity(w);
    for _ in s.len()..w {
        digits.push(b'0');
    }
    digits.extend_from_slice(s.as_bytes());
    let k = d.k as usize;
    if d.dot {
        out.extend_from_slice(&digits[..w - k]);
        out.push(b'.');
        out.extend_from_slice(&digits[w - k..]);
    } else {
        out.extend_from_slice(&digits);
    }
    out.extend_from_slice(&d.exp);
    Some(out)
}

pub fn serialize(d: &Descriptor, out: &mut Vec<u8>) {
    let has_exp = !d.exp.is_empty();
    out.push(d.sign | ((d.dot as u8) << 2) | ((has_exp as u8) << 3));
    out.push(d.w);
    out.push(d.k);
    if has_exp {
        out.push(d.exp.len() as u8);
        out.extend_from_slice(&d.exp);
    }
}

pub fn deserialize(data: &[u8], pos: &mut usize) -> Result<Descriptor> {
    if *pos + 3 > data.len() {
        return err("descriptor: truncated");
    }
    let f = data[*pos];
    let w = data[*pos + 1];
    let k = data[*pos + 2];
    *pos += 3;
    if f & 0xF0 != 0 || (f & 3) == 3 {
        return err("descriptor: bad flags");
    }
    let sign = f & 3;
    let dot = f & 4 != 0;
    let has_exp = f & 8 != 0;
    if w < 1 || w as usize > MAX_W || k > w || (!dot && k != 0) {
        return err("descriptor: bad w/k");
    }
    let mut exp = Vec::new();
    if has_exp {
        if *pos >= data.len() {
            return err("descriptor: truncated exponent");
        }
        let l = data[*pos] as usize;
        *pos += 1;
        if !(2..=2 + MAX_EXP_DIGITS).contains(&l) || *pos + l > data.len() {
            return err("descriptor: bad exponent length");
        }
        exp.extend_from_slice(&data[*pos..*pos + l]);
        *pos += l;
        if exp[0] != b'e' && exp[0] != b'E' {
            return err("descriptor: bad exponent letter");
        }
        let mut p = 1;
        if exp[p] == b'+' || exp[p] == b'-' {
            p += 1;
        }
        if p >= exp.len() || !exp[p..].iter().all(|c| c.is_ascii_digit()) || exp.len() - p > MAX_EXP_DIGITS {
            return err("descriptor: bad exponent digits");
        }
        if exp_value(&exp).abs() > MAX_E {
            return err("descriptor: exponent out of bounds");
        }
    }
    Ok(Descriptor { sign, w, k, dot, exp })
}

#[cfg(test)]
mod tests {
    use super::*;
    fn rt(s: &str, k: u32) {
        let l = parse_lexeme(s.as_bytes()).unwrap();
        let x = grid_value(&l, k).unwrap();
        assert_eq!(render(&l.desc, x, k).unwrap(), s.as_bytes(), "{}", s);
    }
    #[test]
    fn descriptors_roundtrip() {
        for (s, k) in [(".5", 1), ("0.50", 2), ("+5E-01", 1), ("5.", 0), ("-0", 0), ("1e-005", 5),
                       ("-.5", 3), ("00.5", 1), ("12", 0), ("1.5e2", 0), ("-0.000", 3), ("7E+0", 4)] {
            rt(s, k);
        }
    }
    #[test]
    fn scan() {
        let b = b"1.5.5e3-2e+x";
        let e1 = scan_number(b, 0, b.len(), true).unwrap();
        assert_eq!(&b[..e1], b"1.5");
        let e2 = scan_number(b, e1, b.len(), true).unwrap();
        assert_eq!(&b[e1..e2], b".5e3");
        let e3 = scan_number(b, e2, b.len(), true).unwrap();
        assert_eq!(&b[e2..e3], b"-2");
        assert!(scan_number(b".", 0, 1, true).is_none());
        assert!(scan_number(b"-", 0, 1, true).is_none());
    }
    #[test]
    fn bounds() {
        assert_eq!(parse_lexeme(b"1e19").unwrap_err(), LexErr::Bounds);
        assert_eq!(parse_lexeme(b"1e0000001").unwrap_err(), LexErr::Bounds);
        assert!(parse_lexeme(b"1e000001").is_ok());
    }
}
