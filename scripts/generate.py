#!/usr/bin/env python3
"""Generate animated universe-themed GitHub profile SVGs and README.md.

Zero external dependencies (Python 3 stdlib only).
Uses GITHUB_TOKEN + GitHub GraphQL API in CI for live telemetry, or --preview
for deterministic offline starter data before the first workflow run.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import random
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = ROOT / "profile.json"
ASSETS_DIR = ROOT / "assets"
README_PATH = ROOT / "README.md"

FONT_SANS = "'Segoe UI', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Arial, sans-serif"
FONT_MONO = "'Cascadia Code', 'JetBrains Mono', 'Fira Code', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"

# Verified >= 4.5:1 text contrast on deep space (#050816 / #0E1533)
C_BG_TOP = "#050816"
C_BG_MID = "#090E26"
C_BG_BOT = "#0D1333"
C_CARD = "#0F1738"
C_CARD_BORDER = "#2A3975"
C_TEXT_PRI = "#F8FAFC"
C_TEXT_SEC = "#CBD5E1"
C_TEXT_MUTED = "#94A3B8"
C_CYAN = "#38BDF8"
C_VIOLET = "#A78BFA"
C_MAGENTA = "#F472B6"
C_AMBER = "#FBBF24"
C_EMERALD = "#34D399"

LANG_COLORS = {
    "TypeScript": "#3178C6",
    "JavaScript": "#F7DF1E",
    "Python": "#3572A5",
    "Rust": "#DEA584",
    "Go": "#00ADD8",
    "C++": "#F34B7D",
    "C#": "#178600",
    "Java": "#B07219",
    "HTML": "#E34C26",
    "CSS": "#663399",
    "Shell": "#89E051",
    "Dart": "#00B4AB",
    "Swift": "#F05138",
    "Kotlin": "#A97BFF",
    "Vue": "#41B883",
    "Svelte": "#FF3E00",
}

GRAPHQL_QUERY = """
query($login: String!) {
  user(login: $login) {
    name
    bio
    location
    followers { totalCount }
    repositories(first: 100, ownerAffiliations: OWNER, privacy: PUBLIC, isFork: false, orderBy: {field: STARGAZERS, direction: DESC}) {
      totalCount
      nodes {
        name
        description
        url
        stargazerCount
        forkCount
        updatedAt
        primaryLanguage { name color }
        languages(first: 8, orderBy: {field: SIZE, direction: DESC}) {
          edges {
            size
            node { name color }
          }
        }
      }
    }
    pinnedItems(first: 6, types: REPOSITORY) {
      nodes {
        ... on Repository {
          name
          description
          url
          stargazerCount
          forkCount
          primaryLanguage { name color }
        }
      }
    }
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      totalPullRequestReviewContributions
      restrictedContributionsCount
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            contributionCount
            weekday
          }
        }
      }
    }
  }
}
"""


def esc(text: Any) -> str:
    return escape(str(text or ""), {'"': "&quot;", "'": "&apos;"})


def fmt_num(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 10_000:
        return f"{n / 1_000:.1f}k"
    return f"{n:,}"


def wrap_text(text: str, max_chars: int, max_lines: int = 2) -> list[str]:
    words = (text or "").split()
    if not words:
        return []
    lines: list[str] = []
    cur = ""
    for w in words:
        cand = f"{cur} {w}".strip()
        if len(cand) <= max_chars:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            cur = w[: max_chars - 1] + "…" if len(w) > max_chars else w
            if len(lines) == max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    # Append ellipsis if original text was truncated
    joined = " ".join(lines)
    if len(joined) < len(" ".join(words)) and lines:
        last = lines[-1]
        if not last.endswith("…"):
            lines[-1] = (last[: max_chars - 1].rstrip() + "…") if len(last) >= max_chars else (last + "…")
    return lines[:max_lines]


def compute_streaks(days: list[dict[str, Any]]) -> tuple[int, int]:
    """Return (current_streak, longest_streak) from chronological contribution days."""
    if not days:
        return 0, 0
    ordered = sorted(days, key=lambda d: d["date"])
    longest = 0
    run = 0
    for d in ordered:
        if d["contributionCount"] > 0:
            run += 1
            if run > longest:
                longest = run
        else:
            run = 0

    # Current streak allows today to still be 0 if yesterday was active
    idx = len(ordered) - 1
    if idx >= 0 and ordered[idx]["contributionCount"] == 0:
        idx -= 1
    current = 0
    while idx >= 0 and ordered[idx]["contributionCount"] > 0:
        current += 1
        idx -= 1
    return current, longest


def orbit_keyframes(name: str, cx: float, cy: float, rx: float, ry: float, tilt_deg: float, start_deg: float = 0.0, steps: int = 24) -> str:
    """Generate smooth 3D-perspective elliptical orbit CSS keyframes keeping the orbiting body round."""
    tilt = math.radians(tilt_deg)
    ct, st = math.cos(tilt), math.sin(tilt)
    frames = []
    for i in range(steps + 1):
        pct = (i / steps) * 100.0
        angle = math.radians(start_deg + (i / steps) * 360.0)
        ex = rx * math.cos(angle)
        ey = ry * math.sin(angle)
        x = cx + ex * ct - ey * st
        y = cy + ex * st + ey * ct
        depth = math.sin(angle)  # +1 in front, -1 behind
        scale = 1.0 + 0.16 * depth
        opacity = 0.72 + 0.28 * ((depth + 1.0) / 2.0)
        frames.append(
            f"  {pct:.2f}% {{ transform: translate({x:.1f}px, {y:.1f}px) scale({scale:.3f}); opacity: {opacity:.2f}; }}"
        )
    return f"@keyframes {name} {{\n" + "\n".join(frames) + "\n}"


def starfield_svg(width: int, height: int, count: int, seed: int) -> str:
    """Deterministic twinkling multi-layer starfield."""
    rng = random.Random(seed)
    palette = ["#FFFFFF", "#E0F2FE", "#DDD6FE", "#BAE6FD", "#FBCFE8", "#FDE68A"]
    parts = []
    for i in range(count):
        x = rng.uniform(14, width - 14)
        y = rng.uniform(14, height - 14)
        r = rng.choices([0.7, 1.0, 1.4, 1.9], weights=[45, 32, 16, 7])[0]
        color = rng.choice(palette)
        cls = f"tw{(i % 3) + 1}"
        delay = -rng.uniform(0, 5.5)
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{color}" '
            f'class="{cls}" style="animation-delay:{delay:.2f}s"/>'
        )
    return "\n    ".join(parts)


def base_styles(extra_css: str = "") -> str:
    return f"""
    .sans {{ font-family: {FONT_SANS}; }}
    .mono {{ font-family: {FONT_MONO}; }}
    @keyframes twinkleA {{ 0%, 100% {{ opacity: 0.25; }} 50% {{ opacity: 1; }} }}
    @keyframes twinkleB {{ 0%, 100% {{ opacity: 0.9; }} 50% {{ opacity: 0.2; }} }}
    @keyframes twinkleC {{ 0%, 100% {{ opacity: 0.45; }} 40% {{ opacity: 0.95; }} 75% {{ opacity: 0.15; }} }}
    @keyframes nebulaBreathe {{ 0%, 100% {{ opacity: 0.42; }} 50% {{ opacity: 0.68; }} }}
    @keyframes pulseDot {{ 0%, 100% {{ opacity: 1; transform: scale(1); }} 50% {{ opacity: 0.45; transform: scale(0.82); }} }}
    @keyframes pulseRing {{ 0% {{ opacity: 0.75; transform: scale(0.9); }} 100% {{ opacity: 0; transform: scale(2.2); }} }}
    @keyframes spinSlow {{ from {{ transform: rotate(0deg); }} to {{ transform: rotate(360deg); }} }}
    @keyframes spinRev {{ from {{ transform: rotate(360deg); }} to {{ transform: rotate(0deg); }} }}
    @keyframes floatY {{ 0%, 100% {{ transform: translateY(0px); }} 50% {{ transform: translateY(-5px); }} }}
    @keyframes shimmer {{ 0% {{ transform: translateX(-180px); opacity: 0; }} 20% {{ opacity: 0.55; }} 80% {{ opacity: 0.55; }} 100% {{ transform: translateX(880px); opacity: 0; }} }}
    @keyframes blink {{ 0%, 49% {{ opacity: 1; }} 50%, 100% {{ opacity: 0; }} }}
    .tw1 {{ animation: twinkleA 3.4s ease-in-out infinite; }}
    .tw2 {{ animation: twinkleB 4.6s ease-in-out infinite; }}
    .tw3 {{ animation: twinkleC 5.8s ease-in-out infinite; }}
    .nebula {{ animation: nebulaBreathe 9s ease-in-out infinite; }}
    .spin-slow {{ animation: spinSlow 44s linear infinite; }}
    .spin-med {{ animation: spinSlow 24s linear infinite; }}
    .spin-rev {{ animation: spinRev 34s linear infinite; }}
    .float-y {{ animation: floatY 6.5s ease-in-out infinite; }}
    .blink {{ animation: blink 1.1s steps(1, end) infinite; }}
    {extra_css}
    @media (prefers-reduced-motion: reduce) {{
      * {{ animation: none !important; transition: none !important; }}
    }}
    """


def fetch_github_stats(username: str, token: str) -> dict[str, Any]:
    payload = json.dumps({"query": GRAPHQL_QUERY, "variables": {"login": username}}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "universe-github-profile-generator",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if data.get("errors"):
        raise RuntimeError(f"GitHub GraphQL error: {data['errors']}")
    user = (data.get("data") or {}).get("user")
    if not user:
        raise RuntimeError(f"GitHub user '{username}' not found")

    cc = user["contributionsCollection"]
    cal = cc["contributionCalendar"]
    weeks = cal["weeks"]
    flat_days = [d for w in weeks for d in w["contributionDays"]]
    cur_streak, best_streak = compute_streaks(flat_days)

    repos = [r for r in (user["repositories"]["nodes"] or []) if r]
    total_stars = sum(r.get("stargazerCount", 0) for r in repos)

    lang_totals: dict[str, dict[str, Any]] = {}
    for r in repos:
        for edge in (r.get("languages") or {}).get("edges") or []:
            name = edge["node"]["name"]
            color = edge["node"].get("color") or LANG_COLORS.get(name, C_CYAN)
            lang_totals.setdefault(name, {"name": name, "color": color, "size": 0})
            lang_totals[name]["size"] += edge["size"]
    total_bytes = sum(v["size"] for v in lang_totals.values()) or 1
    top_langs = sorted(lang_totals.values(), key=lambda x: x["size"], reverse=True)[:6]
    for l in top_langs:
        l["pct"] = round((l["size"] / total_bytes) * 100.0, 1)

    pinned = [r for r in (user.get("pinnedItems") or {}).get("nodes") or [] if r]
    featured = pinned if pinned else repos[:4]

    return {
        "live": True,
        "updated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"),
        "commits": cc["totalCommitContributions"] + cc.get("restrictedContributionsCount", 0),
        "contributions": cal["totalContributions"],
        "prs": cc["totalPullRequestContributions"],
        "issues": cc["totalIssueContributions"],
        "reviews": cc["totalPullRequestReviewContributions"],
        "stars": total_stars,
        "repo_count": user["repositories"]["totalCount"],
        "followers": user["followers"]["totalCount"],
        "current_streak": cur_streak,
        "longest_streak": best_streak,
        "weeks": weeks,
        "top_languages": top_langs,
        "repositories": featured[:6],
    }


def preview_stats(profile: dict[str, Any]) -> dict[str, Any]:
    """Deterministic starter telemetry used offline before the first GitHub Action sync."""
    rng = random.Random(42)
    today = dt.date.today()
    # Build 52 complete weeks ending on today's week
    days_back = 52 * 7 + today.weekday()
    start = today - dt.timedelta(days=days_back)
    weeks = []
    flat = []
    cur = start
    while cur <= today:
        week_days = []
        for wd in range(7):
            if cur > today:
                break
            wave = 0.5 + 0.5 * math.sin(cur.timetuple().tm_yday / 18.0)
            roll = rng.random()
            if roll < 0.26:
                count = 0
            elif roll < 0.58:
                count = rng.randint(1, 3)
            elif roll < 0.84:
                count = int(rng.randint(4, 8) * (0.7 + 0.6 * wave))
            else:
                count = int(rng.randint(9, 16) * (0.8 + 0.5 * wave))
            # Keep recent 12 days active so preview streak looks alive
            if (today - cur).days <= 11:
                count = max(count, rng.randint(2, 9))
            day_obj = {"date": cur.isoformat(), "contributionCount": count, "weekday": wd}
            week_days.append(day_obj)
            flat.append(day_obj)
            cur += dt.timedelta(days=1)
        if week_days:
            weeks.append({"contributionDays": week_days})

    cur_streak, best_streak = compute_streaks(flat)
    total_contribs = sum(d["contributionCount"] for d in flat)
    uname = profile.get("username", "seishikun")

    stack_langs = []
    for grp in profile.get("tech_stack", []):
        if grp.get("category", "").lower() == "languages":
            stack_langs = grp.get("items", [])
            break
    base_langs = stack_langs[:5] if stack_langs else ["TypeScript", "Python", "JavaScript", "HTML", "CSS"]
    weights = [36.4, 27.8, 17.5, 11.2, 7.1]
    top_langs = [
        {"name": name, "color": LANG_COLORS.get(name, C_CYAN), "pct": weights[i]}
        for i, name in enumerate(base_langs[: len(weights)])
    ]

    default_repos = [
        {
            "name": uname,
            "description": "Animated universe-themed GitHub profile powered by self-updating SVG telemetry.",
            "url": f"https://github.com/{uname}/{uname}",
            "stargazerCount": 12,
            "forkCount": 3,
            "primaryLanguage": {"name": "Python", "color": "#3572A5"},
        },
        {
            "name": "nebula-ui",
            "description": "Accessible dark-first component kit with crisp motion tokens and zero runtime bloat.",
            "url": f"https://github.com/{uname}",
            "stargazerCount": 24,
            "forkCount": 5,
            "primaryLanguage": {"name": "TypeScript", "color": "#3178C6"},
        },
        {
            "name": "orbit-api",
            "description": "Lightweight full-stack starter API with typed schemas, caching, and CI checks.",
            "url": f"https://github.com/{uname}",
            "stargazerCount": 18,
            "forkCount": 4,
            "primaryLanguage": {"name": "JavaScript", "color": "#F7DF1E"},
        },
        {
            "name": "cosmos-cli",
            "description": "Fast developer automation CLI for scaffolding projects and inspecting git workflows.",
            "url": f"https://github.com/{uname}",
            "stargazerCount": 9,
            "forkCount": 2,
            "primaryLanguage": {"name": "Python", "color": "#3572A5"},
        },
    ]

    return {
        "live": False,
        "updated_at": today.isoformat(),
        "commits": int(total_contribs * 0.72),
        "contributions": total_contribs,
        "prs": 48,
        "issues": 26,
        "reviews": 31,
        "stars": sum(r["stargazerCount"] for r in default_repos),
        "repo_count": 14,
        "followers": 28,
        "current_streak": cur_streak,
        "longest_streak": best_streak,
        "weeks": weeks[-53:],
        "top_languages": top_langs,
        "repositories": profile.get("featured_repos") or default_repos,
    }


def render_hero(profile: dict[str, Any]) -> str:
    W, H = 850, 300
    raw_display = str(profile.get("display_name") or profile.get("username", "Developer"))
    raw_username = str(profile.get("username", "seishikun"))
    raw_tagline = str(profile.get("tagline", "Exploring the code cosmos"))
    raw_status = str(profile.get("status", "ONLINE · BUILDING"))
    display = esc(raw_display)
    username = esc(raw_username)
    tagline_lines = wrap_text(raw_tagline, 54, 1)
    tagline = esc(tagline_lines[0] if tagline_lines else raw_tagline)
    status = esc(raw_status)
    bio_lines = [esc(wrap_text(line, 64, 1)[0]) for line in (profile.get("bio") or [])[:2] if line.strip()]
    meta = profile.get("meta") or {}

    pills = []
    if meta.get("location"):
        pills.append(("pin", str(meta["location"]), C_CYAN))
    if meta.get("focus"):
        pills.append(("spark", str(meta["focus"]), C_VIOLET))
    if meta.get("email"):
        pills.append(("mail", str(meta["email"]), C_MAGENTA))

    pill_svg = []
    px = 44
    for kind, label, accent in pills[:3]:
        clean = esc(label)
        pw = max(92, len(label) * 6.9 + 34)
        if px + pw > 525:
            break
        if kind == "pin":
            icon = f'<path d="M{px+14} 245a4 4 0 1 1 8 0c0 3-4 6.5-4 6.5s-4-3.5-4-6.5zm4 1.3a1.4 1.4 0 1 0 0-2.8 1.4 1.4 0 0 0 0 2.8z" fill="{accent}"/>'
        elif kind == "spark":
            icon = f'<path d="M{px+18} 241l1.4 3.6 3.6 1.4-3.6 1.4-1.4 3.6-1.4-3.6-3.6-1.4 3.6-1.4z" fill="{accent}"/>'
        else:
            icon = f'<rect x="{px+12}" y="242" width="12" height="8.5" rx="1.5" fill="none" stroke="{accent}" stroke-width="1.4"/><path d="M{px+12.8} 243l5.2 3.8 5.2-3.8" fill="none" stroke="{accent}" stroke-width="1.3"/>'
        pill_svg.append(
            f'<g>'
            f'<rect x="{px}" y="233" width="{pw:.0f}" height="26" rx="13" fill="#0F1738" fill-opacity="0.88" stroke="{accent}" stroke-opacity="0.45" stroke-width="1"/>'
            f'{icon}'
            f'<text x="{px+30}" y="250" fill="{C_TEXT_SEC}" font-size="11.5" class="mono">{clean}</text>'
            f'</g>'
        )
        px += int(pw) + 10

    status_w = max(165, len(raw_status) * 6.8 + 38)
    handle_x = 44 + int(status_w) + 10
    handle_w = max(76, (len(raw_username) + 1) * 7.6 + 18)

    moon_orbit = orbit_keyframes("heroMoon", 718, 174, 88, 25, -18, start_deg=20, steps=24)
    mini_moon = orbit_keyframes("miniMoon", 568, 224, 28, 10, 14, start_deg=110, steps=20)
    extra_css = f"""
    {moon_orbit}
    {mini_moon}
    .hero-moon {{ animation: heroMoon 11s linear infinite; }}
    .mini-moon {{ animation: miniMoon 6.5s linear infinite; }}
    @keyframes meteor1 {{
      0%, 72% {{ transform: translate(0px, 0px); opacity: 0; }}
      75% {{ opacity: 1; }}
      88% {{ transform: translate(-250px, 110px); opacity: 0; }}
      100% {{ transform: translate(-250px, 110px); opacity: 0; }}
    }}
    @keyframes meteor2 {{
      0%, 40% {{ transform: translate(0px, 0px); opacity: 0; }}
      43% {{ opacity: 0.9; }}
      55% {{ transform: translate(-210px, 92px); opacity: 0; }}
      100% {{ transform: translate(-210px, 92px); opacity: 0; }}
    }}
    @keyframes meteor3 {{
      0%, 10% {{ transform: translate(0px, 0px); opacity: 0; }}
      13% {{ opacity: 0.85; }}
      24% {{ transform: translate(-180px, 78px); opacity: 0; }}
      100% {{ transform: translate(-180px, 78px); opacity: 0; }}
    }}
    .m1 {{ animation: meteor1 8.5s ease-out infinite; }}
    .m2 {{ animation: meteor2 11.5s ease-out infinite; }}
    .m3 {{ animation: meteor3 14s ease-out infinite; }}
    .status-pulse {{ animation: pulseRing 2.4s ease-out infinite; }}
    .status-dot {{ animation: pulseDot 2.4s ease-in-out infinite; }}
    """

    bio_markup = []
    for idx, line in enumerate(bio_lines):
        bio_markup.append(
            f'<text x="44" y="{176 + idx * 22}" fill="{C_TEXT_SEC}" font-size="13.5" class="sans">{line}</text>'
        )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="hero-title hero-desc">
  <title id="hero-title">{display} — Universe GitHub Profile</title>
  <desc id="hero-desc">{tagline}. Animated deep space header with rotating spiral galaxy, ringed planet, orbiting moons, twinkling starfield, and shooting stars.</desc>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{C_BG_TOP}"/>
      <stop offset="52%" stop-color="{C_BG_MID}"/>
      <stop offset="100%" stop-color="{C_BG_BOT}"/>
    </linearGradient>
    <linearGradient id="frameGrad" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{C_CYAN}" stop-opacity="0.65"/>
      <stop offset="50%" stop-color="{C_VIOLET}" stop-opacity="0.55"/>
      <stop offset="100%" stop-color="{C_MAGENTA}" stop-opacity="0.6"/>
    </linearGradient>
    <linearGradient id="titleGrad" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#F8FAFC"/>
      <stop offset="55%" stop-color="#7DD3FC"/>
      <stop offset="100%" stop-color="#C4B5FD"/>
    </linearGradient>
    <radialGradient id="nebulaViolet" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#7C3AED" stop-opacity="0.45"/>
      <stop offset="55%" stop-color="#4C1D95" stop-opacity="0.16"/>
      <stop offset="100%" stop-color="#4C1D95" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="nebulaCyan" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#0EA5E9" stop-opacity="0.34"/>
      <stop offset="60%" stop-color="#0369A1" stop-opacity="0.1"/>
      <stop offset="100%" stop-color="#0369A1" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="nebulaPink" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#EC4899" stop-opacity="0.28"/>
      <stop offset="65%" stop-color="#831843" stop-opacity="0.06"/>
      <stop offset="100%" stop-color="#831843" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="planetGrad" cx="32%" cy="28%" r="72%">
      <stop offset="0%" stop-color="#7DD3FC"/>
      <stop offset="38%" stop-color="#3B82F6"/>
      <stop offset="72%" stop-color="#4338CA"/>
      <stop offset="100%" stop-color="#1E1B4B"/>
    </radialGradient>
    <radialGradient id="rosePlanet" cx="35%" cy="30%" r="70%">
      <stop offset="0%" stop-color="#FDE68A"/>
      <stop offset="45%" stop-color="#F472B6"/>
      <stop offset="100%" stop-color="#581C87"/>
    </radialGradient>
    <radialGradient id="galaxyCore" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#FFFFFF" stop-opacity="0.95"/>
      <stop offset="28%" stop-color="#C4B5FD" stop-opacity="0.7"/>
      <stop offset="65%" stop-color="#38BDF8" stop-opacity="0.2"/>
      <stop offset="100%" stop-color="#38BDF8" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="ringGrad" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#38BDF8" stop-opacity="0.2"/>
      <stop offset="30%" stop-color="#A78BFA" stop-opacity="0.85"/>
      <stop offset="55%" stop-color="#FDE68A" stop-opacity="0.9"/>
      <stop offset="80%" stop-color="#38BDF8" stop-opacity="0.75"/>
      <stop offset="100%" stop-color="#F472B6" stop-opacity="0.18"/>
    </linearGradient>
    <linearGradient id="meteorGrad" x1="0" y1="1" x2="1" y2="0">
      <stop offset="0%" stop-color="#FFFFFF"/>
      <stop offset="25%" stop-color="#7DD3FC" stop-opacity="0.85"/>
      <stop offset="100%" stop-color="#7DD3FC" stop-opacity="0"/>
    </linearGradient>
    <filter id="glowSoft" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="3.5" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <clipPath id="heroClip"><rect x="1" y="1" width="{W-2}" height="{H-2}" rx="18"/></clipPath>
    <clipPath id="saturnClip"><circle cx="718" cy="174" r="42"/></clipPath>
    <style>{base_styles(extra_css)}</style>
  </defs>

  <g clip-path="url(#heroClip)">
    <rect width="{W}" height="{H}" fill="url(#bg)"/>

    <!-- Breathing Cosmic Nebulae -->
    <ellipse cx="690" cy="110" rx="220" ry="135" fill="url(#nebulaViolet)" class="nebula"/>
    <ellipse cx="180" cy="245" rx="230" ry="120" fill="url(#nebulaCyan)" class="nebula" style="animation-delay:-3s"/>
    <ellipse cx="560" cy="245" rx="180" ry="95" fill="url(#nebulaPink)" class="nebula" style="animation-delay:-5.5s"/>

    <!-- Twinkling Starfield -->
    {starfield_svg(W, H, 62, seed=101)}

    <!-- Shooting Stars / Meteors -->
    <g class="m1">
      <line x1="590" y1="22" x2="660" y2="-9" stroke="url(#meteorGrad)" stroke-width="2" stroke-linecap="round"/>
      <circle cx="590" cy="22" r="2.2" fill="#FFFFFF" filter="url(#glowSoft)"/>
    </g>
    <g class="m2">
      <line x1="780" y1="45" x2="845" y2="17" stroke="url(#meteorGrad)" stroke-width="1.6" stroke-linecap="round"/>
      <circle cx="780" cy="45" r="1.8" fill="#E0F2FE"/>
    </g>
    <g class="m3">
      <line x1="420" y1="18" x2="480" y2="-8" stroke="url(#meteorGrad)" stroke-width="1.5" stroke-linecap="round"/>
      <circle cx="420" cy="18" r="1.6" fill="#FDE68A"/>
    </g>

    <!-- Rotating Spiral Galaxy -->
    <g transform="translate(615, 78) rotate(-22) scale(1, 0.56)">
      <g class="spin-slow">
        <circle cx="0" cy="0" r="56" fill="url(#galaxyCore)"/>
        <path d="M 0 0 C 14 -6, 28 4, 34 22 C 39 38, 22 52, 4 54" fill="none" stroke="#C4B5FD" stroke-width="2.4" stroke-opacity="0.65" stroke-linecap="round"/>
        <path d="M 0 0 C -14 6, -28 -4, -34 -22 C -39 -38, -22 -52, -4 -54" fill="none" stroke="#7DD3FC" stroke-width="2.4" stroke-opacity="0.65" stroke-linecap="round"/>
        <path d="M 0 0 C 8 16, -6 30, -24 34 C -40 38, -50 22, -48 6" fill="none" stroke="#F472B6" stroke-width="1.6" stroke-opacity="0.5" stroke-linecap="round"/>
        <path d="M 0 0 C -8 -16, 6 -30, 24 -34 C 40 -38, 50 -22, 48 -6" fill="none" stroke="#FDE68A" stroke-width="1.6" stroke-opacity="0.48" stroke-linecap="round"/>
        <circle cx="24" cy="14" r="1.4" fill="#FFFFFF"/>
        <circle cx="-26" cy="-16" r="1.3" fill="#E0F2FE"/>
        <circle cx="-18" cy="28" r="1.2" fill="#FBCFE8"/>
        <circle cx="20" cy="-26" r="1.2" fill="#FDE68A"/>
      </g>
    </g>

    <!-- Secondary Floating Rose-Gold Exoplanet + Micro Moon -->
    <g class="float-y">
      <ellipse cx="568" cy="224" rx="28" ry="10" transform="rotate(14 568 224)" fill="none" stroke="#F472B6" stroke-opacity="0.3" stroke-width="1" stroke-dasharray="3 4"/>
      <circle cx="568" cy="224" r="13.5" fill="url(#rosePlanet)"/>
      <circle cx="568" cy="224" r="13.5" fill="none" stroke="#FDE68A" stroke-opacity="0.35" stroke-width="1"/>
    </g>
    <g class="mini-moon">
      <circle cx="0" cy="0" r="3.2" fill="#7DD3FC" filter="url(#glowSoft)"/>
    </g>

    <!-- Ringed Saturn-like Exoplanet + 3D Orbiting Moon -->
    <!-- Back half of rings -->
    <g transform="translate(718, 174) rotate(-18)">
      <path d="M -86 0 A 86 24 0 0 1 86 0" fill="none" stroke="url(#ringGrad)" stroke-width="7.5" stroke-opacity="0.55"/>
      <path d="M -71 0 A 71 19 0 0 1 71 0" fill="none" stroke="#7DD3FC" stroke-width="1.6" stroke-opacity="0.45"/>
    </g>
    <!-- Planet Body + Atmospheric Bands -->
    <circle cx="718" cy="174" r="48" fill="#38BDF8" fill-opacity="0.1" filter="url(#glowSoft)"/>
    <circle cx="718" cy="174" r="42" fill="url(#planetGrad)"/>
    <g clip-path="url(#saturnClip)" opacity="0.28">
      <path d="M 670 156 Q 718 148 766 158" fill="none" stroke="#E0F2FE" stroke-width="4.5"/>
      <path d="M 670 172 Q 718 164 766 176" fill="none" stroke="#C4B5FD" stroke-width="6"/>
      <path d="M 670 190 Q 718 184 766 194" fill="none" stroke="#F472B6" stroke-width="3.5"/>
    </g>
    <circle cx="718" cy="174" r="42" fill="none" stroke="#7DD3FC" stroke-opacity="0.45" stroke-width="1.2"/>
    <!-- Front half of rings overlapping planet -->
    <g transform="translate(718, 174) rotate(-18)">
      <path d="M -86 0 A 86 24 0 0 0 86 0" fill="none" stroke="url(#ringGrad)" stroke-width="7.5" stroke-opacity="0.92"/>
      <path d="M -71 0 A 71 19 0 0 0 71 0" fill="none" stroke="#E0F2FE" stroke-width="1.6" stroke-opacity="0.72"/>
    </g>
    <!-- 3D Orbiting Moon -->
    <g class="hero-moon">
      <circle cx="0" cy="0" r="6.2" fill="#FDE68A" filter="url(#glowSoft)"/>
      <circle cx="-1.5" cy="-1.5" r="2.2" fill="#FFFFFF" opacity="0.7"/>
    </g>

    <!-- Mission Control Content (Left) -->
    <!-- Pulsing Status Beacon + Handle Pill -->
    <g transform="translate(44, 34)">
      <rect x="0" y="0" width="{status_w:.0f}" height="24" rx="12" fill="#0F1738" fill-opacity="0.9" stroke="{C_EMERALD}" stroke-opacity="0.45" stroke-width="1"/>
      <g transform="translate(15, 12)">
        <circle cx="0" cy="0" r="4.5" fill="{C_EMERALD}" class="status-pulse"/>
        <circle cx="0" cy="0" r="3.6" fill="{C_EMERALD}" class="status-dot"/>
      </g>
      <text x="27" y="16" fill="{C_EMERALD}" font-size="10.5" font-weight="600" letter-spacing="0.9" class="mono">{status}</text>
    </g>
    <g transform="translate({handle_x}, 34)">
      <rect x="0" y="0" width="{handle_w:.0f}" height="24" rx="12" fill="#0F1738" fill-opacity="0.9" stroke="{C_CYAN}" stroke-opacity="0.45" stroke-width="1"/>
      <text x="{handle_w/2:.0f}" y="16" text-anchor="middle" fill="{C_CYAN}" font-size="11" font-weight="600" class="mono">@{username}</text>
    </g>

    <!-- Display Name + Tagline -->
    <text x="44" y="106" fill="url(#titleGrad)" font-size="40" font-weight="800" letter-spacing="-0.6" class="sans">{display}</text>
    <text x="44" y="138" fill="{C_CYAN}" font-size="13" font-weight="500" class="mono">{tagline}<tspan class="blink" fill="{C_AMBER}"> ▌</tspan></text>

    <!-- Subtle divider glow line -->
    <line x1="44" y1="152" x2="490" y2="152" stroke="url(#frameGrad)" stroke-width="1" stroke-opacity="0.5"/>

    <!-- Bio Lines -->
    {''.join(bio_markup)}

    <!-- Metadata Pills -->
    {''.join(pill_svg)}
  </g>

  <rect x="1" y="1" width="{W-2}" height="{H-2}" rx="18" fill="none" stroke="url(#frameGrad)" stroke-width="1.3"/>
</svg>
"""


