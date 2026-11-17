//! Compiles Google's pinned Brotli C sources into a static library without third-party crates.
//! The compiler and flags are the same ones used for the `brotli.exe` baseline (decision D-02).
use std::env;
use std::path::{Path, PathBuf};
use std::process::Command;

fn run(cmd: &mut Command) {
    let status = cmd.status().unwrap_or_else(|e| panic!("cannot start {:?}: {}", cmd, e));
    if !status.success() {
        panic!("command failed: {:?}", cmd);
    }
}

fn main() {
    println!("cargo:rerun-if-changed=build.rs");
    println!("cargo:rerun-if-env-changed=BROTLI_SRC");
    println!("cargo:rerun-if-env-changed=SVGX_CFLAGS");
    let manifest = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());
    let src = env::var("BROTLI_SRC")
        .map(PathBuf::from)
        .unwrap_or_else(|_| manifest.join("third_party").join("brotli"));
    let cdir = src.join("c");
    if !cdir.join("enc").join("encode.c").exists() {
        panic!("Brotli C source not found at {} (run prepare first)", src.display());
    }
    let target = env::var("TARGET").unwrap();
    let key = target.replace('-', "_");
    let cc = env::var(format!("CC_{}", key))
        .or_else(|_| env::var("CC"))
        .unwrap_or_else(|_| "gcc".to_string());
    let ar = env::var(format!("AR_{}", key))
        .or_else(|_| env::var("AR"))
        .unwrap_or_else(|_| "ar".to_string());
    let flags: Vec<String> = env::var("SVGX_CFLAGS")
        .unwrap_or_else(|_| "-O2 -fno-fast-math -ffp-contract=off -fno-strict-aliasing".to_string())
        .split_whitespace()
        .map(|s| s.to_string())
        .collect();
    let out = PathBuf::from(env::var("OUT_DIR").unwrap());
    let mut objs: Vec<PathBuf> = Vec::new();
    for sub in ["common", "dec", "enc"] {
        let mut files: Vec<PathBuf> = std::fs::read_dir(cdir.join(sub))
            .unwrap()
            .filter_map(|e| e.ok().map(|e| e.path()))
            .filter(|p| p.extension().map(|x| x == "c").unwrap_or(false))
            .collect();
        files.sort();
        for f in files {
            println!("cargo:rerun-if-changed={}", f.display());
            let stem = f.file_stem().unwrap().to_string_lossy().to_string();
            let obj = out.join(format!("{}_{}.o", sub, stem));
            run(Command::new(&cc)
                .args(&flags)
                .arg("-I")
                .arg(cdir.join("include"))
                .arg("-c")
                .arg(&f)
                .arg("-o")
                .arg(&obj));
            objs.push(obj);
        }
    }
    let lib = out.join("libsvgxbrotli.a");
    let _ = std::fs::remove_file(&lib);
    run(Command::new(&ar).arg("crs").arg(&lib).args(&objs));
    println!("cargo:rustc-link-search=native={}", Path::new(&out).display());
    println!("cargo:rustc-link-lib=static=svgxbrotli");
    println!("cargo:rustc-env=SVGX_BROTLI_CFLAGS={}", flags.join(" "));
}
