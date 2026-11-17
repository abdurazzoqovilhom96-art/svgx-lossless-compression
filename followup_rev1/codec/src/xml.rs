//! Byte-span XML scanner (encoder only, FORMAT.md §13). Finds the unprefixed `d` attribute
//! values of `{http://www.w3.org/2000/svg}path` elements. Never resolves external entities.

pub const SVG_NS: &[u8] = b"http://www.w3.org/2000/svg";

#[derive(Debug, Default)]
pub struct Scan {
    /// File-level reason why nothing is modeled (None = scan succeeded).
    pub reason: Option<&'static str>,
    /// Value spans (end-exclusive) of candidate path `d` attributes, in document order.
    pub paths: Vec<(usize, usize)>,
}

fn is_ws(b: u8) -> bool {
    b == 0x20 || b == 0x09 || b == 0x0A || b == 0x0D
}

fn find(h: &[u8], from: usize, needle: &[u8]) -> Option<usize> {
    if from > h.len() || needle.is_empty() {
        return None;
    }
    h[from..].windows(needle.len()).position(|w| w == needle).map(|p| p + from)
}

fn starts(h: &[u8], at: usize, s: &[u8]) -> bool {
    h.len() >= at + s.len() && &h[at..at + s.len()] == s
}

const ALLOWED_ENC: [&str; 8] = ["utf-8", "utf8", "us-ascii", "ascii", "iso-8859-1", "latin1", "iso-8859-15", "windows-1252"];

fn fail(reason: &'static str) -> Scan {
    Scan { reason: Some(reason), paths: Vec::new() }
}