def render_tech_stack(profile: dict[str, Any]) -> str:
    W, H = 850, 312
    groups = (profile.get("tech_stack") or [])[:4]
    cx, cy = 160, 166

    # 6 orbiting planets across 3 concentric tilted orbits
    orbits_spec = [
        ("p1", 46, 20, -14, 0, 7.5, 5.2, C_CYAN),
        ("p2", 46, 20, -14, 180, 7.5, 3.8, C_AMBER),
        ("p3", 82, 36, -14, 45, 13.0, 6.8, C_VIOLET),
        ("p4", 82, 36, -14, 225, 13.0, 4.6, C_MAGENTA),
        ("p5", 118, 52, -14, 120, 19.5, 6.0, C_EMERALD),
        ("p6", 118, 52, -14, 300, 19.5, 4.4, "#7DD3FC"),
    ]
    kf = [orbit_keyframes(name, cx, cy, rx, ry, tilt, start, 24) for name, rx, ry, tilt, start, _, _, _ in orbits_spec]
    cls_css = [f".{name} {{ animation: {name} {dur}s linear infinite; }}" for name, _, _, _, _, dur, _, _ in orbits_spec]
    extra_css = "\n".join(kf + cls_css) + """
    @keyframes sunPulse { 0%, 100% { transform: scale(1); opacity: 0.55; } 50% { transform: scale(1.18); opacity: 0.9; } }
    .sun-corona { animation: sunPulse 4.2s ease-in-out infinite; }
    """

    planets_svg = []
    for name, _, _, _, _, _, r, col in orbits_spec:
        ring = (
            f'<ellipse cx="0" cy="0" rx="{r*1.9:.1f}" ry="{r*0.55:.1f}" transform="rotate(-18)" '
            f'fill="none" stroke="#E0F2FE" stroke-opacity="0.7" stroke-width="1.3"/>'
            if name == "p3"
            else ""
        )
        planets_svg.append(
            f'<g class="{name}">'
            f'{ring}'
            f'<circle cx="0" cy="0" r="{r:.1f}" fill="{col}" filter="url(#softGlow)"/>'
            f'<circle cx="{-r*0.28:.1f}" cy="{-r*0.28:.1f}" r="{r*0.32:.1f}" fill="#FFFFFF" opacity="0.65"/>'
            f'</g>'
        )

    rows_svg = []
    start_y = 74
    row_gap = 56
    for idx, grp in enumerate(groups):
        ry = start_y + idx * row_gap
        cat = esc(grp.get("category", "Stack").upper())
        accent = grp.get("color", C_CYAN)
        rows_svg.append(
            f'<g>'
            f'<circle cx="336" cy="{ry - 4}" r="3.5" fill="{accent}" filter="url(#softGlow)"/>'
            f'<text x="348" y="{ry}" fill="{C_TEXT_MUTED}" font-size="10.5" font-weight="700" letter-spacing="1.2" class="mono">{cat}</text>'
            f'</g>'
        )
        px = 336
        py = ry + 10
        for item in (grp.get("items") or [])[:6]:
            label = esc(item)
            pw = max(62, int(len(str(item)) * 7.1 + 26))
            if px + pw > W - 26:
                break
            rows_svg.append(
                f'<g>'
                f'<rect x="{px}" y="{py}" width="{pw}" height="26" rx="13" fill="{C_CARD}" stroke="{accent}" stroke-opacity="0.45" stroke-width="1"/>'
                f'<circle cx="{px + 12}" cy="{py + 13}" r="3" fill="{accent}"/>'
                f'<text x="{px + 21}" y="{py + 17}" fill="{C_TEXT_PRI}" font-size="11.5" font-weight="500" class="sans">{label}</text>'
                f'</g>'
            )
            px += pw + 8

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="stack-title stack-desc">
  <title id="stack-title">Orbital Tech Stack</title>
  <desc id="stack-desc">Animated solar system with orbiting planets representing core languages, frameworks, backend, and tooling.</desc>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{C_BG_TOP}"/>
      <stop offset="100%" stop-color="{C_BG_BOT}"/>
    </linearGradient>
    <linearGradient id="borderGrad" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="{C_VIOLET}" stop-opacity="0.55"/>
      <stop offset="50%" stop-color="{C_CYAN}" stop-opacity="0.6"/>
      <stop offset="100%" stop-color="{C_EMERALD}" stop-opacity="0.5"/>
    </linearGradient>
    <radialGradient id="sunCore" cx="40%" cy="35%" r="65%">
      <stop offset="0%" stop-color="#FFFBEB"/>
      <stop offset="35%" stop-color="#FBBF24"/>
      <stop offset="75%" stop-color="#F97316"/>
      <stop offset="100%" stop-color="#9A3412"/>
    </radialGradient>
    <radialGradient id="sunHalo" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#FBBF24" stop-opacity="0.55"/>
      <stop offset="60%" stop-color="#F97316" stop-opacity="0.15"/>
      <stop offset="100%" stop-color="#F97316" stop-opacity="0"/>
    </radialGradient>
    <filter id="softGlow" x="-40%" y="-40%" width="180%" height="180%">
      <feGaussianBlur stdDeviation="2.6" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <clipPath id="stackClip"><rect x="1" y="1" width="{W-2}" height="{H-2}" rx="18"/></clipPath>
    <style>{base_styles(extra_css)}</style>
  </defs>

  <g clip-path="url(#stackClip)">
    <rect width="{W}" height="{H}" fill="url(#bg)"/>
    {starfield_svg(W, H, 46, seed=202)}

    <!-- Section Header -->
    <text x="34" y="38" fill="{C_TEXT_PRI}" font-size="15" font-weight="700" letter-spacing="0.8" class="mono">PLANETARY TECH STACK</text>
    <text x="336" y="38" fill="{C_TEXT_MUTED}" font-size="11" letter-spacing="1.1" class="mono">// ORBITING CONSTELLATIONS</text>
    <line x1="34" y1="49" x2="{W-34}" y2="49" stroke="{C_CARD_BORDER}" stroke-width="1"/>

    <!-- Left Solar System Orrery -->
    <g transform="translate({cx}, {cy}) rotate(-14)">
      <ellipse cx="0" cy="0" rx="46" ry="20" fill="none" stroke="{C_CYAN}" stroke-opacity="0.32" stroke-width="1"/>
      <ellipse cx="0" cy="0" rx="82" ry="36" fill="none" stroke="{C_VIOLET}" stroke-opacity="0.32" stroke-width="1" stroke-dasharray="4 4"/>
      <ellipse cx="0" cy="0" rx="118" ry="52" fill="none" stroke="{C_EMERALD}" stroke-opacity="0.28" stroke-width="1"/>
    </g>

    <!-- Central Star -->
    <g transform="translate({cx}, {cy})">
      <circle cx="0" cy="0" r="36" fill="url(#sunHalo)" class="sun-corona"/>
      <circle cx="0" cy="0" r="18" fill="url(#sunCore)" filter="url(#softGlow)"/>
    </g>

    <!-- Orbiting Planets -->
    {''.join(planets_svg)}

    <text x="{cx}" y="274" text-anchor="middle" fill="{C_TEXT_MUTED}" font-size="10.5" letter-spacing="1.4" class="mono">SOLAR STACK SYSTEM</text>

    <!-- Vertical Divider -->
    <line x1="312" y1="64" x2="312" y2="282" stroke="{C_CARD_BORDER}" stroke-width="1" stroke-dasharray="3 5"/>

    <!-- Categorized Stack Pills -->
    {''.join(rows_svg)}
  </g>
  <rect x="1" y="1" width="{W-2}" height="{H-2}" rx="18" fill="none" stroke="url(#borderGrad)" stroke-width="1.2"/>
