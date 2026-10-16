#!/usr/bin/env python3
"""Regenerates the dynamic parts of the profile README from live GitHub data.

Outputs
  assets/tech-stack.svg   animated icon grid (icons detected from your repos)
  assets/languages.svg    animated language bars (bytes across your repos)
  assets/stats.svg        animated stat cards
  assets/social-*.svg     animated social icons
  README.md               <!--OSS:START--> ... <!--OSS:END--> block (merged PRs)

Env: GH_USER (default below), GITHUB_TOKEN (optional locally, provided in Actions).
"""
from __future__ import annotations

import base64
import json
import math
import os
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from urllib.request import Request, urlopen

USER = os.environ.get("GH_USER", "Sneha72893")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
README = ROOT / "README.md"
MAX_REPOS = 40
DEVICON = "https://raw.githubusercontent.com/devicons/devicon/master/icons/"

# ----------------------------------------------------------------------------
# Icon catalog: slug -> (label, category, devicon folder, render as white silhouette)
# ----------------------------------------------------------------------------
CATALOG = {
    "javascript": ("JavaScript", "Languages", "javascript", False),
    "typescript": ("TypeScript", "Languages", "typescript", False),
    "python":     ("Python",     "Languages", "python",     False),
    "java":       ("Java",       "Languages", "java",       False),
    "go":         ("Go",         "Languages", "go",         False),
    "c":          ("C",          "Languages", "c",          False),
    "cplusplus":  ("C++",        "Languages", "cplusplus",  False),
    "rust":       ("Rust",       "Languages", "rust",       True),
    "php":        ("PHP",        "Languages", "php",        False),
    "kotlin":     ("Kotlin",     "Languages", "kotlin",     False),
    "dart":       ("Dart",       "Languages", "dart",       False),
    "bash":       ("Bash",       "Languages", "bash",       False),
    "react":      ("React",      "Frontend",  "react",      False),
    "vuejs":      ("Vue.js",     "Frontend",  "vuejs",      False),
    "nextjs":     ("Next.js",    "Frontend",  "nextjs",     False),
    "html5":      ("HTML5",      "Frontend",  "html5",      False),
    "css3":       ("CSS3",       "Frontend",  "css3",       False),
    "tailwindcss":("Tailwind",   "Frontend",  "tailwindcss",False),
    "bootstrap":  ("Bootstrap",  "Frontend",  "bootstrap",  False),
    "vitejs":     ("Vite",       "Frontend",  "vitejs",     False),
    "nodejs":     ("Node.js",    "Backend",   "nodejs",     False),
    "express":    ("Express",    "Backend",   "express",    True),
    "django":     ("Django",     "Backend",   "django",     True),
    "flask":      ("Flask",      "Backend",   "flask",      True),
    "fastapi":    ("FastAPI",    "Backend",   "fastapi",    False),
    "socketio":   ("Socket.io",  "Backend",   "socketio",   True),
    "graphql":    ("GraphQL",    "Backend",   "graphql",    False),
    "numpy":      ("NumPy",      "Data Science & ML", "numpy",       False),
    "pandas":     ("Pandas",     "Data Science & ML", "pandas",      True),
    "scikitlearn":("Scikit-Learn","Data Science & ML","scikitlearn", False),
    "matplotlib": ("Matplotlib", "Data Science & ML", "matplotlib",  False),
    "seaborn":    ("Seaborn",    "Data Science & ML", "seaborn",     False),
    "tensorflow": ("TensorFlow", "Data Science & ML", "tensorflow",  False),
    "pytorch":    ("PyTorch",    "Data Science & ML", "pytorch",     False),
    "jupyter":    ("Jupyter",    "Data Science & ML", "jupyter",     False),
    "mysql":      ("MySQL",      "Database",  "mysql",      False),
    "postgresql": ("PostgreSQL", "Database",  "postgresql", False),
    "mongodb":    ("MongoDB",    "Database",  "mongodb",    False),
    "redis":      ("Redis",      "Database",  "redis",      False),
    "sqlite":     ("SQLite",     "Database",  "sqlite",     False),
    "firebase":   ("Firebase",   "Database",  "firebase",   False),
    "prisma":     ("Prisma",     "Database",  "prisma",     True),
    "docker":     ("Docker",     "DevOps & Cloud", "docker",     False),
    "amazonwebservices": ("AWS", "DevOps & Cloud", "amazonwebservices", False),
    "googlecloud":("Google Cloud","DevOps & Cloud","googlecloud",False),
    "azure":      ("Azure",      "DevOps & Cloud", "azure",      False),
    "jenkins":    ("Jenkins",    "DevOps & Cloud", "jenkins",    False),
    "kubernetes": ("Kubernetes", "DevOps & Cloud", "kubernetes", False),
    "linux":      ("Linux",      "DevOps & Cloud", "linux",      False),
    "git":        ("Git",        "Tools",     "git",        False),
    "github":     ("GitHub",     "Tools",     "github",     True),
    "vscode":     ("VS Code",    "Tools",     "vscode",     False),
    "figma":      ("Figma",      "Tools",     "figma",      False),
    "postman":    ("Postman",    "Tools",     "postman",    False),
}
CATEGORIES = ["Languages", "Frontend", "Backend", "Data Science & ML", "Database", "DevOps & Cloud", "Tools"]