pub fn scan(b: &[u8]) -> Scan {
    let n = b.len();
    let mut pos = 0;
    if starts(b, 0, &[0xEF, 0xBB, 0xBF]) {
        pos = 3;
    } else if starts(b, 0, &[0xFE, 0xFF]) || starts(b, 0, &[0xFF, 0xFE]) || (n >= 2 && (b[0] == 0 || b[1] == 0)) {
        return fail("unsupported_encoding");
    }
    let mut utf8 = true;
    if starts(b, pos, b"<?xml") && n > pos + 5 && is_ws(b[pos + 5]) {
        let end = match find(b, pos, b"?>") {
            Some(e) => e,
            None => return fail("malformed_xml"),
        };
        let decl = &b[pos..end];
        if let Some(ei) = find(decl, 0, b"encoding") {
            let mut j = ei + 8;
            while j < decl.len() && is_ws(decl[j]) {
                j += 1;
            }
            if j >= decl.len() || decl[j] != b'=' {
                return fail("malformed_xml");
            }
            j += 1;
            while j < decl.len() && is_ws(decl[j]) {
                j += 1;
            }
            if j >= decl.len() || (decl[j] != b'"' && decl[j] != b'\'') {
                return fail("malformed_xml");
            }
            let q = decl[j];
            let vs = j + 1;
            let ve = match decl[vs..].iter().position(|&c| c == q) {
                Some(p) => vs + p,
                None => return fail("malformed_xml"),
            };
            let enc = String::from_utf8_lossy(&decl[vs..ve]).to_ascii_lowercase();
            if !ALLOWED_ENC.contains(&enc.as_str()) {
                return fail("unsupported_encoding");
            }
            utf8 = enc == "utf-8" || enc == "utf8";
        }
    }
    if utf8 && std::str::from_utf8(&b[pos..]).is_err() {
        return fail("invalid_utf8");
    }

    // element stack: (name span, number of namespace bindings pushed)
    let mut stack: Vec<(usize, usize, usize)> = Vec::new();
    let mut ns: Vec<(Vec<u8>, Vec<u8>)> = Vec::new(); // (prefix, uri); prefix "" = default
    let mut paths = Vec::new();
    let mut roots = 0usize;
    let mut i = pos;
    while i < n {
        let lt = match b[i..].iter().position(|&c| c == b'<') {
            Some(p) => i + p,
            None => break,
        };
        if starts(b, lt, b"<!--") {
            match find(b, lt + 4, b"-->") {
                Some(e) => i = e + 3,
                None => return fail("malformed_xml"),
            }
        } else if starts(b, lt, b"<![CDATA[") {
            if stack.is_empty() {
                return fail("malformed_xml");
            }
            match find(b, lt + 9, b"]]>") {
                Some(e) => i = e + 3,
                None => return fail("malformed_xml"),
            }
        } else if starts(b, lt, b"<?") {
            match find(b, lt + 2, b"?>") {
                Some(e) => i = e + 2,
                None => return fail("malformed_xml"),
            }
        } else if starts(b, lt, b"<!DOCTYPE") {
            let mut j = lt + 9;
            let mut depth = 0i32;
            let mut sub_start = None;
            let mut end = None;
            while j < n {
                let c = b[j];
                if c == b'"' || c == b'\'' {
                    match b[j + 1..].iter().position(|&x| x == c) {
                        Some(p) => j = j + 1 + p + 1,
                        None => return fail("malformed_xml"),
                    }
                    continue;
                }
                if c == b'[' {
                    if depth == 0 {
                        sub_start = Some(j);
                    }
                    depth += 1;
                } else if c == b']' {
                    depth -= 1;
                } else if c == b'>' && depth == 0 {
                    end = Some(j);
                    break;
                }
                j += 1;
            }
            let e = match end {
                Some(e) => e,
                None => return fail("malformed_xml"),
            };
            if let Some(s) = sub_start {
                let subset = &b[s..e];
                if find(subset, 0, b"<!ENTITY").is_some() || find(subset, 0, b"<!ATTLIST").is_some() {
                    return fail("ambiguous_dtd");
                }
            }
            i = e + 1;
        } else if starts(b, lt, b"</") {
            let ns_ = lt + 2;
            let mut j = ns_;
            while j < n && !is_ws(b[j]) && b[j] != b'>' {
                j += 1;
            }
            let name = (ns_, j);
            while j < n && is_ws(b[j]) {
                j += 1;
            }
            if j >= n || b[j] != b'>' {
                return fail("malformed_xml");
            }
            match stack.pop() {
                Some((s, e, nb)) => {
                    if b[s..e] != b[name.0..name.1] {
                        return fail("malformed_xml");
                    }
                    for _ in 0..nb {
                        ns.pop();
                    }
                }
                None => return fail("malformed_xml"),
            }
            i = j + 1;
        } else if starts(b, lt, b"<!") {
            return fail("malformed_xml");
        } else {
            // start tag
            let ns_ = lt + 1;
            let mut j = ns_;
            while j < n && !is_ws(b[j]) && b[j] != b'/' && b[j] != b'>' {
                if b[j] == b'<' || b[j] == b'=' || b[j] == b'"' || b[j] == b'\'' {
                    return fail("malformed_xml");
                }
                j += 1;
            }
            if j == ns_ {
                return fail("malformed_xml");
            }
            let name = (ns_, j);
            let mut attrs: Vec<((usize, usize), (usize, usize))> = Vec::new();
            let empty;
            loop {
                let had_ws = j < n && is_ws(b[j]);
                while j < n && is_ws(b[j]) {
                    j += 1;
                }
                if j >= n {
                    return fail("malformed_xml");
                }
                if b[j] == b'>' {
                    empty = false;
                    j += 1;
                    break;
                }
                if starts(b, j, b"/>") {
                    empty = true;
                    j += 2;
                    break;
                }
                if !had_ws {
                    return fail("malformed_xml");
                }
                let as_ = j;
                while j < n && !is_ws(b[j]) && b[j] != b'=' && b[j] != b'>' && b[j] != b'/' {
                    if b[j] == b'<' || b[j] == b'"' || b[j] == b'\'' {
                        return fail("malformed_xml");
                    }
                    j += 1;
                }
                let an = (as_, j);
                if an.0 == an.1 {
                    return fail("malformed_xml");
                }
                while j < n && is_ws(b[j]) {
                    j += 1;
                }
                if j >= n || b[j] != b'=' {
                    return fail("malformed_xml");
                }
                j += 1;
                while j < n && is_ws(b[j]) {
                    j += 1;
                }
                if j >= n || (b[j] != b'"' && b[j] != b'\'') {
                    return fail("malformed_xml");
                }
                let q = b[j];
                let vs = j + 1;
                let ve = match b[vs..].iter().position(|&c| c == q) {
                    Some(p) => vs + p,
                    None => return fail("malformed_xml"),
                };
                if b[vs..ve].contains(&b'<') {
                    return fail("malformed_xml");
                }
                if attrs.iter().any(|(a, _)| b[a.0..a.1] == b[an.0..an.1]) {
                    return fail("malformed_xml");
                }
                attrs.push((an, (vs, ve)));
                j = ve + 1;
            }
            // namespace declarations
            let mut pushed = 0;
            for (an, av) in &attrs {
                let aname = &b[an.0..an.1];
                let prefix: Option<&[u8]> = if aname == b"xmlns" {
                    Some(b"")
                } else if aname.starts_with(b"xmlns:") {
                    Some(&aname[6..])
                } else {
                    None
                };
                if let Some(p) = prefix {
                    let val = &b[av.0..av.1];
                    if val.contains(&b'&') {
                        return fail("ambiguous_namespace");
                    }
                    ns.push((p.to_vec(), val.to_vec()));
                    pushed += 1;
                }
            }
            let ename = &b[name.0..name.1];
            let (prefix, local): (&[u8], &[u8]) = match ename.iter().position(|&c| c == b':') {
                Some(p) => (&ename[..p], &ename[p + 1..]),
                None => (b"", ename),
            };
            let uri: Option<&[u8]> = ns.iter().rev().find(|(p, _)| p.as_slice() == prefix).map(|(_, u)| u.as_slice());
            if !prefix.is_empty() && uri.is_none() && prefix != b"xml" {
                return fail("malformed_xml");
            }
            if local == b"path" && uri == Some(SVG_NS) {
                if let Some((_, av)) = attrs.iter().find(|(a, _)| &b[a.0..a.1] == b"d") {
                    paths.push(*av);
                }
            }
            if stack.is_empty() {
                roots += 1;
            }
            if empty {
                for _ in 0..pushed {
                    ns.pop();
                }
            } else {
                stack.push((name.0, name.1, pushed));
            }
            i = j;
        }
    }
    if !stack.is_empty() || roots != 1 {
        return fail("malformed_xml");
    }
    Scan { reason: None, paths }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn finds_paths() {
        let s = br#"<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/><g><path id="a" d='M1 1'></path></g></svg>"#;
        let r = scan(s);
        assert!(r.reason.is_none());
        assert_eq!(r.paths.len(), 2);
        assert_eq!(&s[r.paths[1].0..r.paths[1].1], b"M1 1");
    }
    #[test]
    fn namespaces() {
        let s = br#"<s:svg xmlns:s="http://www.w3.org/2000/svg"><s:path d="M0 0"/><path d="M1 1"/></s:svg>"#;
        assert_eq!(scan(s).paths.len(), 1);
        let s2 = br#"<svg><path d="M0 0"/></svg>"#;
        assert_eq!(scan(s2).paths.len(), 0);
        let s3 = br#"<!DOCTYPE svg [<!ENTITY a "b">]><svg xmlns="http://www.w3.org/2000/svg"/>"#;
        assert_eq!(scan(s3).reason, Some("ambiguous_dtd"));
        let s4 = br#"<svg xmlns="http://www.w3.org/2000/svg"><path d="1" d="2"/></svg>"#;
        assert_eq!(scan(s4).reason, Some("malformed_xml"));
    }
}