</svg>
"""


def render_telemetry(stats: dict[str, Any]) -> str:
    W, H = 850, 286
    streak = stats["current_streak"]
    best = stats["longest_streak"]
    live_badge = f"LIVE SYNC · {stats['updated_at']}" if stats["live"] else "STARTER PREVIEW · SYNC VIA GITHUB ACTION"
    badge_color = C_EMERALD if stats["live"] else C_AMBER

    # Gauge arc ratio (cap visually at 30 days = full orbit)
    r = 52
    circ = 2 * math.pi * r
    ratio = min(1.0, max(0.14, streak / 30.0)) if streak > 0 else 0.08
    dash = circ * ratio

    cards = [
        ("COMMITS (YEAR)", fmt_num(stats["commits"]), "Code transmissions", C_CYAN, "commit"),
        ("CONTRIBUTIONS", fmt_num(stats["contributions"]), "365-day activity", C_VIOLET, "nova"),
        ("PRs & ISSUES", f"{fmt_num(stats['prs'])} / {fmt_num(stats['issues'])}", f"{fmt_num(stats['reviews'])} reviews", C_MAGENTA, "pr"),
        ("STARS & REPOS", f"{fmt_num(stats['stars'])} / {fmt_num(stats['repo_count'])}", f"{fmt_num(stats['followers'])} followers", C_AMBER, "star"),
    ]

    cards_svg = []
    for idx, (label, val, sub, accent, kind) in enumerate(cards):
        col = idx % 2
        row = idx // 2
        x = 228 + col * 298
        y = 66 + row * 62
        cw, ch = 284, 52
        if kind == "commit":
            icon = f'<circle cx="{x+22}" cy="{y+26}" r="4.5" fill="none" stroke="{accent}" stroke-width="1.8"/><line x1="{x+11}" y1="{y+26}" x2="{x+17.5}" y2="{y+26}" stroke="{accent}" stroke-width="1.8"/><line x1="{x+26.5}" y1="{y+26}" x2="{x+33}" y2="{y+26}" stroke="{accent}" stroke-width="1.8"/>'
        elif kind == "nova":
            icon = f'<path d="M{x+22} {y+16}l2.2 6.8 6.8 2.2-6.8 2.2-2.2 6.8-2.2-6.8-6.8-2.2 6.8-2.2z" fill="{accent}"/>'
        elif kind == "pr":
            icon = f'<circle cx="{x+17}" cy="{y+19}" r="2.6" fill="none" stroke="{accent}" stroke-width="1.6"/><circle cx="{x+17}" cy="{y+33}" r="2.6" fill="none" stroke="{accent}" stroke-width="1.6"/><circle cx="{x+28}" cy="{y+33}" r="2.6" fill="none" stroke="{accent}" stroke-width="1.6"/><line x1="{x+17}" y1="{y+21.6}" x2="{x+17}" y2="{y+30.4}" stroke="{accent}" stroke-width="1.6"/><path d="M{x+20} {y+19}h4a4 4 0 0 1 4 4v7.4" fill="none" stroke="{accent}" stroke-width="1.6"/>'
        else:
            icon = f'<path d="M{x+22} {y+16}l2.6 5.4 5.9.8-4.3 4.2 1 5.9-5.2-2.8-5.2 2.8 1-5.9-4.3-4.2 5.9-.8z" fill="{accent}"/>'

        cards_svg.append(
            f'<g>'
            f'<rect x="{x}" y="{y}" width="{cw}" height="{ch}" rx="12" fill="{C_CARD}" stroke="{C_CARD_BORDER}" stroke-width="1"/>'
            f'<rect x="{x+1}" y="{y+1}" width="3" height="{ch-2}" rx="1.5" fill="{accent}"/>'
            f'{icon}'
            f'<text x="{x+44}" y="{y+21}" fill="{C_TEXT_MUTED}" font-size="10" font-weight="700" letter-spacing="0.9" class="mono">{esc(label)}</text>'
            f'<text x="{x+44}" y="{y+41}" fill="{C_TEXT_PRI}" font-size="18" font-weight="800" class="sans">{esc(val)}</text>'
            f'<text x="{x+cw-14}" y="{y+39}" text-anchor="end" fill="{C_TEXT_MUTED}" font-size="10.5" class="mono">{esc(sub)}</text>'
            f'</g>'
        )

    # Top Languages Bar
    langs = stats.get("top_languages") or []
    bar_x, bar_y, bar_w, bar_h = 34, 218, 782, 12
    total_pct = sum(l["pct"] for l in langs) or 100.0
    seg_svg = []
    leg_svg = []
    cur_x = float(bar_x)
    lx = 34
    if not langs:
        leg_svg.append(f'<text x="34" y="256" fill="{C_TEXT_MUTED}" font-size="11.5" class="mono">No public language telemetry yet</text>')
    for i, lang in enumerate(langs[:6]):
        seg_w = (lang["pct"] / total_pct) * bar_w
        if i == len(langs[:6]) - 1:
            seg_w = max(0.0, (bar_x + bar_w) - cur_x)
        col = lang.get("color") or C_CYAN
        seg_svg.append(f'<rect x="{cur_x:.1f}" y="{bar_y}" width="{seg_w:.1f}" height="{bar_h}" fill="{col}"/>')
        cur_x += seg_w
        text_l = f"{lang['name']} {lang['pct']:.1f}%"
        item_w = int(len(text_l) * 7.2 + 24)
        if lx + item_w <= W - 30:
            leg_svg.append(
                f'<g>'
                f'<circle cx="{lx + 5}" cy="252" r="4" fill="{col}"/>'
                f'<text x="{lx + 14}" y="256" fill="{C_TEXT_SEC}" font-size="11.5" class="mono">{esc(text_l)}</text>'
                f'</g>'
            )
            lx += item_w + 6

    extra_css = f"""
    @keyframes arcBreath {{ 0%, 100% {{ opacity: 0.88; }} 50% {{ opacity: 1; }} }}
    .arc-glow {{ animation: arcBreath 3.6s ease-in-out infinite; }}
    .bar-shimmer {{ animation: shimmer 5.2s ease-in-out infinite; }}
    """

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="tel-title tel-desc">
  <title id="tel-title">Cosmic Telemetry and Languages</title>
  <desc id="tel-desc">GitHub streak, commits, contributions, pull requests, stars, repositories, and top language distribution.</desc>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{C_BG_TOP}"/>
      <stop offset="100%" stop-color="{C_BG_BOT}"/>
    </linearGradient>
    <linearGradient id="arcGrad" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{C_CYAN}"/>
      <stop offset="50%" stop-color="{C_VIOLET}"/>
      <stop offset="100%" stop-color="{C_MAGENTA}"/>
    </linearGradient>
    <linearGradient id="sheen" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#FFFFFF" stop-opacity="0"/>
      <stop offset="50%" stop-color="#FFFFFF" stop-opacity="0.45"/>
      <stop offset="100%" stop-color="#FFFFFF" stop-opacity="0"/>
    </linearGradient>
    <filter id="glow" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="2.5" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <clipPath id="telClip"><rect x="1" y="1" width="{W-2}" height="{H-2}" rx="18"/></clipPath>
    <clipPath id="barClip"><rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" rx="6"/></clipPath>
    <style>{base_styles(extra_css)}</style>
  </defs>

  <g clip-path="url(#telClip)">
    <rect width="{W}" height="{H}" fill="url(#bg)"/>
    {starfield_svg(W, H, 36, seed=303)}

    <!-- Header -->
    <text x="34" y="38" fill="{C_TEXT_PRI}" font-size="15" font-weight="700" letter-spacing="0.8" class="mono">COSMIC TELEMETRY</text>
    <text x="{W-34}" y="37" text-anchor="end" fill="{badge_color}" font-size="10.5" font-weight="600" letter-spacing="0.8" class="mono">{esc(live_badge)}</text>
    <line x1="34" y1="49" x2="{W-34}" y2="49" stroke="{C_CARD_BORDER}" stroke-width="1"/>

    <!-- Orbital Streak Gauge -->
    <g transform="translate(120, 128)">
      <circle cx="0" cy="0" r="64" fill="none" stroke="{C_CYAN}" stroke-opacity="0.22" stroke-width="1" stroke-dasharray="3 6" class="spin-slow"/>
      <circle cx="0" cy="0" r="{r}" fill="{C_CARD}" stroke="#1E295B" stroke-width="7"/>
      <circle cx="0" cy="0" r="{r}" fill="none" stroke="url(#arcGrad)" stroke-width="7" stroke-linecap="round"
        stroke-dasharray="{dash:.1f} {circ:.1f}" transform="rotate(-90)" filter="url(#glow)" class="arc-glow"/>
      <!-- Orbiting gauge beacon -->
      <g class="spin-med">
        <circle cx="0" cy="-64" r="3.4" fill="{C_CYAN}" filter="url(#glow)"/>
      </g>
      <text x="0" y="-2" text-anchor="middle" fill="{C_TEXT_PRI}" font-size="26" font-weight="800" class="sans">{streak}</text>
      <text x="0" y="15" text-anchor="middle" fill="{C_CYAN}" font-size="9.5" font-weight="700" letter-spacing="1" class="mono">DAY STREAK</text>
      <text x="0" y="31" text-anchor="middle" fill="{C_TEXT_MUTED}" font-size="9.5" class="mono">Best: {best}d</text>
    </g>

    <!-- 2x2 Metric Cards -->
    {''.join(cards_svg)}

    <!-- Language Nebula Spectrum -->
    <text x="34" y="207" fill="{C_TEXT_MUTED}" font-size="10.5" font-weight="700" letter-spacing="1.1" class="mono">LANGUAGE SPECTRUM</text>
    <g clip-path="url(#barClip)">
      <rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" fill="#172047"/>
      {''.join(seg_svg)}
      <rect x="{bar_x}" y="{bar_y}" width="120" height="{bar_h}" fill="url(#sheen)" class="bar-shimmer"/>
    </g>
    {''.join(leg_svg)}
  </g>
  <rect x="1" y="1" width="{W-2}" height="{H-2}" rx="18" fill="none" stroke="{C_CARD_BORDER}" stroke-width="1.2"/>
</svg>
"""