# Always shown (Sneha's toolbox). Detected extras are added on top.
PINNED = [
    "javascript", "typescript", "python", "go",
    "react", "vuejs", "nextjs", "html5", "css3", "tailwindcss", "bootstrap",
    "nodejs", "express", "django", "flask",
    "mysql", "postgresql", "mongodb", "redis", "sqlite",
    "docker", "amazonwebservices", "googlecloud", "azure", "jenkins",
    "git", "vscode", "figma", "postman", "vitejs",
]

LANG_TO_SLUG = {
    "JavaScript": "javascript", "TypeScript": "typescript", "Python": "python", "Java": "java",
    "Go": "go", "C": "c", "C++": "cplusplus", "Rust": "rust", "PHP": "php", "Kotlin": "kotlin",
    "Dart": "dart", "HTML": "html5", "CSS": "css3", "Shell": "bash", "Dockerfile": "docker",
    "Jupyter Notebook": "jupyter",
}
NPM_MAP = {
    "react": "react", "vue": "vuejs", "next": "nextjs", "express": "express",
    "tailwindcss": "tailwindcss", "vite": "vitejs", "bootstrap": "bootstrap",
    "mongoose": "mongodb", "mongodb": "mongodb", "mysql": "mysql", "mysql2": "mysql",
    "pg": "postgresql", "redis": "redis", "ioredis": "redis",
    "typescript": "typescript", "firebase": "firebase", "@prisma/client": "prisma",
    "socket.io": "socketio", "graphql": "graphql",
}
PY_MAP = {
    "django": "django", "flask": "flask", "fastapi": "fastapi", "pandas": "pandas", "numpy": "numpy",
    "scikit-learn": "scikitlearn", "sklearn": "scikitlearn", "matplotlib": "matplotlib",
    "seaborn": "seaborn", "tensorflow": "tensorflow", "torch": "pytorch", "psycopg2": "postgresql",
    "psycopg2-binary": "postgresql", "pymongo": "mongodb", "redis": "redis",
    "mysql-connector-python": "mysql", "pymysql": "mysql",
}
TOPIC_ALIAS = {
    "reactjs": "react", "node": "nodejs", "node-js": "nodejs", "golang": "go",
    "next-js": "nextjs", "mongo": "mongodb", "postgres": "postgresql", "k8s": "kubernetes",
    "tailwind": "tailwindcss", "sklearn": "scikitlearn", "machine-learning": None, "vite": "vitejs",
    "vuejs": "vuejs", "vue": "vuejs",
}
LANG_COLORS = {
    "JavaScript": "#f1e05a", "TypeScript": "#3178c6", "Python": "#3572A5", "Java": "#b07219",
    "Go": "#00ADD8", "HTML": "#e34c26", "CSS": "#563d7c", "Shell": "#89e051", "C++": "#f34b7d",
    "C": "#aaaaaa", "Jupyter Notebook": "#DA5B0B", "Rust": "#dea584", "PHP": "#4F5D95",
    "Kotlin": "#A97BFF", "Dart": "#00B4AB", "Dockerfile": "#384d54", "SCSS": "#c6538c",
}

