//! Spelling models D, P, I, U, G (FORMAT.md §8–§9).
use crate::arith;
use crate::error::{err, Result};
use crate::numeric::{render, Descriptor};
use crate::rules::{all_rules, NUM_RULES};

pub const ESC: usize = NUM_RULES; // index of the escape weight
pub const RESCALE_AT: u32 = 16384;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Profile {
    D = 1,
    P = 2,
    I = 3,
    U = 4,
    G = 5,
}

impl Profile {
    pub fn from_u8(v: u8) -> Option<Profile> {
        match v {
            1 => Some(Profile::D),
            2 => Some(Profile::P),
            3 => Some(Profile::I),
            4 => Some(Profile::U),
            5 => Some(Profile::G),
            _ => None,
        }
    }
    pub fn from_name(s: &str) -> Option<Profile> {
        match s {
            "D" | "d" => Some(Profile::D),
            "P" | "p" => Some(Profile::P),
            "I" | "i" => Some(Profile::I),
            "U" | "u" => Some(Profile::U),
            "G" | "g" => Some(Profile::G),
            _ => None,
        }
    }
    pub fn name(&self) -> &'static str {
        match self {
            Profile::D => "D",
            Profile::P => "P",
            Profile::I => "I",
            Profile::U => "U",
            Profile::G => "G",
        }
    }
    pub const ALL: [Profile; 5] = [Profile::D, Profile::P, Profile::I, Profile::U, Profile::G];
}

#[derive(Clone, Debug)]
pub struct HoleCtx {
    pub role: usize,
    pub x: i128,
    pub k: u32,
}

/// One coded alphabet entry.
#[derive(Clone, Debug)]
pub struct Entry {
    pub members: Vec<usize>, // rule indices (0-based); empty for escape
    pub output: Option<Vec<u8>>,
    pub freq: u64,
}

/// Build the I/U/G alphabet from rule outputs (any rule subset, for tests) and weights.
pub fn alphabet(profile: Profile, outs: &[Option<Vec<u8>>], w: &[u32], w_esc: u32) -> Vec<Entry> {
    let mut a: Vec<Entry> = Vec::new();
    match profile {
        Profile::I => {
            for (f, o) in outs.iter().enumerate() {
                if let Some(o) = o {
                    a.push(Entry { members: vec![f], output: Some(o.clone()), freq: w[f] as u64 });
                }
            }
        }
        Profile::U | Profile::G => {
            for (f, o) in outs.iter().enumerate() {
                if let Some(o) = o {
                    if let Some(e) = a.iter_mut().find(|e| e.output.as_deref() == Some(o.as_slice())) {
                        e.members.push(f);
                        e.freq = if profile == Profile::U { e.freq.max(w[f] as u64) } else { e.freq + w[f] as u64 };
                    } else {
                        a.push(Entry { members: vec![f], output: Some(o.clone()), freq: w[f] as u64 });
                    }
                }
            }
        }
        _ => {}
    }
    a.push(Entry { members: Vec::new(), output: None, freq: w_esc as u64 });
    a
}

/// Index of the symbol coding `y` (I: best-weight matching rule; U/G: matching group; else escape).
pub fn choose(profile: Profile, a: &[Entry], w: &[u32], y: &[u8]) -> usize {
    let esc = a.len() - 1;
    match profile {
        Profile::I => {
            let mut best: Option<(usize, u32, usize)> = None; // (entry, weight, rule id)
            for (i, e) in a[..esc].iter().enumerate() {
                if e.output.as_deref() == Some(y) {
                    let f = e.members[0];
                    let better = match best {
                        None => true,
                        Some((_, bw, bf)) => w[f] > bw || (w[f] == bw && f < bf),
                    };
                    if better {
                        best = Some((i, w[f], f));
                    }
                }
            }
            best.map(|b| b.0).unwrap_or(esc)
        }
        _ => a[..esc].iter().position(|e| e.output.as_deref() == Some(y)).unwrap_or(esc),
    }
}

fn cum(a: &[Entry]) -> Vec<u64> {
    let mut c = Vec::with_capacity(a.len() + 1);
    c.push(0);
    for e in a {
        c.push(c.last().unwrap() + e.freq);
    }
    c
}

fn update(w: &mut [u32; NUM_RULES + 1], outs: &[Option<Vec<u8>>; NUM_RULES], y: &[u8]) -> usize {
    let mut nm = 0;
    for f in 0..NUM_RULES {
        if outs[f].as_deref() == Some(y) {
            w[f] += 1;
            nm += 1;
        }
    }
    if nm == 0 {
        w[ESC] += 1;
    }
    let total: u32 = w.iter().sum();
    if total >= RESCALE_AT {
        for v in w.iter_mut() {
            *v = (*v + 1) / 2;
        }
    }
    nm
}

fn update_flag(f: &mut [u32; 2], sym: usize) {
    f[sym] += 1;
    if f[0] + f[1] >= RESCALE_AT {
        f[0] = (f[0] + 1) / 2;
        f[1] = (f[1] + 1) / 2;
    }
}

