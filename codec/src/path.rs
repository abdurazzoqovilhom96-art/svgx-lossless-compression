//! SVG 1.1 path grammar (FORMAT.md §5) over a byte span with optional explicit holes.
//! The same parser serves the encoder (no holes) and the decoders (masked span with holes).

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Tok {
    /// Literal number lexeme `[start, end)` within the parsed span.
    Lit { start: usize, end: usize },
    /// Hole with its ordinal among the path's holes.
    Hole(usize),
}

#[derive(Clone, Debug)]
pub struct Group {
    /// Uppercase command letter; implicit lineto after moveto is reported as `L`.
    pub cmd: u8,
    pub rel: bool,
    pub args: Vec<Tok>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PathErr;

pub type V2 = [i128; 2];

#[inline]
pub fn is_wsp(b: u8) -> bool {
    b == 0x20 || b == 0x09 || b == 0x0A || b == 0x0D
}

#[derive(PartialEq, Eq)]
enum Sep {
    None,
    Wsp,
    Comma,
}

struct Parser<'a> {
    b: &'a [u8],
    holes: &'a [usize],
    hi: usize,
    pos: usize,
    groups: Vec<Group>,
}

impl<'a> Parser<'a> {
    fn at_hole(&self) -> bool {
        self.hi < self.holes.len() && self.holes[self.hi] == self.pos
    }
    fn limit(&self) -> usize {
        if self.hi < self.holes.len() {
            self.holes[self.hi]
        } else {
            self.b.len()
        }
    }
    fn skip_wsp(&mut self) {
        while !self.at_hole() && self.pos < self.b.len() && is_wsp(self.b[self.pos]) {
            self.pos += 1;
        }
    }
    fn comma_wsp(&mut self) -> Sep {
        if self.at_hole() || self.pos >= self.b.len() {
            return Sep::None;
        }
        let c = self.b[self.pos];
        if is_wsp(c) {
            self.skip_wsp();
            if !self.at_hole() && self.pos < self.b.len() && self.b[self.pos] == b',' {
                self.pos += 1;
                self.skip_wsp();
                return Sep::Comma;
            }
            Sep::Wsp
        } else if c == b',' {
            self.pos += 1;
            self.skip_wsp();
            Sep::Comma
        } else {
            Sep::None
        }
    }
    fn number_start(&self) -> bool {
        if self.at_hole() {
            return true;
        }
        if self.pos >= self.b.len() {
            return false;
        }
        let c = self.b[self.pos];
        c.is_ascii_digit() || c == b'.' || c == b'+' || c == b'-'
    }
    fn number(&mut self, allow_sign: bool) -> Result<Tok, PathErr> {
        if self.at_hole() {
            let t = Tok::Hole(self.hi);
            self.hi += 1;
            return Ok(t);
        }
        let lim = self.limit();
        match crate::numeric::scan_number(self.b, self.pos, lim, allow_sign) {
            Some(end) => {
                let t = Tok::Lit { start: self.pos, end };
                self.pos = end;
                Ok(t)
            }
            None => Err(PathErr),
        }
    }
    fn flag(&mut self) -> Result<Tok, PathErr> {
        if self.at_hole() || self.pos >= self.b.len() {
            return Err(PathErr);
        }
        let c = self.b[self.pos];
        if c == b'0' || c == b'1' {
            let t = Tok::Lit { start: self.pos, end: self.pos + 1 };
            self.pos += 1;
            Ok(t)
        } else {
            Err(PathErr)
        }
    }
    fn pair(&mut self, out: &mut Vec<Tok>) -> Result<(), PathErr> {
        out.push(self.number(true)?);
        self.comma_wsp();
        out.push(self.number(true)?);
        Ok(())
    }
    /// After one argument: decide whether another argument follows (comma-wsp? arg).
    fn more_args(&mut self) -> Result<bool, PathErr> {
        let save = (self.pos, self.hi);
        let sep = self.comma_wsp();
        if self.number_start() {
            return Ok(true);
        }
        if sep == Sep::Comma {
            return Err(PathErr);
        }
        self.pos = save.0;
        self.hi = save.1;
        Ok(false)
    }
    fn args(&mut self, cmd: u8, out: &mut Vec<Tok>) -> Result<(), PathErr> {
        match cmd {
            b'M' | b'L' | b'T' => self.pair(out),
            b'H' | b'V' => {
                out.push(self.number(true)?);
                Ok(())
            }
            b'C' => {
                self.pair(out)?;
                self.comma_wsp();
                self.pair(out)?;
                self.comma_wsp();
                self.pair(out)
            }
            b'S' | b'Q' => {
                self.pair(out)?;
                self.comma_wsp();
                self.pair(out)
            }
            b'A' => {
                out.push(self.number(false)?);
                self.comma_wsp();
                out.push(self.number(false)?);
                self.comma_wsp();
                out.push(self.number(true)?);
                if self.comma_wsp() == Sep::None {
                    return Err(PathErr);
                }
                out.push(self.flag()?);
                self.comma_wsp();
                out.push(self.flag()?);
                self.comma_wsp();
                self.pair(out)
            }
            _ => Err(PathErr),
        }
    }
    fn command(&mut self) -> Result<(), PathErr> {
        let c = self.b[self.pos];
        let up = c.to_ascii_uppercase();
        let rel = c.is_ascii_lowercase();
        if !matches!(up, b'M' | b'Z' | b'L' | b'H' | b'V' | b'C' | b'S' | b'Q' | b'T' | b'A') {
            return Err(PathErr);
        }
        self.pos += 1;
        if up == b'Z' {
            self.groups.push(Group { cmd: b'Z', rel, args: Vec::new() });
            return Ok(());
        }
        self.skip_wsp();
        let mut first = true;
        loop {
            let mut a = Vec::with_capacity(7);
            self.args(up, &mut a)?;
            let gcmd = if up == b'M' && !first { b'L' } else { up };
            self.groups.push(Group { cmd: gcmd, rel, args: a });
            first = false;
            if !self.more_args()? {
                break;
            }
        }
        Ok(())
    }
    fn run(&mut self) -> Result<(), PathErr> {
        self.skip_wsp();
        let mut started = false;
        loop {
            self.skip_wsp();
            if self.pos >= self.b.len() && !self.at_hole() {
                break;
            }
            if self.at_hole() {
                return Err(PathErr);
            }
            let c = self.b[self.pos];
            if !started && c != b'M' && c != b'm' {
                return Err(PathErr);
            }
            started = true;
            self.command()?;
        }
        if self.hi != self.holes.len() {
            return Err(PathErr);
        }
        Ok(())
    }
}