# Pink / black / white palette
PINK       = "#FF8FAB"
PINK_LIGHT = "#FFADBD"
PURPLE     = "#9B5DE5"
BG         = "#0d1117"
BG_TILE    = "#161b22"
STROKE     = "#30363d"
TEXT_MUTED = "#8b949e"
TEXT_BODY  = "#c9d1d9"

# ----------------------------------------------------------------------------
# HTTP helpers
# ----------------------------------------------------------------------------

def http(url: str, binary: bool = False):
    headers = {"User-Agent": "profile-readme-updater", "Accept": "application/vnd.github+json"}
    if TOKEN and url.startswith("https://api.github.com"):
        headers["Authorization"] = f"Bearer {TOKEN}"
    try:
        with urlopen(Request(url, headers=headers), timeout=20) as r:
            data = r.read()
            return data if binary else data.decode("utf-8", "replace")
    except Exception:
        return None


def api(path: str):
    raw = http("https://api.github.com" + path)
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


# ----------------------------------------------------------------------------
# Data collection
# ----------------------------------------------------------------------------

def fetch_repos() -> list[dict]:
    out: list[dict] = []
    for page in range(1, 4):
        chunk = api(f"/users/{USER}/repos?per_page=100&type=owner&sort=pushed&page={page}")
        if not chunk:
            break
        out += chunk
        if len(chunk) < 100:
            break
    return [r for r in out if not r.get("fork") and not r.get("archived")]


def repo_signals(repo: dict) -> tuple[set[str], dict]:
    """Return (slugs detected in repo, language-bytes dict)."""
    name = repo["name"]
    slugs: set[str] = set()
    langs = api(f"/repos/{USER}/{name}/languages") or {}
    for lang in langs:
        if lang in LANG_TO_SLUG:
            slugs.add(LANG_TO_SLUG[lang])
    for topic in repo.get("topics") or []:
        t = TOPIC_ALIAS.get(topic, topic)
        if t in CATALOG:
            slugs.add(t)

    base = f"https://raw.githubusercontent.com/{USER}/{name}/HEAD/"
    for sub in ("", "client/", "frontend/", "server/", "backend/", "web/"):
        txt = http(base + sub + "package.json")
        if not txt:
            continue
        try:
            pkg = json.loads(txt)
        except ValueError:
            continue
        slugs.add("nodejs")
        for dep in {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}:
            if dep in NPM_MAP:
                slugs.add(NPM_MAP[dep])
    for sub in ("", "backend/", "server/", "api/"):
        txt = http(base + sub + "requirements.txt")
        if not txt:
            continue
        for line in txt.lower().splitlines():
            pkg = re.split(r"[=<>~!\[;@ ]", line.strip())[0]
            if pkg in PY_MAP:
                slugs.add(PY_MAP[pkg])
    return slugs, langs


def merged_prs() -> tuple[int, list[dict]]:
    q = f"author:{USER}+type:pr+is:merged+-user:{USER}"
    data = api(f"/search/issues?q={q}&sort=updated&order=desc&per_page=30") or {}
    return data.get("total_count", 0), data.get("items", [])


def open_prs_count() -> int:
    data = api(f"/search/issues?q=author:{USER}+type:pr+is:open+-user:{USER}&per_page=1") or {}
    return data.get("total_count", 0)


def contributed_repo_slugs(full_names: list[str]) -> Counter:
    c: Counter = Counter()
    for full in full_names[:10]:
        info = api(f"/repos/{full}") or {}
        for topic in info.get("topics") or []:
            t = TOPIC_ALIAS.get(topic, topic)
            if t in CATALOG:
                c[t] += 1
        langs = api(f"/repos/{full}/languages") or {}
        for lang in sorted(langs, key=langs.get, reverse=True)[:3]:
            if lang in LANG_TO_SLUG:
                c[LANG_TO_SLUG[lang]] += 1
    return c


# ----------------------------------------------------------------------------
# SVG building blocks  (pink / black / white theme)
# ----------------------------------------------------------------------------
_icon_cache: dict[str, str | None] = {}


def data_uri(raw: bytes) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(raw).decode()


