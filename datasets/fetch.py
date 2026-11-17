"""Reproducible public acquisition of licensed SVG candidates (preparation step; no compression).

    python datasets/fetch.py public            # npm + GitHub + Wikimedia Commons (resumable)
    python datasets/fetch.py local DIR META.csv  # local corpus: META columns path,category,family,license,creator,source,date

Writes data/sources.csv (one pinned row per source) and data/candidates.csv (one row per file).
Content is stored content-addressed in data/cache/files/<sha256>.svg. Requests use a generic
User-Agent (no personal data), polite throttling and Retry-After backoff.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import html
import io
import json
import re
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from runner.common import USER_AGENT, atomic_write_json, atomic_write_text, read_json, study_config, toolchain_config  # noqa: E402

DATA = ROOT / "data"
CACHE = DATA / "cache"
FILES = CACHE / "files"
STATE = CACHE / "fetch_state.json"
SOURCES_CSV = DATA / "sources.csv"
CANDIDATES_CSV = DATA / "candidates.csv"
CUTOFF = "2026-10-30T00:00:00Z"
PER_FAMILY_CANDIDATES = 160

# --------------------------------------------------------------------------- source registry
NPM = [  # (package, glob regex on tar path, category, family, lineage group)
    ("bootstrap-icons", r"^package/icons/[^/]+\.svg$", "icons", "bootstrap-icons", "bootstrap-icons"),
    ("@tabler/icons", r"^package/icons/(outline|filled)/[^/]+\.svg$", "icons", "tabler-icons", "tabler-icons"),
    ("@mdi/svg", r"^package/svg/[^/]+\.svg$", "icons", "materialdesignicons", "material-lineage"),
    ("@material-design-icons/svg", r"^package/(filled|outlined|round)/[^/]+\.svg$", "icons", "google-material-icons", "material-lineage"),
    ("@fortawesome/fontawesome-free", r"^package/svgs/(solid|regular|brands)/[^/]+\.svg$", "icons", "fontawesome-free", "fontawesome"),
    ("ionicons", r"^package/dist/svg/[^/]+\.svg$", "icons", "ionicons", "ionicons"),
    ("feather-icons", r"^package/dist/icons/[^/]+\.svg$", "icons", "feather-icons", "feather-lineage"),
    ("lucide-static", r"^package/icons/[^/]+\.svg$", "icons", "lucide", "feather-lineage"),
    ("@phosphor-icons/core", r"^package/assets/(regular|fill|duotone)/[^/]+\.svg$", "icons", "phosphor", "phosphor"),
    ("iconoir", r"^package/icons/(regular|solid)/[^/]+\.svg$", "icons", "iconoir", "iconoir"),
    ("remixicon", r"^package/icons/[^/]+/[^/]+\.svg$", "icons", "remixicon", "remixicon"),
    ("@primer/octicons", r"^package/build/svg/[^/]+\.svg$", "icons", "octicons", "octicons"),
    ("heroicons", r"^package/(24|20)/(outline|solid)/[^/]+\.svg$", "icons", "heroicons", "heroicons"),
    ("@carbon/icons", r"^package/svg/32/[^/]+\.svg$", "icons", "carbon", "carbon"),
    ("@fluentui/svg-icons", r"^package/icons/[^/]+\.svg$", "icons", "fluentui-system-icons", "fluentui"),
    ("simple-icons", r"^package/icons/[^/]+\.svg$", "icons", "simple-icons", "simple-icons"),
    ("eva-icons", r"^package/(fill|outline)/svg/[^/]+\.svg$", "icons", "eva-icons", "eva-icons"),
    ("boxicons", r"^package/svg/(regular|solid|logos)/[^/]+\.svg$", "icons", "boxicons", "boxicons"),
    ("css.gg", r"^package/icons/svg/[^/]+\.svg$", "icons", "css-gg", "css-gg"),
    ("@coreui/icons", r"^package/svg/(free|brand|flag)/[^/]+\.svg$", "icons", "coreui-icons", "coreui"),
    ("pixelarticons", r"^package/svg/[^/]+\.svg$", "icons", "pixelarticons", "pixelarticons"),
    ("typicons.font", r"^package/src/svg/[^/]+\.svg$", "icons", "typicons", "typicons"),
    ("@svg-maps/world", r"^package/world\.svg$", "maps", "svg-maps", "svg-maps"),
    ("@svg-maps/usa", r"^package/usa\.svg$", "maps", "svg-maps", "svg-maps"),
    ("@svg-maps/france.departments", r"^package/[^/]+\.svg$", "maps", "svg-maps", "svg-maps"),
    ("@svg-maps/canada", r"^package/canada\.svg$", "maps", "svg-maps", "svg-maps"),
    ("@svg-maps/brazil", r"^package/[^/]+\.svg$", "maps", "svg-maps", "svg-maps"),
    ("@svg-maps/china", r"^package/[^/]+\.svg$", "maps", "svg-maps", "svg-maps"),
    ("@svg-maps/india", r"^package/[^/]+\.svg$", "maps", "svg-maps", "svg-maps"),
    ("@svg-maps/japan", r"^package/[^/]+\.svg$", "maps", "svg-maps", "svg-maps"),
    ("@svg-maps/germany", r"^package/[^/]+\.svg$", "maps", "svg-maps", "svg-maps"),
    ("@svg-maps/italy", r"^package/[^/]+\.svg$", "maps", "svg-maps", "svg-maps"),
    ("@svg-maps/spain", r"^package/[^/]+\.svg$", "maps", "svg-maps", "svg-maps"),
    ("@svg-maps/australia", r"^package/[^/]+\.svg$", "maps", "svg-maps", "svg-maps"),
    ("@svg-maps/mexico", r"^package/[^/]+\.svg$", "maps", "svg-maps", "svg-maps"),
    ("@mapbox/maki", r"^package/icons/[^/]+\.svg$", "icons", "maki", "maki"),
]
GITHUB = [  # (owner/repo, path prefix, regex on path, category, family, lineage, license)
    ("googlefonts/noto-emoji", "2D/svg", r"^2D/svg/[^/]+\.svg$", "illustrations", "noto-emoji", "noto-lineage", "Apache-2.0"),
    ("jdecked/twemoji", "assets/svg", r"^assets/svg/[^/]+\.svg$", "illustrations", "twemoji", "twemoji", "CC-BY-4.0"),
    ("hfg-gmuend/openmoji", "color/svg", r"^color/svg/[^/]+\.svg$", "illustrations", "openmoji", "openmoji", "CC-BY-SA-4.0"),
    ("microsoft/fluentui-emoji", "assets", r"^assets/.+/(Flat|Color)/[^/]+\.svg$", "illustrations", "fluent-emoji", "fluent-emoji", "MIT"),
    ("EmojiTwo/emojitwo", "svg", r"^svg/[^/]+\.svg$", "illustrations", "emojitwo", "emojione-lineage", "CC-BY-4.0"),
    ("mozilla/fxemoji", "svgs/FirefoxEmoji", r"^svgs/FirefoxEmoji/[^/]+\.svg$", "illustrations", "firefox-emoji", "fxemoji", "CC-BY-4.0 (visual design, LICENSE.md)"),
    ("vega/vega-lite", "examples/compiled", r"^examples/compiled/[^/]+\.svg$", "diagrams", "vega-lite", "vega", "BSD-3-Clause"),
    ("matplotlib/matplotlib", "lib/matplotlib/tests/baseline_images", r"^lib/matplotlib/tests/baseline_images/.+\.svg$", "diagrams", "matplotlib-baselines", "matplotlib", "Matplotlib license (PSF-based, BSD-compatible)"),
    ("tidyverse/ggplot2", "tests/testthat/_snaps", r"^tests/testthat/_snaps/.+\.svg$", "diagrams", "ggplot2-snapshots", "ggplot2", "MIT"),
    ("terrastruct/d2", "e2etests/testdata", r"^e2etests/testdata/.+\.svg$", "diagrams", "d2-e2e", "d2", "MPL-2.0"),
    ("mledoze/countries", "data", r"^data/[^/]+\.svg$", "maps", "mledoze-countries", "mledoze", "ODbL-1.0"),
    ("game-icons/icons", "", r"^[^/]+/.+\.svg$", "icons", "game-icons", "game-icons", "CC-BY-3.0 (or CC0 where stated, license.txt)"),
]
COMMONS = {  # category -> CirrusSearch deepcat seeds
    "maps": ["SVG maps", "Blank maps", "SVG locator maps"],
    "diagrams": ["SVG diagrams"],
    "illustrations": ["SVG people", "SVG animals", "SVG plants", "SVG food", "SVG vehicles", "SVG clip art"],
}
# Candidate pool targets (decision D-12): sized for the quotas and family breadth while respecting
# Wikimedia's rate limits for an unidentified generic client (>= 2.5 s between file downloads).
COMMONS_TARGET = {"maps": 750, "diagrams": 750, "illustrations": 450}
COMMONS_DOWNLOAD_INTERVAL = 20.0    # trickle mode (decision D-12): Wikimedia bans bursts from generic clients
COMMONS_API_INTERVAL = 5.0
COMMONS_TIME_BUDGET_S = 3600        # per fetch run; later runs resume from the saved state
COMMONS_MAX_RETRY_AFTER_S = 120     # a longer server-imposed ban stops Commons for this run
COMMONS_PER_VISIT = 2               # files taken per page visit before rotating to the next category
COMMONS_WAIT_BANS = True            # wait out a server ban (Retry-After + 10 s) while the budget allows


class RateLimited(RuntimeError):
    def __init__(self, msg: str, delay: float = 0.0):
        super().__init__(msg)
        self.delay = delay
ALLOWED_COMMONS = re.compile(r"^(cc0|public domain|pd\b|pd-|cc[- ]by(-sa)?[- ]\d|cc[- ]by(-sa)?$)", re.I)


# --------------------------------------------------------------------------- polite HTTP

class Http:
    def __init__(self):
        self.last = {}

    def get(self, url: str, *, min_interval: float = 0.4, retries: int = 6, accept_json: bool = False,
            max_retry_after: float | None = None) -> bytes:
        host = urllib.parse.urlparse(url).netloc
        for attempt in range(retries):
            wait = self.last.get(host, 0) + min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self.last[host] = time.monotonic()
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = r.read()
                    if r.headers.get("Content-Encoding") == "gzip":
                        data = gzip.decompress(data)
                    return data
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504):
                    ra = e.headers.get("Retry-After")
                    delay = float(ra) if ra and ra.isdigit() else min(120, 5 * 2 ** attempt)
                    if max_retry_after is not None and delay > max_retry_after:
                        raise RateLimited(f"{host}: Retry-After {delay:.0f} s", delay)
                    delay = max(delay, 2.0 * (attempt + 1))
                    print(f"    … {e.code}, {delay:.0f} s kutilmoqda ({host})", flush=True)
                    time.sleep(delay)
                    continue
                raise
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                delay = min(60, 3 * 2 ** attempt)
                print(f"    … tarmoq xatosi ({e}); {delay} s", flush=True)
                time.sleep(delay)
        raise RuntimeError(f"so'rov muvaffaqiyatsiz: {url}")

    def json(self, url: str, **kw):
        return json.loads(self.get(url, **kw).decode("utf-8"))


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def seeded_order(items: list[str], salt: str) -> list[str]:
    return sorted(items, key=lambda s: hashlib.sha256((salt + "\0" + s).encode()).hexdigest())


def looks_like_svg(b: bytes) -> bool:
    head = b[:4096].lower()
    return b"<svg" in head or (b"<?xml" in head and b"<svg" in b[:65536].lower())


def store(b: bytes) -> str:
    h = sha256(b)
    p = FILES / f"{h}.svg"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b)
    return h


# --------------------------------------------------------------------------- npm

def fetch_npm(http: Http, state: dict, max_bytes: int) -> tuple[list, list]:
    sources, cands = [], []
    for pkg, pattern, cat, fam, group in NPM:
        sid = f"npm:{pkg}"
        st = state.get(sid)
        if st and st.get("done") and st["source"].get("status") == "ok" and st["source"].get("candidates", 0) > 0:
            sources.append(st["source"])
            cands += st["candidates"]
            continue
        try:
            meta = http.json("https://registry.npmjs.org/" + urllib.parse.quote(pkg, safe="@"), min_interval=0.3)
            times = meta.get("time", {})
            vers = [v for v in meta.get("versions", {}) if "-" not in v and times.get(v, "9999") < CUTOFF]
            if not vers:
                raise RuntimeError("cutoff oldidan reliz yo'q")
            ver = max(vers, key=lambda v: times[v])
            vm = meta["versions"][ver]
            tar_url = vm["dist"]["tarball"]
            tgz = http.get(tar_url, min_interval=0.3)
            integ = vm["dist"].get("integrity", "")
            if integ.startswith("sha512-"):
                import base64
                if base64.b64encode(hashlib.sha512(tgz).digest()).decode() != integ[7:]:
                    raise RuntimeError("npm integrity mos emas")
            lic = vm.get("license") if isinstance(vm.get("license"), str) else json.dumps(vm.get("license"))
            rx = re.compile(pattern)
            members = {}
            with tarfile.open(fileobj=io.BytesIO(tgz), mode="r:gz") as t:
                for m in t.getmembers():
                    if m.isfile() and rx.match(m.name) and m.size <= max_bytes:
                        members[m.name] = m
                chosen = seeded_order(list(members), f"{sid}@{ver}")[:PER_FAMILY_CANDIDATES]
                rows = []
                for name in chosen:
                    b = t.extractfile(members[name]).read()
                    if not looks_like_svg(b):
                        continue
                    h = store(b)
                    rows.append({"sha256": h, "size": len(b), "category": cat, "family": fam, "lineage": group,
                                 "creator": fam, "license": lic, "source_id": sid, "revision": ver,
                                 "url": tar_url + "#" + name[len("package/"):], "path": name[len("package/"):],
                                 "date": times[ver][:10], "title": Path(name).stem})
            src = {"source_id": sid, "kind": "npm", "name": pkg, "revision": ver, "published": times[ver],
                   "url": tar_url, "archive_sha256": sha256(tgz), "integrity": integ, "license": lic, "category": cat,
                   "family": fam, "lineage": group, "available_files": len(members), "candidates": len(rows), "status": "ok"}
            print(f"  ✓ {pkg}@{ver}: {len(rows)}/{len(members)} nomzod", flush=True)
        except Exception as e:  # noqa: BLE001 - record verified reason
            src = {"source_id": sid, "kind": "npm", "name": pkg, "status": f"failed: {e}", "category": cat, "family": fam}
            rows = []
            print(f"  ✗ {pkg}: {e}", flush=True)
        state[sid] = {"done": True, "source": src, "candidates": rows}
        atomic_write_json(STATE, state)
        sources.append(src)
        cands += rows
    return sources, cands


# --------------------------------------------------------------------------- GitHub

def gh_tree(http: Http, repo: str, sha: str, prefix: str) -> list[str]:
    """List blob paths under `prefix` by walking non-recursive trees, then recursing below it."""
    tree_sha = sha
    walked = ""
    for part in [p for p in prefix.split("/") if p]:
        t = http.json(f"https://api.github.com/repos/{repo}/git/trees/{tree_sha}", min_interval=1.0)
        nxt = [e for e in t["tree"] if e["path"] == part and e["type"] == "tree"]
        if not nxt:
            raise RuntimeError(f"yo'l topilmadi: {walked}{part}")
        tree_sha = nxt[0]["sha"]
        walked += part + "/"
    t = http.json(f"https://api.github.com/repos/{repo}/git/trees/{tree_sha}?recursive=1", min_interval=1.0)
    if t.get("truncated"):
        print(f"    ! {repo}: daraxt qisqartirilgan (truncated) — mavjud qism ishlatiladi", flush=True)
    return [walked + e["path"] for e in t["tree"] if e["type"] == "blob"]


def fetch_github(http: Http, state: dict, max_bytes: int) -> tuple[list, list]:
    sources, cands = [], []
    for repo, prefix, pattern, cat, fam, group, lic in GITHUB:
        sid = f"github:{repo}"
        st = state.get(sid)
        if st and st.get("done") and st["source"].get("status") == "ok" and st["source"].get("candidates", 0) > 0:
            sources.append(st["source"])
            cands += st["candidates"]
            continue
        try:
            info = http.json(f"https://api.github.com/repos/{repo}", min_interval=1.0)
            branch = info["default_branch"]
            commits = http.json(f"https://api.github.com/repos/{repo}/commits?sha={branch}&until={CUTOFF}&per_page=1",
                                min_interval=1.0)
            sha = commits[0]["sha"]
            date = commits[0]["commit"]["committer"]["date"]
            paths = [p for p in gh_tree(http, repo, sha, prefix) if re.match(pattern, p)]
            chosen = seeded_order(paths, f"{sid}@{sha}")
            rows = []
            for p in chosen:
                if len(rows) >= PER_FAMILY_CANDIDATES:
                    break
                url = f"https://raw.githubusercontent.com/{repo}/{sha}/{urllib.parse.quote(p)}"
                b = http.get(url, min_interval=0.15)
                if len(b) > max_bytes or not looks_like_svg(b):
                    continue
                h = store(b)
                rows.append({"sha256": h, "size": len(b), "category": cat, "family": fam, "lineage": group, "creator": fam,
                             "license": lic, "source_id": sid, "revision": sha, "url": url, "path": p, "date": date[:10],
                             "title": Path(p).stem})
            src = {"source_id": sid, "kind": "github", "name": repo, "revision": sha, "published": date,
                   "url": f"https://github.com/{repo}/tree/{sha}/{prefix}", "license": lic, "category": cat,
                   "family": fam, "lineage": group, "available_files": len(paths), "candidates": len(rows), "status": "ok"}
            print(f"  ✓ {repo}@{sha[:10]}: {len(rows)}/{len(paths)} nomzod", flush=True)
        except Exception as e:  # noqa: BLE001
            src = {"source_id": sid, "kind": "github", "name": repo, "status": f"failed: {e}", "category": cat, "family": fam}
            rows = []
            print(f"  ✗ {repo}: {e}", flush=True)
        state[sid] = {"done": True, "source": src, "candidates": rows}
        atomic_write_json(STATE, state)
        sources.append(src)
        cands += rows
    return sources, cands


# --------------------------------------------------------------------------- Wikimedia Commons

API = "https://commons.wikimedia.org/w/api.php"


def strip_html(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def norm_family(artist: str, user: str) -> str:
    a = strip_html(artist).lower()
    a = re.sub(r"\b(own work|derivative work|based on|by|this file was|created by|user:)\b", " ", a)
    a = re.sub(r"[^a-z0-9À-￿]+", "-", a).strip("-")[:60]
    if not a or a in ("unknown", "anonymous", "see-below", "see-source"):
        a = "user-" + re.sub(r"[^a-z0-9]+", "-", (user or "unknown").lower()).strip("-")
    return "commons:" + a


def commons_search(http: Http, seed: str, offset: int):
    q = {"action": "query", "format": "json", "formatversion": "2", "generator": "search",
         "gsrsearch": f'deepcat:"{seed}" filemime:image/svg+xml', "gsrnamespace": "6", "gsrlimit": "50",
         "gsroffset": str(offset), "prop": "imageinfo", "iiprop": "url|size|sha1|mime|timestamp|user|extmetadata",
         "iiextmetadatafilter": "LicenseShortName|Artist|DateTimeOriginal|UsageTerms|Copyrighted"}
    return http.json(API + "?" + urllib.parse.urlencode(q), min_interval=COMMONS_API_INTERVAL)


def fetch_commons(http: Http, state: dict, max_bytes: int) -> tuple[list, list]:
    """Round-robin over categories and seeds, a few files per page visit, trickle rate, time budget.

    A title is marked seen once accepted or rejected; a page offset advances only after every title
    on it has been seen, so an interrupted run resumes exactly where it stopped.
    """
    t_start = time.monotonic()
    stop_reason = None
    sts = {}
    for cat in COMMONS:
        st = state.setdefault(f"commons:{cat}", {"done": False, "rows": [], "offsets": {}, "rejected": {}})
        st.setdefault("seen", [r["title"] for r in st["rows"]])
        st.setdefault("exhausted", [])
        sts[cat] = st
    seen = {t for st in sts.values() for t in st["seen"]}

    def need(cat, seed):
        st = sts[cat]
        per_seed = max(1, COMMONS_TARGET[cat] // len(COMMONS[cat]))
        return seed not in st["exhausted"] and sum(1 for r in st["rows"] if r.get("seed") == seed) < per_seed

    width = max(len(v) for v in COMMONS.values())
    pairs = [(cat, seeds[i]) for i in range(width) for cat, seeds in COMMONS.items() if i < len(seeds)]

    def wait_out(e: RateLimited) -> bool:
        remaining = COMMONS_TIME_BUDGET_S - (time.monotonic() - t_start)
        if COMMONS_WAIT_BANS and remaining > e.delay + 60:
            print(f"    … Wikimedia taqiqi: {e.delay:.0f} s kutilmoqda (qolgan byudjet {remaining / 60:.0f} daqiqa)", flush=True)
            atomic_write_json(STATE, state)
            time.sleep(e.delay + 10)
            return True
        return False

    while not stop_reason and any(need(c, s) for c, ss in COMMONS.items() for s in ss):
        for cat, seed in pairs:
            st = sts[cat]
            if True:
                if stop_reason or not need(cat, seed):
                    continue
                if time.monotonic() - t_start > COMMONS_TIME_BUDGET_S:
                    stop_reason = "time budget for this run exhausted (resumable)"
                    break
                offset = st["offsets"].get(seed, 0)
                if offset >= 9500:
                    st["exhausted"].append(seed)
                    continue
                try:
                    d = commons_search(http, seed, offset)
                except RateLimited as e:
                    if wait_out(e):
                        continue
                    stop_reason = f"rate limited by Wikimedia ({e}); resumable"
                    break
                except Exception as e:  # noqa: BLE001
                    print(f"    ! qidiruv xatosi ({seed}): {e}", flush=True)
                    st["exhausted"].append(seed)
                    continue
                pages = sorted((d.get("query") or {}).get("pages") or [], key=lambda p: p.get("index", 0))
                taken = 0
                for pg in pages:
                    title = pg["title"]
                    if title in seen:
                        continue
                    if taken >= COMMONS_PER_VISIT or not need(cat, seed):
                        break
                    ii = (pg.get("imageinfo") or [None])[0]
                    if ii is None:
                        seen.add(title); st["seen"].append(title)
                        continue
                    em = ii.get("extmetadata") or {}
                    lic = strip_html((em.get("LicenseShortName") or {}).get("value", ""))
                    reject = None
                    if not ALLOWED_COMMONS.match(lic):
                        reject = "license"
                    elif ii.get("size", 0) > max_bytes:
                        reject = "size"
                    b = None
                    if reject is None:
                        try:
                            b = http.get(ii["url"], min_interval=COMMONS_DOWNLOAD_INTERVAL, retries=4,
                                         max_retry_after=COMMONS_MAX_RETRY_AFTER_S)
                        except RateLimited as e:
                            if wait_out(e):
                                break          # revisit this page on the next round (title not marked seen)
                            stop_reason = f"rate limited by Wikimedia ({e}); resumable"
                            break
                        except Exception as e:  # noqa: BLE001
                            reject = "download"
                            print(f"    ! yuklab bo'lmadi {title}: {e}", flush=True)
                        if b is not None and (hashlib.sha1(b).hexdigest() != ii.get("sha1") or not looks_like_svg(b)):
                            reject = "integrity"
                    seen.add(title)
                    st["seen"].append(title)
                    if reject:
                        st["rejected"][reject] = st["rejected"].get(reject, 0) + 1
                        continue
                    h = store(b)
                    artist = (em.get("Artist") or {}).get("value", "")
                    date = strip_html((em.get("DateTimeOriginal") or {}).get("value", ""))[:10] or ii["timestamp"][:10]
                    st["rows"].append({"sha256": h, "size": len(b), "category": cat,
                                       "family": norm_family(artist, ii.get("user", "")), "lineage": "",
                                       "creator": strip_html(artist)[:120] or ii.get("user", ""), "license": lic,
                                       "source_id": f"commons:{cat}", "revision": ii["timestamp"], "url": ii["url"],
                                       "path": title, "date": ii["timestamp"][:10], "title": title, "seed": seed,
                                       "upload_date": ii["timestamp"][:10], "original_date": date})
                    taken += 1
                if not stop_reason and pages and all(p["title"] in seen for p in pages):
                    st["offsets"][seed] = offset + 50
                    if "continue" not in d:
                        st["exhausted"].append(seed)
                elif not pages:
                    st["exhausted"].append(seed)
                atomic_write_json(STATE, state)
                print(f"    {cat}/{seed}: {sum(1 for r in st['rows'] if r.get('seed') == seed)} fayl", flush=True)
    sources, cands = [], []
    for cat, seeds in COMMONS.items():
        st = sts[cat]
        st["done"] = not any(need(cat, s) for s in seeds)
        src = {"source_id": f"commons:{cat}", "kind": "commons", "name": "Wikimedia Commons: " + ", ".join(seeds),
               "revision": "per-file upload timestamp + SHA-1", "url": API, "license": "per file (extmetadata)",
               "category": cat, "family": "per file (Artist / uploader)", "candidates": len(st["rows"]),
               "rejected": json.dumps(st["rejected"], sort_keys=True),
               "status": "ok" if st["done"] else f"partial: {stop_reason or 'targets not reached'}"}
        print(f"  {'✓' if st['done'] else '…'} Commons {cat}: {len(st['rows'])} nomzod ({src['status']})", flush=True)
        sources.append(src)
        cands += st["rows"]
    atomic_write_json(STATE, state)
    return sources, cands


# --------------------------------------------------------------------------- local corpus

def fetch_local(directory: Path, meta_csv: Path) -> tuple[list, list]:
    rows = []
    with open(meta_csv, newline="", encoding="utf-8") as f:
        for m in csv.DictReader(f):
            p = (directory / m["path"]).resolve()
            b = p.read_bytes()
            h = store(b)
            rows.append({"sha256": h, "size": len(b), "category": m["category"], "family": m["family"],
                         "lineage": m.get("lineage", ""), "creator": m.get("creator", m["family"]),
                         "license": m.get("license", ""), "source_id": "local:" + m.get("source", directory.name),
                         "revision": sha256(b), "url": p.as_uri(), "path": m["path"], "date": m.get("date", ""),
                         "title": Path(m["path"]).stem})
    src = [{"source_id": "local:" + directory.name, "kind": "local", "name": str(directory), "status": "ok",
            "candidates": len(rows)}]
    return src, rows


CAND_COLS = ["sha256", "size", "category", "family", "lineage", "creator", "license", "source_id", "revision", "url",
             "path", "date", "title", "seed", "upload_date", "original_date"]
SRC_COLS = ["source_id", "kind", "name", "revision", "published", "url", "archive_sha256", "integrity", "license",
            "category", "family", "lineage", "available_files", "candidates", "rejected", "status"]


def write_csv(path: Path, rows: list[dict], cols: list[str]) -> None:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    atomic_write_text(path, buf.getvalue())


def main(argv: list[str]) -> int:
    cfg = study_config()
    max_bytes = int(cfg["corpus"]["max_file_bytes"])
    FILES.mkdir(parents=True, exist_ok=True)
    if len(argv) >= 2 and argv[1] == "local":
        s, c = fetch_local(Path(argv[2]), Path(argv[3]))
    else:
        global COMMONS_TIME_BUDGET_S
        only = {"npm", "github", "commons"}
        if "--only" in argv:
            only = set(argv[argv.index("--only") + 1].split(","))
        if "--budget" in argv:
            COMMONS_TIME_BUDGET_S = float(argv[argv.index("--budget") + 1])
        global STATE
        legacy = read_json(CACHE / "fetch_state.json", {}) or {}
        http = Http()
        s, c = [], []
        for kind, label, fn in (("npm", "npm manbalari…", fetch_npm), ("github", "GitHub manbalari…", fetch_github),
                                ("commons", "Wikimedia Commons…", fetch_commons)):
            # one state file per source kind, so kinds can be fetched by separate processes
            STATE = CACHE / f"fetch_state_{kind}.json"
            state = read_json(STATE)
            if state is None:
                state = {k: v for k, v in legacy.items() if k.startswith(kind + ":")}
                atomic_write_json(STATE, state)
            if kind in only:
                print(label, flush=True)
                si, ci = fn(http, state, max_bytes)
            else:  # offline: reuse what an earlier run stored (no network)
                si, ci = [], []
                for k, v in state.items():
                    if k.startswith(kind + ":"):
                        if kind == "commons":
                            ci += v.get("rows", [])
                            si.append({"source_id": k, "kind": "commons", "candidates": len(v.get("rows", [])),
                                       "status": "ok" if v.get("done") else "partial: resumable",
                                       "rejected": json.dumps(v.get("rejected", {}), sort_keys=True)})
                        else:
                            si.append(v["source"])
                            ci += v.get("candidates", [])
            s += si
            c += ci
    if argv[1:2] != ["local"] and "--only" in argv:
        print("(qisman ishga tushirish: candidates.csv barcha turlarning saqlangan holatidan yig'ildi)", flush=True)
    write_csv(SOURCES_CSV, s, SRC_COLS)
    write_csv(CANDIDATES_CSV, c, CAND_COLS)
    print(f"manbalar: {len(s)}, nomzod fayllar: {len(c)} → {CANDIDATES_CSV}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