#[derive(Clone, Debug, Default)]
pub struct RoleStats {
    pub tokens: u64,
    pub escapes: u64,
    pub multi_match: u64,         // tokens where >=2 applicable rules matched (collisions)
    pub applicable_sum: u64,      // sum over tokens of |A|
    pub distinct_outputs_sum: u64, // sum over tokens of the number of distinct rule outputs
    pub distinct_outputs_max: u64,
    pub ideal_bits_i: f64,
    pub ideal_bits_u: f64,
    pub ideal_bits_g: f64,
    pub rule_hits: [u64; NUM_RULES],
    pub p_matches: u64,
}

pub struct SpellOut {
    pub bytes: Vec<u8>,
    pub bits: u64,
    pub escapes: Vec<Descriptor>,
    pub stats: Vec<RoleStats>,
}

fn ln2(p: f64) -> f64 {
    -p.log2()
}

/// Encode the lexemes `ys` (with descriptors `ds`) of holes `ctx` under `profile`.
pub fn encode(profile: Profile, ctx: &[HoleCtx], ys: &[Vec<u8>], ds: &[Descriptor]) -> SpellOut {
    let mut stats = vec![RoleStats::default(); 8];
    let mut w = [[1u32; NUM_RULES + 1]; 8];
    let mut flag = [[1u32; 2]; 8];
    let mut prev: [Option<Descriptor>; 8] = Default::default();
    let mut enc = arith::Encoder::new();
    let mut escapes = Vec::new();
    for (i, h) in ctx.iter().enumerate() {
        let y = &ys[i];
        let r = h.role;
        let outs = all_rules(h.x, h.k);
        // diagnostics shared by all profiles
        {
            let st = &mut stats[r];
            st.tokens += 1;
            let napp = outs.iter().filter(|o| o.is_some()).count() as u64;
            st.applicable_sum += napp;
            let g = alphabet(Profile::G, &outs, &w[r][..NUM_RULES], w[r][ESC]);
            let u = alphabet(Profile::U, &outs, &w[r][..NUM_RULES], w[r][ESC]);
            let ia = alphabet(Profile::I, &outs, &w[r][..NUM_RULES], w[r][ESC]);
            let nd = (g.len() - 1) as u64;
            st.distinct_outputs_sum += nd;
            st.distinct_outputs_max = st.distinct_outputs_max.max(nd);
            for (al, prof, slot) in [(&ia, Profile::I, 0), (&u, Profile::U, 1), (&g, Profile::G, 2)] {
                let s = choose(prof, al, &w[r][..NUM_RULES], y);
                let tot: u64 = al.iter().map(|e| e.freq).sum();
                let bits = ln2(al[s].freq as f64 / tot as f64);
                match slot {
                    0 => st.ideal_bits_i += bits,
                    1 => st.ideal_bits_u += bits,
                    _ => st.ideal_bits_g += bits,
                }
            }
        }
        match profile {
            Profile::D => escapes.push(ds[i].clone()),
            Profile::P => {
                let cand = prev[r].as_ref().and_then(|d| render(d, h.x, h.k));
                match cand {
                    Some(out) => {
                        let sym = if &out == y { 0 } else { 1 };
                        let f = flag[r];
                        let (cl, ch) = if sym == 0 { (0, f[0] as u64) } else { (f[0] as u64, (f[0] + f[1]) as u64) };
                        enc.encode(cl, ch, (f[0] + f[1]) as u64);
                        update_flag(&mut flag[r], sym);
                        if sym == 1 {
                            escapes.push(ds[i].clone());
                        } else {
                            stats[r].p_matches += 1;
                        }
                    }
                    None => escapes.push(ds[i].clone()),
                }
            }
            Profile::I | Profile::U | Profile::G => {
                let a = alphabet(profile, &outs, &w[r][..NUM_RULES], w[r][ESC]);
                let s = choose(profile, &a, &w[r][..NUM_RULES], y);
                let c = cum(&a);
                enc.encode(c[s], c[s + 1], *c.last().unwrap());
                if s == a.len() - 1 {
                    escapes.push(ds[i].clone());
                }
            }
        }
        if profile == Profile::P {
            prev[r] = Some(ds[i].clone());
        }
        let nm = update(&mut w[r], &outs, y);
        if nm == 0 {
            stats[r].escapes += 1;
        }
        if nm >= 2 {
            stats[r].multi_match += 1;
        }
        for f in 0..NUM_RULES {
            if outs[f].as_deref() == Some(y.as_slice()) {
                stats[r].rule_hits[f] += 1;
            }
        }
    }
    let (bytes, bits) = match profile {
        Profile::D => (Vec::new(), 0),
        _ if ctx.is_empty() => (Vec::new(), 0),
        _ => enc.finish(),
    };
    SpellOut { bytes, bits, escapes, stats }
}

