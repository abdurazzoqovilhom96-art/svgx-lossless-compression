//! svgx — byte-exact SVG codec (SVGX v1). See docs/FORMAT.md.
mod arith;
mod bits;
mod brotli;
mod container;
mod crc32;
mod decode;
mod encode;
mod error;
mod geometry;
mod numeric;
mod path;
mod rules;
mod spelling;
mod stats;
mod xml;

use encode::{Analysis, Common, ProfileOut};
use spelling::Profile;
use stats::J;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

const HELP: &str = "svgx 1.0.0 — byte-exact SVG kodek (SVGX v1, docs/FORMAT.md)

Foydalanish:
  svgx encode --profile <D|P|I|U|G> [--force-structured] [--stats FAYL] KIRISH CHIQISH
      Bitta profil bilan siqadi. Natija = min(raw Brotli-11, strukturali); tenglikda raw.
      --force-structured  strukturali oqimni majburan yozadi (sinov va hisob uchun).
  svgx encode-all [--stats FAYL] KIRISH PAPKA
      Bitta tahlil va umumiy geometriya bilan barcha profillarni yozadi:
      raw.br, <P>.svgx (yakuniy), <P>.forced.svgx (strukturali, agar mavjud bo'lsa).
  svgx decode KIRISH CHIQISH     Qat'iy dekodlash (0x11 strukturali, 0x91 rad, boshqasi Brotli).
  svgx raw KIRISH CHIQISH        Faqat raw Brotli-11 (lgwin 22) oqimini yozadi.
  svgx analyze KIRISH            Tahlil statistikasini JSON ko'rinishida chiqaradi.
  svgx bench --profile P [--repeats N] [--warmup N] [--cpu K] [--modes L] KIRISH
      REV1: jarayon ichida, xotiradan xotiraga vaqt o'lchovi (JSON, nanosekund).
  REV1 ablation: encode / encode-all qo'shimcha [--modes L], L = 00,01,10,11 dan vergulli ro'yxat
      (00 majburiy; standart = hammasi, ya'ni muzlatilgan SVGX v1 bilan bir xil).
  svgx --version | --help

Chiqish kodlari: 0 muvaffaqiyat, 2 noto'g'ri buyruq, 3 fayl xatosi, 4 format/dekodlash xatosi.
";

fn fail(code: u8, msg: &str) -> ExitCode {
    eprintln!("xato: {}", msg);
    ExitCode::from(code)
}

fn read(p: &str) -> Result<Vec<u8>, ExitCode> {
    std::fs::read(p).map_err(|e| fail(3, &format!("{}: {}", p, e)))
}

fn write(p: &Path, data: &[u8]) -> Result<(), ExitCode> {
    let tmp = p.with_extension("tmp_svgx");
    std::fs::write(&tmp, data).map_err(|e| fail(3, &format!("{}: {}", tmp.display(), e)))?;
    std::fs::rename(&tmp, p).map_err(|e| fail(3, &format!("{}: {}", p.display(), e)))
}

fn role_stats_json(outs: &[ProfileOut]) -> J {
    // diagnostics are identical across profiles except P matches; take G (or any) plus P.
    let g = outs.iter().find(|o| o.profile == Profile::G).or(outs.first());
    let p = outs.iter().find(|o| o.profile == Profile::P);
    let g = match g {
        Some(g) => g,
        None => return J::Null,
    };
    let mut roles = Vec::new();
    for (r, st) in g.stats.iter().enumerate() {
        roles.push(J::obj(vec![
            ("role", J::n(r)),
            ("tokens", J::n(st.tokens)),
            ("escapes_rules", J::n(st.escapes)),
            ("multi_match", J::n(st.multi_match)),
            ("applicable_sum", J::n(st.applicable_sum)),
            ("distinct_outputs_sum", J::n(st.distinct_outputs_sum)),
            ("distinct_outputs_max", J::n(st.distinct_outputs_max)),
            ("ideal_bits_I", J::f(st.ideal_bits_i)),
            ("ideal_bits_U", J::f(st.ideal_bits_u)),
            ("ideal_bits_G", J::f(st.ideal_bits_g)),
            ("rule_hits", J::Arr(st.rule_hits.iter().map(|&v| J::n(v)).collect())),
            ("p_matches", J::n(p.map(|p| p.stats[r].p_matches).unwrap_or(0))),
        ]));
    }
    J::Arr(roles)
}

fn file_json(input: &[u8], a: &Analysis, raw: &[u8], common: Option<&Common>, outs: &[ProfileOut], finals: &[(Profile, usize, &'static str)]) -> J {
    let mut reasons = Vec::new();
    for (k, v) in &a.path_reasons {
        reasons.push((k.to_string(), J::n(*v)));
    }
    let blocks: usize = a.paths.iter().map(|p| p.blocks.len()).sum();
    let mut prof = Vec::new();
    for o in outs {
        let fin = finals.iter().find(|f| f.0 == o.profile);
        prof.push((
            o.profile.name().to_string(),
            J::obj(vec![
                ("forced_len", J::n(o.stream.len())),
                ("spelling_len", J::n(o.spelling_len)),
                ("spelling_bits", J::n(o.spelling_bits)),
                ("escape_len", J::n(o.escape_len)),
                ("escape_count", J::n(o.escape_count)),
                ("final_len", fin.map(|f| J::n(f.1)).unwrap_or(J::Null)),
                ("final_branch", fin.map(|f| J::s(f.2)).unwrap_or(J::Null)),
            ]),
        ));
    }
    let (common_j, ceiling) = match common {
        Some(c) => {
            let l = c.literal.len() + c.schedule.len();
            let r = c.geometry.len();
            let o = (container::HEADER_LEN + l + r).min(raw.len());
            (
                J::obj(vec![
                    ("header_len", J::n(container::HEADER_LEN)),
                    ("literal_len", J::n(c.literal.len())),
                    ("schedule_len", J::n(c.schedule.len())),
                    ("geometry_len", J::n(c.geometry.len())),
                    ("geometry_bits", J::n(c.geometry_bits)),
                    ("u_len", J::n(c.u_len)),
                    ("hole_count", J::n(c.hole_count)),
                    ("mode_counts", J::Arr(c.gstats.mode_counts.iter().map(|&v| J::n(v)).collect())),
                    ("geometry_header_bits", J::n(c.gstats.header_bits)),
                    ("geometry_residual_bits", J::n(c.gstats.residual_bits)),
                    ("ref_candidates_evaluated", J::n(c.gstats.ref_candidates_evaluated)),
                ]),
                J::n(o),
            )
        }
        None => (J::Null, J::n(raw.len())),
    };
    J::obj(vec![
        ("format", J::s("svgx-1")),
        ("codec_version", J::s(env!("CARGO_PKG_VERSION"))),
        ("brotli_version", J::s(&brotli::version())),
        ("input_len", J::n(input.len())),
        ("crc32", J::n(crc32::crc32(input))),
        ("raw_brotli_len", J::n(raw.len())),
        ("file_reason", a.file_reason.map(J::s).unwrap_or(J::Null)),
        ("eligible", J::Bool(!a.paths.is_empty())),
        ("svg_path_candidates", J::n(a.candidates)),
        ("modeled_paths", J::n(a.paths.len())),
        ("path_reasons", J::Obj(reasons)),
        ("blocks", J::n(blocks)),
        ("common", common_j),
        ("style_free_ceiling_O", ceiling),
        ("profiles", J::Obj(prof)),
        ("roles", role_stats_json(outs)),
    ])
}

struct Opts {
    profile: Option<Profile>,
    force: bool,
    stats: Option<PathBuf>,
    pos: Vec<String>,
    modes: u8,
    repeats: usize,
    warmup: usize,
    cpu: Option<u32>,
}

/// Parse a comma-separated list of prediction modes ("00,01,10,11"); mode 00 is mandatory.
fn parse_modes(v: &str) -> Result<u8, ExitCode> {
    let mut m = 0u8;
    for tok in v.split(',') {
        m |= match tok.trim() {
            "00" => 1,
            "01" => 2,
            "10" => 4,
            "11" => 8,
            other => return Err(fail(2, &format!("noma'lum rejim: {} (00,01,10,11)", other))),
        };
    }
    if m & 1 == 0 {
        return Err(fail(2, "--modes 00 rejimini o'z ichiga olishi shart"));
    }
    Ok(m)
}

fn parse_count(v: Option<&String>, name: &str) -> Result<usize, ExitCode> {
    v.and_then(|s| s.parse::<usize>().ok()).ok_or_else(|| fail(2, &format!("{} butun son talab qiladi", name)))
}

fn parse_opts(args: &[String]) -> Result<Opts, ExitCode> {
    let mut o = Opts {
        profile: None,
        force: false,
        stats: None,
        pos: Vec::new(),
        modes: geometry::ALL_MODES,
        repeats: 31,
        warmup: 5,
        cpu: None,
    };
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--profile" => {
                i += 1;
                let v = args.get(i).ok_or_else(|| fail(2, "--profile qiymati yo'q"))?;
                o.profile = Some(Profile::from_name(v).ok_or_else(|| fail(2, &format!("noma'lum profil: {}", v)))?);
            }
            "--force-structured" => o.force = true,
            "--modes" => {
                i += 1;
                o.modes = parse_modes(args.get(i).ok_or_else(|| fail(2, "--modes qiymati yo'q"))?)?;
            }
            "--repeats" => {
                i += 1;
                o.repeats = parse_count(args.get(i), "--repeats")?;
            }
            "--warmup" => {
                i += 1;
                o.warmup = parse_count(args.get(i), "--warmup")?;
            }
            "--cpu" => {
                i += 1;
                o.cpu = Some(parse_count(args.get(i), "--cpu")? as u32);
            }
            "--stats" => {
                i += 1;
                o.stats = Some(PathBuf::from(args.get(i).ok_or_else(|| fail(2, "--stats qiymati yo'q"))?));
            }
            s if s.starts_with("--") => return Err(fail(2, &format!("noma'lum parametr: {}", s))),
            s => o.pos.push(s.to_string()),
        }
        i += 1;
    }
    Ok(o)
}

fn run() -> Result<(), ExitCode> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let cmd = args.first().map(|s| s.as_str()).unwrap_or("--help");
    match cmd {
        "--help" | "-h" | "help" => {
            print!("{}", HELP);
            Ok(())
        }
        "--version" | "-V" => {
            println!("svgx {} (format svgx-1, brotli {}, cflags {})", env!("CARGO_PKG_VERSION"), brotli::version(), env!("SVGX_BROTLI_CFLAGS"));
            Ok(())
        }
        "decode" => {
            let o = parse_opts(&args[1..])?;
            if o.pos.len() != 2 {
                return Err(fail(2, "decode KIRISH CHIQISH"));
            }
            let data = read(&o.pos[0])?;
            let out = decode::decode(&data).map_err(|e| fail(4, &e.0))?;
            write(Path::new(&o.pos[1]), &out)
        }
        "raw" => {
            let o = parse_opts(&args[1..])?;
            if o.pos.len() != 2 {
                return Err(fail(2, "raw KIRISH CHIQISH"));
            }
            let data = read(&o.pos[0])?;
            write(Path::new(&o.pos[1]), &brotli::compress(&data))
        }
        "analyze" => {
            let o = parse_opts(&args[1..])?;
            if o.pos.len() != 1 {
                return Err(fail(2, "analyze KIRISH"));
            }
            let data = read(&o.pos[0])?;
            let a = encode::analyze(&data);
            let raw = brotli::compress(&data);
            print!("{}", file_json(&data, &a, &raw, None, &[], &[]).to_json());
            Ok(())
        }
        "encode" => {
            let o = parse_opts(&args[1..])?;
            let profile = o.profile.ok_or_else(|| fail(2, "--profile majburiy"))?;
            if o.pos.len() != 2 {
                return Err(fail(2, "encode --profile X KIRISH CHIQISH"));
            }
            let data = read(&o.pos[0])?;
            let raw = brotli::compress(&data);
            let a = encode::analyze(&data);
            let mut outs = Vec::new();
            let mut common = None;
            if !a.paths.is_empty() || o.force {
                let c = encode::build_common_modes(&data, &a, o.modes);
                outs.push(encode::build_profile(&data, &c, profile));
                common = Some(c);
            }
            let structured = outs.first().map(|p| p.stream.as_slice());
            let fin = encode::choose_final(&raw, structured, o.force);
            let branch = if fin[0] == container::MARKER { "structured" } else { "raw" };
            write(Path::new(&o.pos[1]), fin)?;
            if let Some(sp) = &o.stats {
                let j = file_json(&data, &a, &raw, common.as_ref(), &outs, &[(profile, fin.len(), branch)]);
                write(sp, j.to_json().as_bytes())?;
            }
            Ok(())
        }
        "encode-all" => {
            let o = parse_opts(&args[1..])?;
            if o.pos.len() != 2 {
                return Err(fail(2, "encode-all KIRISH PAPKA"));
            }
            let data = read(&o.pos[0])?;
            let dir = PathBuf::from(&o.pos[1]);
            std::fs::create_dir_all(&dir).map_err(|e| fail(3, &format!("{}: {}", dir.display(), e)))?;
            let raw = brotli::compress(&data);
            write(&dir.join("raw.br"), &raw)?;
            let a = encode::analyze(&data);
            let mut outs = Vec::new();
            let mut common = None;
            if !a.paths.is_empty() {
                let c = encode::build_common_modes(&data, &a, o.modes);
                for p in Profile::ALL {
                    outs.push(encode::build_profile(&data, &c, p));
                }
                common = Some(c);
            }
            let mut finals = Vec::new();
            for p in Profile::ALL {
                let structured = outs.iter().find(|x| x.profile == p).map(|x| x.stream.as_slice());
                let fin = encode::choose_final(&raw, structured, false);
                let branch = if fin[0] == container::MARKER { "structured" } else { "raw" };
                write(&dir.join(format!("{}.svgx", p.name())), fin)?;
                if let Some(s) = structured {
                    write(&dir.join(format!("{}.forced.svgx", p.name())), s)?;
                }
                finals.push((p, fin.len(), branch));
            }
            let j = file_json(&data, &a, &raw, common.as_ref(), &outs, &finals);
            let sp = o.stats.unwrap_or_else(|| dir.join("stats.json"));
            write(&sp, j.to_json().as_bytes())
        }
        "bench" => bench(&parse_opts(&args[1..])?),
        other => Err(fail(2, &format!("noma'lum buyruq: {} (svgx --help)", other))),
    }
}