def icon_uri(slug: str) -> str | None:
    if slug in _icon_cache:
        return _icon_cache[slug]
    folder = CATALOG[slug][2]
    uri = None
    for variant in ("original", "plain"):
        raw = http(f"{DEVICON}{folder}/{folder}-{variant}.svg", binary=True)
        if raw and b"<svg" in raw[:2000]:
            uri = data_uri(raw)
            break
    _icon_cache[slug] = uri
    return uri


THEME_CSS = f"""
text{{font-family:'Fira Code','SFMono-Regular',Consolas,'Liberation Mono',monospace}}
.panel{{fill:{BG};stroke:{PINK};stroke-opacity:.35}}
.title{{fill:{PINK};font-size:15px;font-weight:600}}
.cat{{fill:{PINK};font-size:12.5px;font-weight:600}}
.muted{{fill:{TEXT_MUTED};font-size:10.5px}}
.lbl{{fill:{TEXT_MUTED};font-size:10.5px;text-anchor:middle}}
.tile{{fill:{BG_TILE};stroke:{STROKE}}}
.tile.live{{stroke:{PINK};animation:glow 2.4s ease-in-out infinite alternate}}
.dot{{fill:{PINK_LIGHT};animation:pulse 1.6s ease-in-out infinite}}
.cursor{{fill:{PINK};animation:blink 1s steps(1) infinite}}
.enter{{opacity:0;animation:enter .6s ease-out forwards}}
.float{{animation:float 3.2s ease-in-out infinite}}
.white{{filter:brightness(0) invert(1)}}
.big{{fill:{PINK};font-size:30px;font-weight:700}}
.card{{fill:{BG_TILE};stroke:{PINK};stroke-opacity:.4;animation:glow 3s ease-in-out infinite alternate}}
.sublbl{{fill:{TEXT_BODY};font-size:11px;text-anchor:middle}}
@keyframes enter{{from{{opacity:0;transform:translateY(12px)}}to{{opacity:1;transform:none}}}}
@keyframes float{{0%,100%{{transform:translateY(0)}}50%{{transform:translateY(-5px)}}}}
@keyframes glow{{from{{stroke-opacity:.3}}to{{stroke-opacity:1}}}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.2}}}}
@keyframes blink{{0%,49%{{opacity:1}}50%,100%{{opacity:0}}}}
@media (prefers-reduced-motion:reduce){{*{{animation:none!important;opacity:1!important}}}}
"""


def svg_doc(w: int, h: int, body: str, label: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
        f'role="img" aria-label="{escape(label)}"><style>{THEME_CSS}</style>'
        f'<rect class="panel" x="0.5" y="0.5" width="{w-1}" height="{h-1}" rx="14"/>{body}</svg>'
    )


def tile(slug: str, x: int, y: int, idx: int, repos_using: int) -> str:
    label, _, _, white = CATALOG[slug]
    delay = (idx % 14) * 0.1
    live = repos_using > 0
    uri = icon_uri(slug)
    if uri:
        cls = ' class="white"' if white else ""
        glyph = f'<image href="{uri}" x="{x+12}" y="{y+12}" width="32" height="32"{cls}/>'
    else:
        glyph = f'<text x="{x+28}" y="{y+33}" text-anchor="middle" class="cat">{escape(label[:2])}</text>'
    dot = f'<circle class="dot" cx="{x+50}" cy="{y+6}" r="3.5"/>' if live else ""
    tip = f"{label} Â· {repos_using} repo{'s' if repos_using != 1 else ''}" if live else label
    return (
        f'<g class="enter" style="animation-delay:{delay:.1f}s"><g class="float" style="animation-delay:{delay:.1f}s">'
        f'<title>{escape(tip)}</title>'
        f'<rect class="tile{" live" if live else ""}" x="{x}" y="{y}" width="56" height="56" rx="12"/>'
        f'{glyph}{dot}<text class="lbl" x="{x+28}" y="{y+72}">{escape(label)}</text></g></g>'
    )