def render_contributions(stats: dict[str, Any]) -> str:
    W, H = 850, 326
    weeks = (stats.get("weeks") or [])[-53:]
    flat = [d for w in weeks for d in w.get("contributionDays") or []]
    max_day = max((d["contributionCount"] for d in flat), default=1) or 1

    # Starfield heatmap grid: 53 cols * 14px = 742px -> start at x=54
    gx, gy = 54, 72
    step = 14
    cell = 11
    levels = ["#12193B", "#312E81", "#6D28D9", "#0EA5E9", "#7DD3FC"]

    cells_svg = []
    months_svg = []
    seen_months: set[tuple[int, int]] = set()
    last_month_wi = -4
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    for wi, week in enumerate(weeks):
        days = week.get("contributionDays") or []
        if days:
            first_dt = dt.date.fromisoformat(days[0]["date"])
            key = (first_dt.year, first_dt.month)
            if key not in seen_months and wi < len(weeks) - 1 and (wi - last_month_wi) >= 3:
                seen_months.add(key)
                last_month_wi = wi
                months_svg.append(
                    f'<text x="{gx + wi * step}" y="{gy - 7}" fill="{C_TEXT_MUTED}" font-size="9.5" class="mono">{month_names[first_dt.month - 1]}</text>'
                )
        for day in days:
            cnt = day["contributionCount"]
            wd = day["weekday"]
            x = gx + wi * step
            y = gy + wd * step
            if cnt <= 0:
                lvl = 0
            else:
                ratio = cnt / max_day
                lvl = 1 if ratio <= 0.25 else (2 if ratio <= 0.5 else (3 if ratio <= 0.78 else 4))
            cls = ""
            extra = ""
            if lvl == 4:
                cls = f' class="tw{(wi + wd) % 3 + 1}"'
                extra = ' filter="url(#starGlow)"'
            elif lvl == 0:
                extra = ' stroke="#1C2654" stroke-width="0.6"'
            cells_svg.append(
                f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2.5" fill="{levels[lvl]}"{cls}{extra}/>'
            )

    # 30-day commit activity wave
    last30 = flat[-30:] if len(flat) >= 2 else [{"date": "2026-01-01", "contributionCount": 0}, {"date": "2026-01-02", "contributionCount": 0}]
    wx, wy, ww, wh = 54, 212, 742, 72
    wmax = max((d["contributionCount"] for d in last30), default=1) or 1
    pts = []
    for i, d in enumerate(last30):
        px = wx + (i / max(1, len(last30) - 1)) * ww
        py = wy + wh - (d["contributionCount"] / wmax) * (wh - 12) - 4
        pts.append((px, py, d["contributionCount"]))

    # Smooth Catmull-like cubic path
    path_d = f"M {pts[0][0]:.1f} {pts[0][1]:.1f}"
    for i in range(1, len(pts)):
        x0, y0, _ = pts[i - 1]
        x1, y1, _ = pts[i]
        mx = (x0 + x1) / 2.0
        path_d += f" C {mx:.1f} {y0:.1f}, {mx:.1f} {y1:.1f}, {x1:.1f} {y1:.1f}"
    area_d = f"{path_d} L {pts[-1][0]:.1f} {wy + wh} L {pts[0][0]:.1f} {wy + wh} Z"

    peak_dots = []
    for i, (px, py, cnt) in enumerate(pts):
        if cnt >= wmax * 0.65 and cnt > 0:
            peak_dots.append(
                f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.2" fill="#7DD3FC" class="tw{(i % 3) + 1}" filter="url(#starGlow)"/>'
            )

    last30_total = sum(d["contributionCount"] for d in last30)
    extra_css = """
    @keyframes cometSweep {
      0% { transform: translateX(-80px); opacity: 0; }
      8% { opacity: 0.95; }
      90% { opacity: 0.95; }
      100% { transform: translateX(790px); opacity: 0; }
    }
    .comet { animation: cometSweep 9.5s ease-in-out infinite; }
    @keyframes wavePulse {
      0%, 100% { opacity: 0.85; }
      50% { opacity: 1; }
    }
    .wave-line { animation: wavePulse 4s ease-in-out infinite; }
    """

    legend_svg = []
    for i, col in enumerate(levels):
        legend_svg.append(f'<rect x="{696 + i * 15}" y="176" width="11" height="11" rx="2.5" fill="{col}"/>')

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="cal-title cal-desc">
  <title id="cal-title">Contribution Starfield and 30-Day Activity Wave</title>
  <desc id="cal-desc">365-day GitHub contribution starfield with animated comet sweep and 30-day cosmic activity waveform.</desc>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{C_BG_TOP}"/>
      <stop offset="100%" stop-color="{C_BG_BOT}"/>
    </linearGradient>
    <linearGradient id="cometTail" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#38BDF8" stop-opacity="0"/>
      <stop offset="75%" stop-color="#A78BFA" stop-opacity="0.7"/>
      <stop offset="100%" stop-color="#FFFFFF" stop-opacity="1"/>
    </linearGradient>
    <linearGradient id="waveStroke" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="{C_VIOLET}"/>
      <stop offset="50%" stop-color="{C_CYAN}"/>
      <stop offset="100%" stop-color="{C_MAGENTA}"/>
    </linearGradient>
    <linearGradient id="waveFill" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{C_CYAN}" stop-opacity="0.34"/>
      <stop offset="100%" stop-color="{C_VIOLET}" stop-opacity="0.02"/>
    </linearGradient>
    <filter id="starGlow" x="-60%" y="-60%" width="220%" height="220%">
      <feGaussianBlur stdDeviation="2.2" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <clipPath id="calClip"><rect x="1" y="1" width="{W-2}" height="{H-2}" rx="18"/></clipPath>
    <clipPath id="gridClip"><rect x="{gx}" y="{gy - 4}" width="{53 * step}" height="{7 * step + 8}"/></clipPath>
    <style>{base_styles(extra_css)}</style>
  </defs>

  <g clip-path="url(#calClip)">
    <rect width="{W}" height="{H}" fill="url(#bg)"/>
    {starfield_svg(W, H, 32, seed=404)}

    <!-- Header -->
    <text x="34" y="38" fill="{C_TEXT_PRI}" font-size="15" font-weight="700" letter-spacing="0.8" class="mono">CONTRIBUTION GALAXY</text>
    <text x="{W-34}" y="37" text-anchor="end" fill="{C_CYAN}" font-size="11.5" font-weight="600" class="mono">{fmt_num(stats['contributions'])} stars ignited (365d)</text>
    <line x1="34" y1="49" x2="{W-34}" y2="49" stroke="{C_CARD_BORDER}" stroke-width="1"/>

    <!-- Weekday & Month Labels -->
    <text x="34" y="{gy + 1 * step + 9}" fill="{C_TEXT_MUTED}" font-size="9" class="mono">Mon</text>
    <text x="34" y="{gy + 3 * step + 9}" fill="{C_TEXT_MUTED}" font-size="9" class="mono">Wed</text>
    <text x="34" y="{gy + 5 * step + 9}" fill="{C_TEXT_MUTED}" font-size="9" class="mono">Fri</text>
    {''.join(months_svg)}

    <!-- Heatmap Cells -->
    {''.join(cells_svg)}

    <!-- Sweeping Cosmic Comet across Heatmap -->
    <g clip-path="url(#gridClip)">
      <g class="comet">
        <line x1="{gx - 70}" y1="{gy + 46}" x2="{gx}" y2="{gy + 46}" stroke="url(#cometTail)" stroke-width="2.2" stroke-linecap="round"/>
        <circle cx="{gx}" cy="{gy + 46}" r="3.4" fill="#FFFFFF" filter="url(#starGlow)"/>
      </g>
    </g>

    <!-- Legend -->
    <text x="660" y="185" fill="{C_TEXT_MUTED}" font-size="9.5" class="mono">Void</text>
    {''.join(legend_svg)}
    <text x="776" y="185" fill="{C_TEXT_MUTED}" font-size="9.5" class="mono">Nova</text>

    <!-- 30-Day Activity Pulse Wave -->
    <text x="54" y="204" fill="{C_TEXT_MUTED}" font-size="10.5" font-weight="700" letter-spacing="1.1" class="mono">30-DAY ORBITAL ACTIVITY WAVE</text>
    <text x="{wx + ww}" y="204" text-anchor="end" fill="{C_TEXT_SEC}" font-size="10.5" class="mono">{fmt_num(last30_total)} recent · peak {wmax}/day</text>
    <line x1="{wx}" y1="{wy + wh}" x2="{wx + ww}" y2="{wy + wh}" stroke="{C_CARD_BORDER}" stroke-width="1"/>
    <line x1="{wx}" y1="{wy + wh // 2}" x2="{wx + ww}" y2="{wy + wh // 2}" stroke="{C_CARD_BORDER}" stroke-opacity="0.45" stroke-width="1" stroke-dasharray="3 5"/>
    <path d="{area_d}" fill="url(#waveFill)"/>
    <path d="{path_d}" fill="none" stroke="url(#waveStroke)" stroke-width="2.4" stroke-linecap="round" class="wave-line"/>
    {''.join(peak_dots)}
    <text x="{wx}" y="303" fill="{C_TEXT_MUTED}" font-size="9.5" class="mono">30d ago</text>
    <text x="{wx + ww}" y="303" text-anchor="end" fill="{C_TEXT_MUTED}" font-size="9.5" class="mono">Today</text>
  </g>
  <rect x="1" y="1" width="{W-2}" height="{H-2}" rx="18" fill="none" stroke="{C_CARD_BORDER}" stroke-width="1.2"/>
