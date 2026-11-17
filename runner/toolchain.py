"""Acquire, verify and build the pinned toolchain and external baseline programs.

Every step is idempotent: it checks a stamp (with the pinned hash) and skips work that is already
valid. All messages are Uzbek. Only the Python standard library is used so this can run before the
virtual environment exists.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from .common import (DOWNLOADS, EXE, ROOT, TOOLS, USER_AGENT, atomic_write_json, read_json, run, say,
                     sha256_file, tool_env, toolchain_config)

BIN = TOOLS / "bin"
SRC = TOOLS / "src"
STAMPS = TOOLS / "stamps"
SYSTEM_TAR = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tar.exe"


class ToolError(RuntimeError):
    pass


# ---------------------------------------------------------------- generic helpers

def _stamp_ok(name: str, token: str) -> bool:
    data = read_json(STAMPS / f"{name}.json")
    return bool(data) and data.get("token") == token


def _stamp(name: str, token: str, **extra) -> None:
    atomic_write_json(STAMPS / f"{name}.json", {"token": token, **extra})


def fetch(key: str) -> Path:
    """Download a pinned file (if needed) and verify its SHA-256."""
    spec = toolchain_config()["download"][key]
    dest = DOWNLOADS / spec["file"]
    want = spec["sha256"].lower()
    if dest.exists() and sha256_file(dest) == want:
        return dest
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    say(f"  ↓ yuklab olinmoqda: {spec['file']} ({spec['version']})")
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(spec["url"], headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    got = sha256_file(tmp)
    if got != want:
        tmp.unlink(missing_ok=True)
        raise ToolError(f"SHA-256 mos kelmadi: {spec['file']} (kutilgan {want}, olingan {got})")
    os.replace(tmp, dest)
    return dest


def _safe_extract_zip(zpath: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zpath) as z:
        for m in z.infolist():
            target = (dest / m.filename).resolve()
            if not str(target).startswith(str(dest.resolve())):
                raise ToolError(f"Arxivda xavfli yo'l: {m.filename}")
        z.extractall(dest)


def _extract_tar_gz(tpath: Path, dest: Path, strip_top: bool = True) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="x_", dir=str(TOOLS)))
    try:
        with tarfile.open(tpath, "r:gz") as t:
            t.extractall(tmp, filter="data")
        entries = list(tmp.iterdir())
        src = entries[0] if strip_top and len(entries) == 1 and entries[0].is_dir() else tmp
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _extract_with_system_tar(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    tar = str(SYSTEM_TAR) if SYSTEM_TAR.exists() else "tar"
    run([tar, "-xf", archive, "-C", dest], capture=True)


def _version_line(cmd) -> str:
    try:
        res = subprocess.run([str(c) for c in cmd], capture_output=True, timeout=60, env=tool_env())
        out = (res.stdout or b"") + (res.stderr or b"")
        for line in out.decode("utf-8", "replace").splitlines():
            if line.strip():
                return line.strip()
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: {exc}"
    return ""


# ---------------------------------------------------------------- individual tools

def seven_zip_r() -> Path:
    exe = TOOLS / "7zr" / "7zr.exe"
    spec = toolchain_config()["download"]["sevenzip_r"]
    if exe.exists() and sha256_file(exe) == spec["sha256"]:
        return exe
    src = fetch("sevenzip_r")
    exe.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, exe)
    return exe


def seven_zip_a() -> Path:
    spec = toolchain_config()["download"]["sevenzip_extra"]
    exe = TOOLS / "7zip" / "x64" / "7za.exe"
    if exe.exists() and _stamp_ok("7zip", spec["sha256"]):
        return exe
    arc = fetch("sevenzip_extra")
    out = TOOLS / "7zip"
    if out.exists():
        shutil.rmtree(out)
    run([seven_zip_r(), "x", "-y", f"-o{out}", arc], capture=True)
    if not exe.exists():
        raise ToolError("7za.exe (x64) arxivdan topilmadi")
    _stamp("7zip", spec["sha256"], exe=str(exe))
    return exe


def winlibs_gcc() -> Path:
    spec = toolchain_config()["download"]["winlibs"]
    gcc = TOOLS / "winlibs" / "mingw64" / "bin" / "gcc.exe"
    if gcc.exists() and _stamp_ok("winlibs", spec["sha256"]):
        return gcc
    arc = fetch("winlibs")
    out = TOOLS / "winlibs"
    if out.exists():
        shutil.rmtree(out)
    say("  … WinLibs GCC ochilmoqda (bir necha daqiqa)")
    run([seven_zip_a(), "x", "-y", "-mmt=on", f"-o{out}", arc], capture=True)
    if not gcc.exists():
        raise ToolError("gcc.exe WinLibs arxivida topilmadi")
    _stamp("winlibs", spec["sha256"], version=_version_line([gcc, "--version"]))
    return gcc


def rust_toolchain() -> Path:
    cfg = toolchain_config()
    want = cfg["rust"]["toolchain"]
    cargo = TOOLS / "cargo" / "bin" / f"cargo{EXE}"
    token = f"{want}|{cfg['rust']['host']}|{cfg['download']['rustup_init']['sha256']}"
    if cargo.exists() and _stamp_ok("rust", token):
        return cargo
    init = fetch("rustup_init")
    env = tool_env()
    say(f"  … Rust {want} ({cfg['rust']['host']}) o'rnatilmoqda")
    run([init, "-y", "--no-modify-path", "--profile", cfg["rust"]["profile"],
         "--default-host", cfg["rust"]["host"], "--default-toolchain", want], env=env, capture=True)
    rustc = TOOLS / "cargo" / "bin" / f"rustc{EXE}"
    ver = _version_line([rustc, f"+{want}", "--version"])
    if want not in ver:
        raise ToolError(f"rustc versiyasi kutilganidek emas: {ver}")
    _stamp("rust", token, version=ver)
    return cargo


def brotli_source() -> Path:
    spec = toolchain_config()["download"]["brotli_src"]
    dest = ROOT / "codec" / "third_party" / "brotli"
    if (dest / "c" / "enc" / "encode.c").exists() and _stamp_ok("brotli_src", spec["sha256"]):
        return dest
    _extract_tar_gz(fetch("brotli_src"), dest)
    _stamp("brotli_src", spec["sha256"])
    return dest


def _cflags() -> list[str]:
    return list(toolchain_config()["cflags"]["common"])


def brotli_cli() -> Path:
    """Build the primary Brotli baseline (brotli.exe) from the same pinned C source as the codec."""
    src = brotli_source()
    gcc = winlibs_gcc()
    exe = BIN / "brotli.exe"
    token = f"{toolchain_config()['download']['brotli_src']['sha256']}|{' '.join(_cflags())}|{gcc}"
    if exe.exists() and _stamp_ok("brotli_cli", token):
        return exe
    files = []
    for sub in ("common", "dec", "enc"):
        files += sorted(str(p) for p in (src / "c" / sub).glob("*.c"))
    files.append(str(src / "c" / "tools" / "brotli.c"))
    BIN.mkdir(parents=True, exist_ok=True)
    say("  … brotli.exe yig'ilmoqda (Google C manbasi, -O2)")
    run([gcc, *_cflags(), "-I", src / "c" / "include", *files, "-o", exe, "-lm", "-static"],
        env=tool_env(), capture=True)
    _stamp("brotli_cli", token, version=_version_line([exe, "--version"]))
    return exe


def xwrt_cli() -> Path:
    spec = toolchain_config()["download"]["xwrt_src"]
    gpp = winlibs_gcc().with_name("g++.exe")
    exe = BIN / "xwrt.exe"
    token = f"{spec['sha256']}|{gpp}|v2"
    if exe.exists() and _stamp_ok("xwrt", token):
        return exe
    src = SRC / "xwrt"
    _extract_tar_gz(fetch("xwrt_src"), src)
    BIN.mkdir(parents=True, exist_ok=True)
    say("  … XWRT yig'ilmoqda (upstream Makefile'ning Windows fayllar ro'yxati, g++)")
    # File list and defines follow the upstream Makefile's Windows branch (decision D-07).
    units = (["LZMA/Windows/FileIO.cpp", "LZMA/LZMAlib.cpp", "LZMA/LZMAEncoder.cpp", "LZMA/LZMADecoder.cpp",
              "LZMA/7zip/Common/FileStreams.cpp", "LZMA/7zip/Common/StreamUtils.cpp",
              "LZMA/7zip/Common/OutBuffer.cpp", "LZMA/7zip/Common/InBuffer.cpp", "LZMA/StreamRam.cpp",
              "LZMA/Common/Alloc.cpp", "LZMA/7zip/Compress/LZ/LZInWindow.cpp",
              "LZMA/7zip/Compress/LZ/LZOutWindow.cpp", "LZMA/7zip/Compress/RangeCoder/RangeCoderBit.cpp",
              "LZMA/Common/CRC.cpp", "LZMA/Common/StringConvert.cpp", "LZMA/Common/NewHandler.cpp"]
             + [f"zlib/{n}.c" for n in ("adler32", "compress", "crc32", "deflate", "gzclose", "gzlib", "gzread",
                                        "gzwrite", "infback", "inffast", "inflate", "inftrees", "trees",
                                        "uncompr", "zutil")]
             + ["src/XWRT.cpp", "src/Encoder.cpp", "src/Decoder.cpp", "src/MemBuffer.cpp", "src/Common.cpp",
                "PPMd/Model.cpp", "PPMd/PPMdlib.cpp"])
    defines = ["-D_WIN32_ENVIRONMENT_", "-D__x86_64__", "-I."]
    opt = ["-O3", "-fomit-frame-pointer", "-fstrict-aliasing", "-ffast-math", "-w"]
    objs = []
    obj_dir = src / "_obj"
    obj_dir.mkdir(exist_ok=True)
    for u in units:
        o = obj_dir / (u.replace("/", "_") + ".o")
        if u.endswith(".c"):
            cmd = [winlibs_gcc(), *opt, *defines, "-c", u, "-o", o]
        else:
            cmd = [gpp, *opt, "-std=gnu++98", "-fpermissive", *defines, "-c", u, "-o", o]
        run(cmd, cwd=src, env=tool_env(), capture=True)
        objs.append(o)
    run([gpp, *objs, "-o", exe, "-static", "-lshell32", "-lole32", "-loleaut32"], cwd=src, env=tool_env(),
        capture=True)
    _stamp("xwrt", token)
    return exe


def xz_cli() -> Path:
    spec = toolchain_config()["download"]["xz"]
    out = TOOLS / "xz"
    exe = out / "bin_x86-64" / "xz.exe"
    if exe.exists() and _stamp_ok("xz", spec["sha256"]):
        return exe
    if out.exists():
        shutil.rmtree(out)
    _safe_extract_zip(fetch("xz"), out)
    if not exe.exists():
        cands = list(out.rglob("xz.exe"))
        if not cands:
            raise ToolError("xz.exe topilmadi")
        exe = [p for p in cands if "x86-64" in str(p)][0] if any("x86-64" in str(p) for p in cands) else cands[0]
    _stamp("xz", spec["sha256"], exe=str(exe))
    return exe


def zstd_cli() -> Path:
    spec = toolchain_config()["download"]["zstd"]
    out = TOOLS / "zstd"
    if _stamp_ok("zstd", spec["sha256"]):
        exe = Path(read_json(STAMPS / "zstd.json")["exe"])
        if exe.exists():
            return exe
    if out.exists():
        shutil.rmtree(out)
    _safe_extract_zip(fetch("zstd"), out)
    cands = list(out.rglob("zstd.exe"))
    if not cands:
        raise ToolError("zstd.exe topilmadi")
    _stamp("zstd", spec["sha256"], exe=str(cands[0]))
    return cands[0]


def gzip_cli() -> Path:
    cfg = toolchain_config()["download"]
    token = cfg["gzip_msys"]["sha256"] + "|" + cfg["msys2_runtime"]["sha256"]
    out = TOOLS / "msys"
    exe = out / "usr" / "bin" / "gzip.exe"
    if exe.exists() and _stamp_ok("gzip", token):
        return exe
    if out.exists():
        shutil.rmtree(out)
    _extract_with_system_tar(fetch("gzip_msys"), out)
    _extract_with_system_tar(fetch("msys2_runtime"), out)
    if not exe.exists():
        raise ToolError("gzip.exe MSYS2 paketida topilmadi")
    _stamp("gzip", token, exe=str(exe))
    return exe


def tool_paths() -> dict[str, str]:
    """Paths of every acquired program (no acquisition is triggered)."""
    return {
        "7za": str(TOOLS / "7zip" / "x64" / "7za.exe"),
        "gcc": str(TOOLS / "winlibs" / "mingw64" / "bin" / "gcc.exe"),
        "cargo": str(TOOLS / "cargo" / "bin" / f"cargo{EXE}"),
        "brotli": str(BIN / "brotli.exe"),
        "xwrt": str(BIN / "xwrt.exe"),
        "xz": str(TOOLS / "xz" / "bin_x86-64" / "xz.exe"),
        "zstd": (read_json(STAMPS / "zstd.json") or {}).get("exe", ""),
        "gzip": str(TOOLS / "msys" / "usr" / "bin" / "gzip.exe"),
    }


def acquire_all(report: dict) -> dict:
    """Run every acquisition/build step; record successes and verified failure reasons."""
    steps = [
        ("7zr", seven_zip_r), ("7za", seven_zip_a), ("winlibs_gcc", winlibs_gcc), ("rust", rust_toolchain),
        ("brotli_source", brotli_source), ("brotli_cli", brotli_cli), ("xz", xz_cli), ("zstd", zstd_cli),
        ("gzip", gzip_cli), ("xwrt", xwrt_cli),
    ]
    for name, fn in steps:
        try:
            path = fn()
            report[name] = {"status": "ok", "path": str(path)}
            say(f"  ✓ {name}: tayyor")
        except Exception as exc:  # noqa: BLE001 - record and continue; caller decides if fatal
            report[name] = {"status": "failed", "reason": str(exc)[-2000:]}
            say(f"  ✗ {name}: xato — {str(exc).splitlines()[0] if str(exc) else exc!r}")
    return report