/// REV1 timing support: pin the current thread to one logical processor and raise the process priority.
#[cfg(windows)]
mod affinity {
    #[link(name = "kernel32")]
    extern "system" {
        fn GetCurrentThread() -> isize;
        fn SetThreadAffinityMask(h: isize, mask: usize) -> usize;
        fn GetCurrentProcess() -> isize;
        fn SetPriorityClass(h: isize, class: u32) -> i32;
    }
    pub fn pin(cpu: u32) -> (bool, bool) {
        const HIGH_PRIORITY_CLASS: u32 = 0x0000_0080;
        if cpu as usize >= usize::BITS as usize {
            return (false, false);
        }
        // SAFETY: plain Win32 calls on pseudo-handles of the current thread and process.
        unsafe {
            let a = SetThreadAffinityMask(GetCurrentThread(), 1usize << cpu) != 0;
            let p = SetPriorityClass(GetCurrentProcess(), HIGH_PRIORITY_CLASS) != 0;
            (a, p)
        }
    }
}
#[cfg(not(windows))]
mod affinity {
    pub fn pin(_cpu: u32) -> (bool, bool) {
        (false, false)
    }
}

/// The exact pipeline of `svgx encode` (without file I/O): returns the shipped stream C = min(B, S).
fn encode_final(data: &[u8], profile: Profile, modes: u8) -> Vec<u8> {
    let raw = brotli::compress(data);
    let a = encode::analyze(data);
    let mut outs = Vec::new();
    if !a.paths.is_empty() {
        let c = encode::build_common_modes(data, &a, modes);
        outs.push(encode::build_profile(data, &c, profile));
    }
    let structured = outs.first().map(|p| p.stream.as_slice());
    encode::choose_final(&raw, structured, false).to_vec()
}