</svg>
"""


def render_repositories(stats: dict[str, Any]) -> str:
    repos = (stats.get("repositories") or [])[:6]
    rows = max(1, math.ceil(len(repos) / 2))
    W = 850
    H = 74 + rows * 114 + 14

    card_w, card_h = 380, 98
    gap_x, gap_y = 22, 16
    start_x, start_y = 34, 68

    # Background constellation connector lines between card centers
    centers = []
    for idx in range(len(repos)):
        col, row = idx % 2, idx // 2
        cx = start_x + col * (card_w + gap_x) + card_w / 2
        cy = start_y + row * (card_h + gap_y) + card_h / 2
        centers.append((cx, cy))

    constellation_lines = []
    for i in range(len(centers) - 1):
        x1, y1 = centers[i]
        x2, y2 = centers[i + 1]
        constellation_lines.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{C_CYAN}" stroke-opacity="0.22" stroke-width="1.2" stroke-dasharray="4 6"/>'
        )

    cards_svg = []
    if not repos:
        cards_svg.append(
            f'<rect x="{start_x}" y="{start_y}" width="{W - 2 * start_x}" height="92" rx="14" fill="{C_CARD}" stroke="{C_CARD_BORDER}" stroke-width="1"/>'
            f'<text x="{W / 2:.0f}" y="{start_y + 50}" text-anchor="middle" fill="{C_TEXT_MUTED}" font-size="13" class="mono">No public repositories charted yet — launch your first mission.</text>'
        )
    for idx, repo in enumerate(repos):
        col, row = idx % 2, idx // 2
        x = start_x + col * (card_w + gap_x)
        y = start_y + row * (card_h + gap_y)
        name = repo.get("name", "repository")
        if len(name) > 28:
            name = name[:27] + "…"
        desc_lines = wrap_text(repo.get("description") or "Exploring new frontiers in this repository.", 48, 2)
        lang_obj = repo.get("primaryLanguage") or {}
        lang_name = lang_obj.get("name") or "Code"
        lang_color = lang_obj.get("color") or LANG_COLORS.get(lang_name, C_CYAN)
        stars = fmt_num(int(repo.get("stargazerCount", 0)))
        forks = fmt_num(int(repo.get("forkCount", 0)))

        desc_svg = "".join(
            f'<text x="{x+18}" y="{y+46 + li * 16}" fill="{C_TEXT_SEC}" font-size="11.5" class="sans">{esc(line)}</text>'
            for li, line in enumerate(desc_lines)
        )

        # Repo vector icon + star + fork icons
        cards_svg.append(
            f'<g>'
            f'<rect x="{x}" y="{y}" width="{card_w}" height="{card_h}" rx="14" fill="{C_CARD}" fill-opacity="0.94" stroke="{C_CARD_BORDER}" stroke-width="1"/>'
            f'<rect x="{x+16}" y="{y}" width="64" height="2" rx="1" fill="{lang_color}"/>'
            # Repo book icon
            f'<path d="M{x+18} {y+16}h10a1.5 1.5 0 0 1 1.5 1.5v10a1.5 1.5 0 0 1-1.5 1.5H{x+18}a1.5 1.5 0 0 1-1.5-1.5v-10A1.5 1.5 0 0 1 {x+18} {y+16}zm1 2.2v8.2h8v-8.2z" fill="{C_CYAN}"/>'
            f'<text x="{x+36}" y="{y+27}" fill="{C_TEXT_PRI}" font-size="14" font-weight="700" class="sans">{esc(name)}</text>'
            f'<circle cx="{x+card_w-18}" cy="{y+22}" r="3" fill="{lang_color}" class="tw{(idx % 3) + 1}" filter="url(#glow)"/>'
            f'{desc_svg}'
            # Bottom metadata row
            f'<circle cx="{x+22}" cy="{y+81}" r="4.2" fill="{lang_color}"/>'
            f'<text x="{x+32}" y="{y+85}" fill="{C_TEXT_MUTED}" font-size="11" class="mono">{esc(lang_name)}</text>'
            # Stars
            f'<path d="M{x+242} {y+75}l1.8 3.6 4 .6-2.9 2.8.7 4-3.6-1.9-3.6 1.9.7-4-2.9-2.8 4-.6z" fill="{C_AMBER}"/>'
            f'<text x="{x+252}" y="{y+85}" fill="{C_TEXT_SEC}" font-size="11" class="mono">{stars}</text>'
            # Forks
            f'<circle cx="{x+314}" cy="{y+77}" r="2" fill="none" stroke="{C_VIOLET}" stroke-width="1.3"/>'
            f'<circle cx="{x+322}" cy="{y+77}" r="2" fill="none" stroke="{C_VIOLET}" stroke-width="1.3"/>'
            f'<circle cx="{x+318}" cy="{y+85}" r="2" fill="none" stroke="{C_VIOLET}" stroke-width="1.3"/>'
            f'<path d="M{x+314} {y+79}v2h8v-2M{x+318} {y+81}v2" fill="none" stroke="{C_VIOLET}" stroke-width="1.3"/>'
            f'<text x="{x+329}" y="{y+85}" fill="{C_TEXT_SEC}" font-size="11" class="mono">{forks}</text>'
            f'</g>'
        )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="repo-title repo-desc">
  <title id="repo-title">Featured Repositories Star Map</title>
  <desc id="repo-desc">Constellation grid displaying featured repositories with primary languages, stars, and forks.</desc>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{C_BG_TOP}"/>
      <stop offset="100%" stop-color="{C_BG_BOT}"/>
    </linearGradient>
    <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur stdDeviation="2.2" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <clipPath id="repoClip"><rect x="1" y="1" width="{W-2}" height="{H-2}" rx="18"/></clipPath>
    <style>{base_styles()}</style>
  </defs>

  <g clip-path="url(#repoClip)">
    <rect width="{W}" height="{H}" fill="url(#bg)"/>
    {starfield_svg(W, H, 38, seed=505)}

    <!-- Header -->
    <text x="34" y="38" fill="{C_TEXT_PRI}" font-size="15" font-weight="700" letter-spacing="0.8" class="mono">STAR CHART // REPOSITORIES</text>
    <text x="{W-34}" y="37" text-anchor="end" fill="{C_TEXT_MUTED}" font-size="11" class="mono">{len(repos)} sectors charted</text>
    <line x1="34" y1="49" x2="{W-34}" y2="49" stroke="{C_CARD_BORDER}" stroke-width="1"/>

    <!-- Background Constellation Paths -->
    {''.join(constellation_lines)}

    <!-- Repository Sector Cards -->
    {''.join(cards_svg)}
  </g>
  <rect x="1" y="1" width="{W-2}" height="{H-2}" rx="18" fill="none" stroke="{C_CARD_BORDER}" stroke-width="1.2"/>
</svg>
"""


