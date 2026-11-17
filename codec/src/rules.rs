//! The eight frozen fixed-point spelling rules (FORMAT.md §8).
use crate::numeric::pow10;

pub const NUM_RULES: usize = 8;

/// fixed(d, short): exact rendering of v = X/10^K with exactly d fractional digits.
pub fn fixed(x: i128, k: u32, d: u32, short: bool) -> Option<Vec<u8>> {
    let ax = x.unsigned_abs();
    let n: u128 = if d >= k {
        ax.checked_mul(pow10(d - k)?)?
    } else {
        let p = pow10(k - d)?;
        if ax % p != 0 {
            return None;
        }
        ax / p
    };
    let mut s = n.to_string().into_bytes();
    while s.len() < d as usize + 1 {
        s.insert(0, b'0');
    }
    let split = s.len() - d as usize;
    let mut out = Vec::with_capacity(s.len() + 2);
    if x < 0 {
        out.push(b'-');
    }
    let int_part = &s[..split];
    let drop_zero = short && int_part == b"0" && n != 0;
    if !drop_zero {
        out.extend_from_slice(int_part);
    }
    if d > 0 {
        out.push(b'.');
        out.extend_from_slice(&s[split..]);
    }
    Some(out)
}

/// Smallest d >= 0 such that fixed(d) applies.
pub fn shortest_places(x: i128, k: u32) -> u32 {
    let mut ax = x.unsigned_abs();
    if ax == 0 {
        return 0;
    }
    let mut d = k;
    while d > 0 && ax % 10 == 0 {
        ax /= 10;
        d -= 1;
    }
    d
}

/// Output of rule `id` (1..=8), or None when inapplicable.
pub fn rule(id: usize, x: i128, k: u32) -> Option<Vec<u8>> {
    match id {
        1 => fixed(x, k, 0, false),
        2 => fixed(x, k, 1, false),
        3 => fixed(x, k, 2, false),
        4 => fixed(x, k, 3, false),
        5 => fixed(x, k, 4, false),
        6 => fixed(x, k, shortest_places(x, k), false),
        7 => fixed(x, k, shortest_places(x, k), true),
        8 => fixed(x, k, 2, true),
        _ => None,
    }
}

/// Outputs of all rules: index 0..8 for rule IDs 1..8.
pub fn all_rules(x: i128, k: u32) -> [Option<Vec<u8>>; NUM_RULES] {
    std::array::from_fn(|i| rule(i + 1, x, k))
}

#[cfg(test)]
mod tests {
    use super::*;
    fn s(id: usize, x: i128, k: u32) -> Option<String> {
        rule(id, x, k).map(|b| String::from_utf8(b).unwrap())
    }
    #[test]
    fn examples() {
        assert_eq!(s(6, 10, 0).as_deref(), Some("10"));
        assert_eq!(s(6, 100, 1).as_deref(), Some("10"));
        assert_eq!(s(6, 0, 3).as_deref(), Some("0"));
        assert_eq!(s(7, -5, 1).as_deref(), Some("-.5"));
        assert_eq!(s(6, -5, 1).as_deref(), Some("-0.5"));
        assert_eq!(s(8, 5, 1).as_deref(), Some(".50"));
        assert_eq!(s(8, 0, 1).as_deref(), Some("0.00"));
        assert_eq!(s(3, 5, 1).as_deref(), Some("0.50"));
        assert_eq!(s(1, 5, 1), None);
        assert_eq!(s(2, 125, 2), None);
        assert_eq!(s(1, -0, 0).as_deref(), Some("0"));
        assert_eq!(s(5, 12345, 2).as_deref(), Some("123.4500"));
        assert_eq!(s(7, 12345, 2).as_deref(), Some("123.45"));
        assert_eq!(s(2, 120, 2).as_deref(), Some("1.2"));
    }
}