/// In-process, memory-to-memory timing of SVGX encode/decode and of the raw Brotli-11 branch alone,
/// both from the same library build. Operations are interleaved and their order rotates per repeat.
fn bench(o: &Opts) -> Result<(), ExitCode> {
    use std::hint::black_box;
    use std::time::Instant;
    let profile = o.profile.ok_or_else(|| fail(2, "--profile majburiy"))?;
    if o.pos.len() != 1 || o.repeats == 0 {
        return Err(fail(2, "bench --profile X [--repeats N>0] KIRISH"));
    }
    let data = read(&o.pos[0])?;
    let (pinned, high) = match o.cpu {
        Some(c) => affinity::pin(c),
        None => (false, false),
    };
    // reference outputs and correctness checks (not timed)
    let raw_ref = brotli::compress(&data);
    let fin_ref = encode_final(&data, profile, o.modes);
    let ok_final = decode::decode(&fin_ref).map(|v| v == data).unwrap_or(false);
    let ok_raw = decode::decode(&raw_ref).map(|v| v == data).unwrap_or(false);
    let branch = if fin_ref.first() == Some(&container::MARKER) { "structured" } else { "raw" };
    let mut t: [Vec<u128>; 4] = [Vec::new(), Vec::new(), Vec::new(), Vec::new()];
    let total = o.warmup + o.repeats;
    for r in 0..total {
        for k in 0..4 {
            let op = (r + k) % 4;
            let start = Instant::now();
            let n = match op {
                0 => black_box(encode_final(black_box(&data), profile, o.modes)).len(),
                1 => black_box(decode::decode(black_box(&fin_ref)).map(|v| v.len()).unwrap_or(0)),
                2 => black_box(brotli::compress(black_box(&data))).len(),
                _ => black_box(decode::decode(black_box(&raw_ref)).map(|v| v.len()).unwrap_or(0)),
            };
            let ns = start.elapsed().as_nanos();
            black_box(n);
            if r >= o.warmup {
                t[op].push(ns);
            }
        }
    }
    let arr = |v: &Vec<u128>| J::Arr(v.iter().map(|x| J::n(*x)).collect());
    let j = J::obj(vec![
        ("file_bytes", J::n(data.len())),
        ("profile", J::s(profile.name())),
        ("modes", J::n(o.modes)),
        ("final_len", J::n(fin_ref.len())),
        ("raw_len", J::n(raw_ref.len())),
        ("branch", J::s(branch)),
        ("restored_ok", J::Bool(ok_final && ok_raw)),
        ("cpu", o.cpu.map(J::n).unwrap_or(J::Null)),
        ("pinned", J::Bool(pinned)),
        ("high_priority", J::Bool(high)),
        ("warmup", J::n(o.warmup)),
        ("repeats", J::n(o.repeats)),
        ("encode_ns", arr(&t[0])),
        ("decode_ns", arr(&t[1])),
        ("raw_encode_ns", arr(&t[2])),
        ("raw_decode_ns", arr(&t[3])),
    ]);
    print!("{}", j.to_json());
    Ok(())
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(c) => c,
    }
}