def render_footer(profile: dict[str, Any]) -> str:
    W, H = 850, 84
    text = esc(profile.get("footer_text", "TRANSMISSION OPEN · EXPLORE THE COSMOS"))
    extra_css = """
    @keyframes waveDrift1 { 0%, 100% { transform: translateX(0px); } 50% { transform: translateX(-38px); } }
    @keyframes waveDrift2 { 0%, 100% { transform: translateX(-30px); } 50% { transform: translateX(18px); } }
    @keyframes probeGlide {
      0% { transform: translateX(-40px); opacity: 0; }
      10% { opacity: 1; }
      90% { opacity: 1; }
      100% { transform: translateX(890px); opacity: 0; }
    }
    .w1 { animation: waveDrift1 9s ease-in-out infinite; }
    .w2 { animation: waveDrift2 12s ease-in-out infinite; }
    .probe { animation: probeGlide 14s linear infinite; }
    """
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="foot-title">
  <title id="foot-title">{text}</title>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="{C_BG_TOP}"/>
      <stop offset="50%" stop-color="{C_BG_MID}"/>
      <stop offset="100%" stop-color="{C_BG_TOP}"/>
    </linearGradient>
    <linearGradient id="nebWave1" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="{C_VIOLET}" stop-opacity="0.35"/>
      <stop offset="50%" stop-color="{C_CYAN}" stop-opacity="0.45"/>
      <stop offset="100%" stop-color="{C_MAGENTA}" stop-opacity="0.35"/>
    </linearGradient>
    <linearGradient id="nebWave2" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="{C_CYAN}" stop-opacity="0.22"/>
      <stop offset="50%" stop-color="{C_MAGENTA}" stop-opacity="0.3"/>
      <stop offset="100%" stop-color="{C_VIOLET}" stop-opacity="0.22"/>
    </linearGradient>
    <clipPath id="footClip"><rect x="1" y="1" width="{W-2}" height="{H-2}" rx="16"/></clipPath>
    <style>{base_styles(extra_css)}</style>
  </defs>
  <g clip-path="url(#footClip)">
    <rect width="{W}" height="{H}" fill="url(#bg)"/>
    {starfield_svg(W, H, 24, seed=606)}
    <path class="w1" d="M -40 58 Q 120 34 280 54 T 600 50 T 940 56 L 940 90 L -40 90 Z" fill="url(#nebWave1)"/>
    <path class="w2" d="M -40 66 Q 160 44 340 62 T 700 56 T 960 64 L 960 90 L -40 90 Z" fill="url(#nebWave2)"/>
    <g class="probe">
      <line x1="-26" y1="22" x2="0" y2="22" stroke="{C_CYAN}" stroke-opacity="0.6" stroke-width="1.5"/>
      <circle cx="0" cy="22" r="2.4" fill="#FFFFFF"/>
    </g>
    <text x="{W/2:.0f}" y="47" text-anchor="middle" fill="{C_TEXT_PRI}" font-size="11.5" font-weight="600" letter-spacing="1.6" class="mono">{text}</text>
  </g>
  <rect x="1" y="1" width="{W-2}" height="{H-2}" rx="16" fill="none" stroke="{C_CARD_BORDER}" stroke-width="1.1"/>
