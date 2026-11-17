//! FFI to Google's pinned Brotli C library (statically linked by build.rs).
//! Compression replicates the call sequence of the `brotli` CLI with `-q 11 -w 22` so that the raw
//! fallback is byte-identical to the independent baseline stream (decision D-02).
use crate::error::{err, Result};
use std::os::raw::{c_int, c_void};

const PARAM_QUALITY: c_int = 1;
const PARAM_LGWIN: c_int = 2;
const PARAM_SIZE_HINT: c_int = 5;
const OP_FINISH: c_int = 2;
const DEC_ERROR: c_int = 0;
const DEC_SUCCESS: c_int = 1;
const DEC_NEEDS_MORE_INPUT: c_int = 2;
const DEC_NEEDS_MORE_OUTPUT: c_int = 3;

pub const QUALITY: u32 = 11;
pub const LGWIN: u32 = 22;

extern "C" {
    fn BrotliEncoderCreateInstance(a: *const c_void, f: *const c_void, o: *mut c_void) -> *mut c_void;
    fn BrotliEncoderSetParameter(s: *mut c_void, p: c_int, v: u32) -> c_int;
    fn BrotliEncoderCompressStream(
        s: *mut c_void,
        op: c_int,
        available_in: *mut usize,
        next_in: *mut *const u8,
        available_out: *mut usize,
        next_out: *mut *mut u8,
        total_out: *mut usize,
    ) -> c_int;
    fn BrotliEncoderIsFinished(s: *mut c_void) -> c_int;
    fn BrotliEncoderDestroyInstance(s: *mut c_void);
    fn BrotliEncoderVersion() -> u32;
    fn BrotliDecoderCreateInstance(a: *const c_void, f: *const c_void, o: *mut c_void) -> *mut c_void;
    fn BrotliDecoderDecompressStream(
        s: *mut c_void,
        available_in: *mut usize,
        next_in: *mut *const u8,
        available_out: *mut usize,
        next_out: *mut *mut u8,
        total_out: *mut usize,
    ) -> c_int;
    fn BrotliDecoderDestroyInstance(s: *mut c_void);
}

pub fn version() -> String {
    let v = unsafe { BrotliEncoderVersion() };
    format!("{}.{}.{}", v >> 24, (v >> 12) & 0xFFF, v & 0xFFF)
}

/// Brotli quality 11, lgwin 22, generic mode, size hint as in the CLI.
pub fn compress(input: &[u8]) -> Vec<u8> {
    unsafe {
        let s = BrotliEncoderCreateInstance(std::ptr::null(), std::ptr::null(), std::ptr::null_mut());
        assert!(!s.is_null(), "brotli: out of memory");
        BrotliEncoderSetParameter(s, PARAM_QUALITY, QUALITY);
        BrotliEncoderSetParameter(s, PARAM_LGWIN, LGWIN);
        if !input.is_empty() {
            let hint = if input.len() < (1 << 30) { input.len() as u32 } else { 1u32 << 30 };
            BrotliEncoderSetParameter(s, PARAM_SIZE_HINT, hint);
        }
        let mut out: Vec<u8> = Vec::with_capacity(input.len() / 2 + 1024);
        let mut chunk = vec![0u8; 1 << 16];
        let mut avail_in = input.len();
        let mut next_in = input.as_ptr();
        loop {
            let mut avail_out = chunk.len();
            let mut next_out = chunk.as_mut_ptr();
            let ok = BrotliEncoderCompressStream(
                s,
                OP_FINISH,
                &mut avail_in,
                &mut next_in,
                &mut avail_out,
                &mut next_out,
                std::ptr::null_mut(),
            );
            assert!(ok != 0, "brotli: compression failed");
            let produced = chunk.len() - avail_out;
            out.extend_from_slice(&chunk[..produced]);
            if BrotliEncoderIsFinished(s) != 0 {
                break;
            }
        }
        BrotliEncoderDestroyInstance(s);
        out
    }
}

/// Strict standard decode: large window disabled (decoder default), full consumption,
/// no trailing bytes, output limited to `max_out` bytes.
pub fn decompress_strict(input: &[u8], max_out: usize) -> Result<Vec<u8>> {
    if input.is_empty() {
        return err("brotli: empty stream");
    }
    unsafe {
        let s = BrotliDecoderCreateInstance(std::ptr::null(), std::ptr::null(), std::ptr::null_mut());
        if s.is_null() {
            return err("brotli: out of memory");
        }
        let mut out: Vec<u8> = Vec::new();
        let mut chunk = vec![0u8; 1 << 16];
        let mut avail_in = input.len();
        let mut next_in = input.as_ptr();
        let result;
        loop {
            let mut avail_out = chunk.len();
            let mut next_out = chunk.as_mut_ptr();
            let r = BrotliDecoderDecompressStream(
                s,
                &mut avail_in,
                &mut next_in,
                &mut avail_out,
                &mut next_out,
                std::ptr::null_mut(),
            );
            let produced = chunk.len() - avail_out;
            out.extend_from_slice(&chunk[..produced]);
            if out.len() > max_out {
                result = Err("brotli: output exceeds limit");
                break;
            }
            match r {
                DEC_SUCCESS => {
                    result = if avail_in == 0 { Ok(()) } else { Err("brotli: trailing bytes after stream") };
                    break;
                }
                DEC_NEEDS_MORE_OUTPUT => continue,
                DEC_NEEDS_MORE_INPUT => {
                    result = Err("brotli: truncated stream");
                    break;
                }
                DEC_ERROR => {
                    result = Err("brotli: corrupt stream");
                    break;
                }
                _ => {
                    result = Err("brotli: unexpected decoder state");
                    break;
                }
            }
        }
        BrotliDecoderDestroyInstance(s);
        match result {
            Ok(()) => Ok(out),
            Err(m) => err(m),
        }
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn roundtrip() {
        for data in [&b""[..], b"a", b"<svg xmlns='http://www.w3.org/2000/svg'/>"] {
            let c = super::compress(data);
            assert!(!c.is_empty());
            assert_ne!(c[0], 0x11);
            assert_eq!(super::decompress_strict(&c, 1 << 20).unwrap(), data);
            let mut t = c.clone();
            t.push(0);
            assert!(super::decompress_strict(&t, 1 << 20).is_err());
            if c.len() > 1 {
                assert!(super::decompress_strict(&c[..c.len() - 1], 1 << 20).is_err());
            }
        }
    }
}