def build_tech_svg(slugs: list[str], scores: Counter) -> str:
    W, PAD, T, GAP, ROW = 800, 28, 56, 18, 56 + 34
    cols = (W - 2 * PAD + GAP) // (T + GAP)
    parts = [
        f'<text class="title" x="{PAD}" y="34">$ ls ~/stack<tspan class="cursor"> â–Œ</tspan></text>',
        f'<circle class="dot" cx="{W-175}" cy="30" r="3.5"/>'
        f'<text class="muted" x="{W-165}" y="34">used in my repos</text>',
    ]
    y, idx = 62, 0
    for cat in CATEGORIES:
        items = [s for s in slugs if CATALOG[s][1] == cat]
        if not items:
            continue
        parts.append(f'<text class="cat" x="{PAD}" y="{y}">// {escape(cat)}</text>')
        y += 14
        for i, slug in enumerate(items):
            r, c = divmod(i, cols)
            parts.append(tile(slug, PAD + c * (T + GAP), y + r * ROW, idx, scores.get(slug, 0)))
            idx += 1
        y += math.ceil(len(items) / cols) * ROW + 14
    return svg_doc(W, y + 6, "".join(parts), "Animated tech stack generated from my repositories")


def build_languages_svg(lang_bytes: Counter) -> str:
    W, PAD = 800, 28
    total = sum(lang_bytes.values()) or 1
    top = lang_bytes.most_common(6)
    parts = [f'<text class="title" x="{PAD}" y="34">$ cloc ~/repos<tspan class="cursor"> â–Œ</tspan></text>']
    y = 62
    bar_x, bar_w = 190, 480
    for i, (lang, b) in enumerate(top):
        pct = b / total * 100
        w = max(4, bar_w * pct / 100 * (100 / max(top[0][1] / total * 100, 1)) * 0.95)
        color = LANG_COLORS.get(lang, PINK)
        parts.append(
            f'<g class="enter" style="animation-delay:{i*0.12:.2f}s">'
            f'<text class="cat" x="{PAD}" y="{y+13}" style="fill:{TEXT_BODY}">{escape(lang)}</text>'
            f'<rect x="{bar_x}" y="{y}" width="{bar_w}" height="16" rx="8" fill="{BG_TILE}"/>'
            f'<rect x="{bar_x}" y="{y}" width="0" height="16" rx="8" fill="{color}">'
            f'<animate attributeName="width" from="0" to="{w:.1f}" dur="1.2s" begin="{i*0.12:.2f}s" fill="freeze" '
            f'calcMode="spline" keySplines="0.2 0.8 0.2 1" keyTimes="0;1"/></rect>'
            f'<text class="cat" x="{bar_x+bar_w+16}" y="{y+13}" style="fill:{color}">{pct:.1f}%</text></g>'
        )
        y += 30
    return svg_doc(W, y + 12, "".join(parts), "Most used languages across my repositories")


def build_stats_svg(stats: list[tuple[str, str]]) -> str:
    W, H, PAD, GAP = 800, 130, 20, 16
    n = len(stats)
    cw = (W - 2 * PAD - GAP * (n - 1)) / n
    parts = []
    for i, (value, label) in enumerate(stats):
        x = PAD + i * (cw + GAP)
        parts.append(
            f'<g class="enter" style="animation-delay:{i*0.15:.2f}s">'
            f'<rect class="card" x="{x:.1f}" y="22" width="{cw:.1f}" height="86" rx="12" style="animation-delay:{i*0.4:.1f}s"/>'
            f'<text class="big" x="{x+cw/2:.1f}" y="68" text-anchor="middle">{escape(value)}</text>'
            f'<text class="lbl" x="{x+cw/2:.1f}" y="92">{escape(label)}</text></g>'
        )
    return svg_doc(W, H, "".join(parts), "GitHub stats")


def build_social_svg(file_name: str, delay: float) -> str | None:
    raw = http(f"https://raw.githubusercontent.com/gauravghongde/social-icons/master/SVG/Color/{file_name}", binary=True)
    if not raw:
        return None
    css = (
        "@keyframes hop{0%,100%{transform:translateY(0)}50%{transform:translateY(-6px)}}"
        f".i{{animation:hop 2.4s ease-in-out {delay}s infinite}}"
        "@media (prefers-reduced-motion:reduce){.i{animation:none}}"
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 72" width="64" height="72">'
        f'<style>{css}</style><image class="i" href="{data_uri(raw)}" x="8" y="12" width="48" height="48"/></svg>'
    )