</svg>
"""


def render_readme(profile: dict[str, Any], stats: dict[str, Any]) -> str:
    username = profile.get("username", "seishikun")
    display = profile.get("display_name") or username
    links = profile.get("links") or []
    link_md = " · ".join(f"[{l['label']}]({l['url']})" for l in links)

    repo_links = " · ".join(
        f"[{r['name']}]({r['url']})" for r in (stats.get("repositories") or [])[:6]
    )

    lines = [
        '<div align="center">',
        "",
        f'<a href="https://github.com/{username}">',
        f'  <img src="./assets/hero.svg" alt="{esc(display)} — Animated Universe Profile Header" width="100%" />',
        "</a>",
        "",
        f"{link_md}" if link_md else "",
        "",
        '<img src="./assets/tech-stack.svg" alt="Animated Planetary Tech Stack" width="100%" />',
        "",
        '<img src="./assets/telemetry.svg" alt="Cosmic Telemetry: Streak, Commits, Contributions, PRs, Stars, and Languages" width="100%" />',
        "",
        '<img src="./assets/contributions.svg" alt="365-Day Contribution Galaxy and 30-Day Activity Wave" width="100%" />',
        "",
        f'<a href="https://github.com/{username}?tab=repositories">',
        '  <img src="./assets/repositories.svg" alt="Featured Repositories Star Map" width="100%" />',
        "</a>",
        "",
        f"**Quick Jump:** {repo_links}" if repo_links else "",
        "",
        '<img src="./assets/footer.svg" alt="Animated Cosmic Horizon Footer" width="100%" />',
        "",
        "</div>",
        "",
    ]
    return "\n".join(line for line in lines if line is not None)


def verify_svgs(assets_dir: Path) -> None:
    expected = ["hero.svg", "tech-stack.svg", "telemetry.svg", "contributions.svg", "repositories.svg", "footer.svg"]
    for name in expected:
        p = assets_dir / name
        assert p.exists(), f"Missing {p}"
        raw = p.read_text(encoding="utf-8")
        root = ET.fromstring(raw)
        assert root.tag.endswith("svg"), f"{name}: root is not <svg>"
        assert "@keyframes" in raw, f"{name}: missing CSS animations"
        assert "prefers-reduced-motion" in raw, f"{name}: missing reduced-motion media query"
        assert "<title" in raw, f"{name}: missing accessible <title>"
        assert "<script" not in raw.lower(), f"{name}: forbidden <script> tag"


def run_self_checks() -> None:
    # 1. XML escaping & wrapping edge cases
    assert esc('C++ & <script>"x"') == "C++ &amp; &lt;script&gt;&quot;x&quot;"
    wrapped = wrap_text("A very long description about cosmic distributed systems and galaxies", 22, 2)
    assert len(wrapped) == 2 and wrapped[-1].endswith("…")
    assert wrap_text("", 20, 2) == []

    # 2. Streak calculation edge cases (active yesterday with 0 today, empty, multi-gap)
    assert compute_streaks([]) == (0, 0)
    sample_days = [
        {"date": "2026-01-01", "contributionCount": 3},
        {"date": "2026-01-02", "contributionCount": 2},
        {"date": "2026-01-03", "contributionCount": 5},
        {"date": "2026-01-04", "contributionCount": 0},
        {"date": "2026-01-05", "contributionCount": 1},
        {"date": "2026-01-06", "contributionCount": 4},
        {"date": "2026-01-07", "contributionCount": 0},
    ]
    assert compute_streaks(sample_days) == (2, 3), f"Unexpected streak: {compute_streaks(sample_days)}"

    # 3. Verify generated SVGs on disk are valid XML with animations + a11y
    verify_svgs(ASSETS_DIR)

    # 4. Special-character injection resilience check (in-memory render)
    nasty = {
        "username": "test_user",
        "display_name": 'A&B <Cosmic> "Dev"',
        "tagline": "C++ & C# <3 Space",
        "status": "ONLINE & READY",
        "bio": ["Uses <tags> & 'quotes' safely"],
        "meta": {"location": "Mars & Phobos"},
        "tech_stack": [{"category": "Langs & More", "color": "#38BDF8", "items": ["C++", "C#", "R&D"]}],
        "footer_text": "A & B < C",
    }
    ET.fromstring(render_hero(nasty))
    ET.fromstring(render_tech_stack(nasty))
    ET.fromstring(render_footer(nasty))
    empty_stats = {
        "live": False,
        "updated_at": "2026-01-01",
        "commits": 0,
        "contributions": 0,
        "prs": 0,
        "issues": 0,
        "reviews": 0,
        "stars": 0,
        "repo_count": 0,
        "followers": 0,
        "current_streak": 0,
        "longest_streak": 0,
        "weeks": [],
        "top_languages": [],
        "repositories": [],
    }
    ET.fromstring(render_telemetry(empty_stats))
    ET.fromstring(render_contributions(empty_stats))
    ET.fromstring(render_repositories(empty_stats))
    print("All self-checks passed.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate animated universe GitHub profile SVGs.")
    parser.add_argument("--preview", action="store_true", help="Allow offline preview stats when GITHUB_TOKEN is unset.")
    parser.add_argument("--verify-only", action="store_true", help="Run XML, accessibility, and logic self-checks only.")
    args = parser.parse_args()

    if args.verify_only:
        run_self_checks()
        return 0

    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    username = profile["username"]
    token = os.environ.get("GITHUB_TOKEN", "").strip()

    if token:
        # In CI, fail loudly on API errors instead of overwriting live telemetry with preview zeros
        stats = fetch_github_stats(username, token)
    elif args.preview:
        stats = preview_stats(profile)
    else:
        print("ERROR: GITHUB_TOKEN is not set. Pass --preview to generate offline starter SVGs.", file=sys.stderr)
        return 1

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    outputs = {
        "hero.svg": render_hero(profile),
        "tech-stack.svg": render_tech_stack(profile),
        "telemetry.svg": render_telemetry(stats),
        "contributions.svg": render_contributions(stats),
        "repositories.svg": render_repositories(stats),
        "footer.svg": render_footer(profile),
    }
    for fname, content in outputs.items():
        (ASSETS_DIR / fname).write_text(content, encoding="utf-8")

    README_PATH.write_text(render_readme(profile, stats), encoding="utf-8")
    run_self_checks()
    mode = "live GitHub API" if stats["live"] else "offline preview"
    print(f"Generated {len(outputs)} animated SVGs + README.md ({mode}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