/// Decode lexemes for holes `ctx` under `profile`; `escapes` are the parsed escape descriptors.
pub fn decode(profile: Profile, ctx: &[HoleCtx], data: &[u8], bits: u64, escapes: &[Descriptor]) -> Result<Vec<Vec<u8>>> {
    let mut out = Vec::with_capacity(ctx.len());
    let mut ei = 0usize;
    let next_escape = |ei: &mut usize| -> Result<Descriptor> {
        if *ei >= escapes.len() {
            return err("spelling: escape stream exhausted");
        }
        *ei += 1;
        Ok(escapes[*ei - 1].clone())
    };
    if profile == Profile::D {
        if escapes.len() != ctx.len() {
            return err("spelling: D escape count mismatch");
        }
        for (i, h) in ctx.iter().enumerate() {
            match render(&escapes[i], h.x, h.k) {
                Some(y) => out.push(y),
                None => return err("spelling: inapplicable descriptor"),
            }
        }
        return Ok(out);
    }
    if ctx.is_empty() {
        if bits != 0 || !escapes.is_empty() {
            return err("spelling: data without holes");
        }
        return Ok(out);
    }
    let mut dec = arith::Decoder::new(data, bits);
    let mut w = [[1u32; NUM_RULES + 1]; 8];
    let mut flag = [[1u32; 2]; 8];
    let mut prev: [Option<Descriptor>; 8] = Default::default();
    for h in ctx {
        let r = h.role;
        let outs = all_rules(h.x, h.k);
        let y: Vec<u8>;
        let mut desc_used: Option<Descriptor> = None;
        match profile {
            Profile::P => {
                let cand = prev[r].as_ref().and_then(|d| render(d, h.x, h.k));
                match cand {
                    Some(c) => {
                        let f = flag[r];
                        let sym = dec.decode(&[0, f[0] as u64, (f[0] + f[1]) as u64])?;
                        update_flag(&mut flag[r], sym);
                        if sym == 0 {
                            y = c;
                            desc_used = prev[r].clone();
                        } else {
                            let d = next_escape(&mut ei)?;
                            let yy = render(&d, h.x, h.k).ok_or_else(|| crate::error::Error("spelling: inapplicable escape".into()))?;
                            if yy == c {
                                return err("spelling: non-canonical P escape");
                            }
                            y = yy;
                            desc_used = Some(d);
                        }
                    }
                    None => {
                        let d = next_escape(&mut ei)?;
                        y = render(&d, h.x, h.k).ok_or_else(|| crate::error::Error("spelling: inapplicable escape".into()))?;
                        desc_used = Some(d);
                    }
                }
            }
            _ => {
                let a = alphabet(profile, &outs, &w[r][..NUM_RULES], w[r][ESC]);
                let c = cum(&a);
                let s = dec.decode(&c)?;
                if s == a.len() - 1 {
                    let d = next_escape(&mut ei)?;
                    let yy = render(&d, h.x, h.k).ok_or_else(|| crate::error::Error("spelling: inapplicable escape".into()))?;
                    if outs.iter().any(|o| o.as_deref() == Some(yy.as_slice())) {
                        return err("spelling: non-canonical escape (a rule matches)");
                    }
                    y = yy;
                } else {
                    let yy = a[s].output.clone().unwrap();
                    if profile == Profile::I {
                        // canonical: the coded rule must be the highest-weight matching rule
                        let best = choose(Profile::I, &a, &w[r][..NUM_RULES], &yy);
                        if best != s {
                            return err("spelling: non-canonical rule choice");
                        }
                    }
                    y = yy;
                }
            }
        }
        if profile == Profile::P {
            // prev = descriptor of the actual lexeme (rendering preserves every descriptor field)
            prev[r] = desc_used;
        }
        update(&mut w[r], &outs, &y);
        out.push(y);
    }
    dec.finish()?;
    if ei != escapes.len() {
        return err("spelling: unused escape descriptors");
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    /// Reduced fixture of the master specification: rules fixed-one-place, shortest-with-L,
    /// fixed-two-places and escape, all weight one, at v = 1/2.
    #[test]
    fn reduced_fixture() {
        let outs = vec![Some(b"0.5".to_vec()), Some(b"0.5".to_vec()), Some(b"0.50".to_vec())];
        let w = [1u32, 1, 1];
        let prob = |p: Profile, y: &[u8]| {
            let a = alphabet(p, &outs, &w, 1);
            let s = choose(p, &a, &w, y);
            let tot: u64 = a.iter().map(|e| e.freq).sum();
            (a[s].freq, tot)
        };
        assert_eq!(prob(Profile::I, b"0.5"), (1, 4));
        assert_eq!(prob(Profile::U, b"0.5"), (1, 3));
        assert_eq!(prob(Profile::G, b"0.5"), (2, 4));
        assert_eq!(prob(Profile::U, b"0.50"), (1, 3));
        assert_eq!(prob(Profile::G, b"0.50"), (1, 4));
    }
    #[test]
    fn rescale_jump() {
        let mut w = [0u32; NUM_RULES + 1];
        w[ESC] = 16382 - 0;
        // three matching rules: 16382 + 3 = 16385 >= 16384 -> rescale
        let outs: [Option<Vec<u8>>; NUM_RULES] = std::array::from_fn(|i| if i < 3 { Some(b"1".to_vec()) } else { None });
        update(&mut w, &outs, b"1");
        assert_eq!(w[ESC], (16382 + 1) / 2);
        assert_eq!(w[0], 1);
    }
}