# ----------------------------------------------------------------------------
# README block
# ----------------------------------------------------------------------------

def build_oss_markdown(total: int, items: list[dict]) -> str:
    by_repo: Counter = Counter()
    for it in items:
        by_repo[it["repository_url"].split("/repos/")[1]] += 1
    lines = ["#### ðŸ¤ Projects I've contributed to", ""]
    badges = []
    for repo, n in by_repo.most_common(8):
        badges.append(
            f'<a href="https://github.com/{repo}"><img alt="{repo}" '
            f'src="https://img.shields.io/github/stars/{repo}?style=for-the-badge&logo=github&label={repo.replace("-", "--")}&color=FF8FAB&labelColor=000000" /></a>'
        )
    if badges:
        lines += ['<p align="center">', "  " + "\n  ".join(badges), "</p>", ""]
    lines += [f"#### âœ… Recently merged pull requests ({total} merged in total)", "", "| Project | Pull request | Merged |", "|---|---|---|"]
    for it in items[:10]:
        repo = it["repository_url"].split("/repos/")[1]
        title = it["title"].replace("|", "\\|")
        title = title if len(title) <= 70 else title[:67] + "..."
        merged = ((it.get("pull_request") or {}).get("merged_at") or it.get("closed_at") or "")[:10]
        lines.append(f"| [{repo}](https://github.com/{repo}) | [#{it['number']} {title}]({it['html_url']}) | {merged} |")
    if not items:
        lines.append("| _Nothing yet, first PR coming soon_ | | |")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines += ["", f"<sub>Auto-updated {stamp}</sub>"]
    return "\n".join(lines)


def replace_block(text: str, start: str, end: str, content: str) -> str:
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    return pattern.sub(lambda _: f"{start}\n{content}\n{end}", text)


# ----------------------------------------------------------------------------
def main() -> int:
    repos = fetch_repos()
    if not repos:
        print("No repos returned (rate limit or network). Leaving files untouched.", file=sys.stderr)
        return 1
    ASSETS.mkdir(exist_ok=True)
    scan = repos[:MAX_REPOS]

    scores: Counter = Counter()
    lang_bytes: Counter = Counter()
    with ThreadPoolExecutor(max_workers=8) as pool:
        for slugs, langs in pool.map(repo_signals, scan):
            scores.update(slugs)
            lang_bytes.update(langs)

    total_merged, items = merged_prs()
    ext_repos = list(dict.fromkeys(it["repository_url"].split("/repos/")[1] for it in items))
    scores.update(contributed_repo_slugs(ext_repos))

    pool_slugs = set(PINNED) | {s for s, v in scores.items() if v > 0 and s in CATALOG}
    ordered = sorted(
        pool_slugs,
        key=lambda s: (-scores.get(s, 0), PINNED.index(s) if s in PINNED else 99),
    )
    (ASSETS / "tech-stack.svg").write_text(build_tech_svg(ordered, scores), encoding="utf-8")
    (ASSETS / "languages.svg").write_text(build_languages_svg(lang_bytes), encoding="utf-8")

    stars = sum(r.get("stargazers_count", 0) for r in repos)
    stats = [
        (str(total_merged), "merged PRs (open source)"),
        (str(open_prs_count()), "open PRs"),
        (str(len(repos)), "public repos"),
        (str(stars), "stars earned"),
    ]
    (ASSETS / "stats.svg").write_text(build_stats_svg(stats), encoding="utf-8")

    # LinkedIn and Gmail only (no Twitter in source data)
    for i, (fname, out) in enumerate([("LinkedIN.svg", "linkedin"), ("Gmail.svg", "gmail")]):
        svg = build_social_svg(fname, i * 0.3)
        if svg:
            (ASSETS / f"social-{out}.svg").write_text(svg, encoding="utf-8")

    if README.exists():
        text = README.read_text(encoding="utf-8")
        text = replace_block(text, "<!--OSS:START-->", "<!--OSS:END-->", build_oss_markdown(total_merged, items))
        README.write_text(text, encoding="utf-8")

    print(f"repos={len(repos)} merged_ext={total_merged} icons={len(ordered)} detected={sorted(s for s,v in scores.items() if v>0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