/// Parse a path span; `holes` are sorted insertion positions (may repeat).
pub fn parse(bytes: &[u8], holes: &[usize]) -> Result<Vec<Group>, PathErr> {
    let mut p = Parser { b: bytes, holes, hi: 0, pos: 0, groups: Vec::new() };
    p.run()?;
    Ok(p.groups)
}

/// Blocks: four consecutive cubic groups from the start of each maximal run.
pub fn blocks(groups: &[Group]) -> Vec<[usize; 4]> {
    let mut out = Vec::new();
    let mut i = 0;
    while i < groups.len() {
        if groups[i].cmd == b'C' {
            let start = i;
            while i < groups.len() && groups[i].cmd == b'C' {
                i += 1;
            }
            let n = i - start;
            for b in 0..n / 4 {
                let g = start + 4 * b;
                out.push([g, g + 1, g + 2, g + 3]);
            }
        } else {
            i += 1;
        }
    }
    out
}

/// Endpoint argument indices (current-point update) of a group.
pub fn endpoint_args(cmd: u8) -> &'static [usize] {
    match cmd {
        b'M' | b'L' | b'T' => &[0, 1],
        b'H' | b'V' => &[0],
        b'C' => &[4, 5],
        b'S' | b'Q' => &[2, 3],
        b'A' => &[5, 6],
        _ => &[],
    }
}

const LIMIT: u128 = 1u128 << 96;

fn in_bounds(p: V2) -> bool {
    p[0].unsigned_abs() < LIMIT && p[1].unsigned_abs() < LIMIT
}

/// Walk current points. `val(g, a)` returns the grid value of endpoint argument `a` of group `g`.
/// Returns (start point, end point) per group; errors when an absolute coordinate is out of bounds.
pub fn walk<F>(groups: &[Group], mut val: F) -> Result<Vec<(V2, V2)>, PathErr>
where
    F: FnMut(usize, usize) -> Result<i128, PathErr>,
{
    let mut cur: V2 = [0, 0];
    let mut sub: V2 = [0, 0];
    let mut out = Vec::with_capacity(groups.len());
    for (gi, g) in groups.iter().enumerate() {
        let start = cur;
        let base = if g.rel { cur } else { [0, 0] };
        match g.cmd {
            b'Z' => {
                cur = sub;
            }
            b'H' => {
                let x = val(gi, 0)?;
                cur = [if g.rel { cur[0] + x } else { x }, cur[1]];
            }
            b'V' => {
                let y = val(gi, 0)?;
                cur = [cur[0], if g.rel { cur[1] + y } else { y }];
            }
            _ => {
                let ea = endpoint_args(g.cmd);
                let x = val(gi, ea[0])?;
                let y = val(gi, ea[1])?;
                cur = [base[0] + x, base[1] + y];
            }
        }
        if !in_bounds(cur) {
            return Err(PathErr);
        }
        if g.cmd == b'M' {
            sub = cur;
        }
        out.push((start, cur));
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn grammar() {
        assert!(parse(b"M0 0C1 2 3 4 5 6 7 8 9 10 11 12z", &[]).is_ok());
        assert!(parse(b"M1.5.5L.5-.5", &[]).is_ok());
        assert!(parse(b"m0,0 1,1 2,2", &[]).map(|g| g.len() == 3 && g[1].cmd == b'L').unwrap());
        assert!(parse(b"M0 0a1 1 0 01 5 5", &[]).is_ok());
        assert!(parse(b"M0 0a1 1 001 5 5", &[]).is_err());
        assert!(parse(b"M0,0,", &[]).is_err());
        assert!(parse(b"L0 0", &[]).is_err());
        assert!(parse(b"  ", &[]).map(|g| g.is_empty()).unwrap());
        assert!(parse(b"M0 0 X", &[]).is_err());
    }
    #[test]
    fn masked() {
        // "M0 0C1 2 3 4 5 6" with the four controls removed: "M0 0C   5 6"
        let m = b"M0 0C    5 6";
        let holes = [5, 6, 7, 8];
        let g = parse(m, &holes).unwrap();
        assert_eq!(g[1].args[0], Tok::Hole(0));
        assert_eq!(g[1].args[3], Tok::Hole(3));
        // adjacent holes with zero gaps
        let m2 = b"M0 0C 5 6";
        assert!(parse(m2, &[5, 5, 5, 5]).is_ok());
    }
    #[test]
    fn runs() {
        let g = parse(b"M0 0c1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 L0 0C1 1 1 1 1 1", &[]).unwrap();
        assert_eq!(blocks(&g).len(), 1);
    }
}
