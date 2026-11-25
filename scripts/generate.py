#!/usr/bin/env python3
"""Generate a single seamless, animated, realistic deep-space GitHub profile SVG and README.md.

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
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = ROOT / "profile.json"
ASSETS_DIR = ROOT / "assets"
OUTPUT_SVG = ASSETS_DIR / "universe.svg"
README_PATH = ROOT / "README.md"

FONT_SANS = "'Segoe UI', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Arial, sans-serif"
FONT_MONO = "'Cascadia Code', 'JetBrains Mono', 'Fira Code', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"

# Deep-space observatory palette (all text >= 4.5:1 on obsidian glass #060A14 / void #020409)
C_VOID_0 = "#020308"
C_VOID_1 = "#040711"
C_VOID_2 = "#03050D"
C_HUD_BG = "#060B17"
C_HUD_LINE = "#243554"
C_HUD_TICK = "#4A6694"
C_TEXT_PRI = "#F1F5F9"
C_TEXT_SEC = "#B8C7DC"
C_TEXT_MUTED = "#8295B2"
C_STAR_BLUE = "#9EC5FE"
C_STAR_ICE = "#CBE2FF"
C_STAR_WARM = "#E8CFA6"
C_STAR_ROSE = "#D89FA8"
C_STATUS_OK = "#6EE7B7"

# Muted astronomical spectral tones for tech categories (replaces neon clipart colors)
ASTRO_ACCENTS = ["#8CC2F8", "#B9B8E8", "#D9A49A", "#86C8B8"]

LANG_COLORS = {
    "TypeScript": "#4E88C7",
    "JavaScript": "#D9C36A",
    "Python": "#5588B5",
    "Rust": "#C99678",
    "Go": "#56B0C9",
    "C++": "#C96A86",
    "C#": "#5AA168",
    "Java": "#B88450",
    "HTML": "#C76B52",
    "CSS": "#8774B8",
    "Shell": "#84B86E",
    "Dart": "#4FA8A4",
    "Swift": "#D4755B",
    "Kotlin": "#9C84D4",
    "Vue": "#62A885",
    "Svelte": "#D46E4E",
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
    idx = len(ordered) - 1
    if idx >= 0 and ordered[idx]["contributionCount"] == 0:
        idx -= 1
    current = 0
    while idx >= 0 and ordered[idx]["contributionCount"] > 0:
        current += 1
        idx -= 1
    return current, longest


def orbit_keyframes(
    name: str,
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    tilt_deg: float,
    start_deg: float = 0.0,
    steps: int = 24,
) -> str:
    """Parametric 3D elliptical orbit keyframes that keep orbiting moons circular."""
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
        depth = math.sin(angle)
        scale = 1.0 + 0.14 * depth
        opacity = 0.65 + 0.35 * ((depth + 1.0) / 2.0)
        frames.append(
            f"  {pct:.2f}% {{ transform: translate({x:.1f}px, {y:.1f}px) scale({scale:.3f}); opacity: {opacity:.2f}; }}"
        )
    return f"@keyframes {name} {{\n" + "\n".join(frames) + "\n}"


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
            color = edge["node"].get("color") or LANG_COLORS.get(name, C_STAR_BLUE)
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
    uname = profile.get("username", "SeishiKun9")

    stack_langs = []
    for grp in profile.get("tech_stack", []):
        if grp.get("category", "").lower() == "languages":
            stack_langs = grp.get("items", [])
            break
    base_langs = stack_langs[:5] if stack_langs else ["TypeScript", "Python", "JavaScript", "HTML", "CSS"]
    weights = [36.4, 27.8, 17.5, 11.2, 7.1]
    top_langs = [
        {"name": name, "color": LANG_COLORS.get(name, C_STAR_BLUE), "pct": weights[i]}
        for i, name in enumerate(base_langs[: len(weights)])
    ]

    default_repos = [
        {
            "name": uname.lower(),
            "description": "Animated deep-space GitHub profile powered by self-updating SVG telemetry.",
            "url": f"https://github.com/{uname}/{uname.lower()}",
            "stargazerCount": 12,
            "forkCount": 3,
            "primaryLanguage": {"name": "Python", "color": "#5588B5"},
        },
        {
            "name": "nebula-ui",
            "description": "Accessible dark-first component kit with crisp motion tokens and zero runtime bloat.",
            "url": f"https://github.com/{uname}",
            "stargazerCount": 24,
            "forkCount": 5,
            "primaryLanguage": {"name": "TypeScript", "color": "#4E88C7"},
        },
        {
            "name": "orbit-api",
            "description": "Lightweight full-stack starter API with typed schemas, caching, and CI checks.",
            "url": f"https://github.com/{uname}",
            "stargazerCount": 18,
            "forkCount": 4,
            "primaryLanguage": {"name": "JavaScript", "color": "#D9C36A"},
        },
        {
            "name": "cosmos-cli",
            "description": "Fast developer automation CLI for scaffolding projects and inspecting git workflows.",
            "url": f"https://github.com/{uname}",
            "stargazerCount": 9,
            "forkCount": 2,
            "primaryLanguage": {"name": "Python", "color": "#5588B5"},
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


def hud_crosshairs(x: float, y: float, w: float, h: float, size: float = 5.0) -> str:
    """Precision observatory reticle ticks on panel corners."""
    corners = [(x, y), (x + w, y), (x, y + h), (x + w, y + h)]
    segs = []
    for cx, cy in corners:
        segs.append(
            f'<path d="M{cx-size:.1f} {cy:.1f}h{size*2:.1f}M{cx:.1f} {cy-size:.1f}v{size*2:.1f}" '
            f'stroke="{C_HUD_TICK}" stroke-width="0.8" stroke-opacity="0.75"/>'
        )
    return "".join(segs)


def build_star_tile(tile_id: str, width: int, height: int, count: int, seed: int, r_range: tuple[float, float], with_spikes: int = 0) -> str:
    """Generate a deterministic astrophotography starfield tile using O-B-A-F-G-K spectral colors."""
    rng = random.Random(seed)
    # Realistic stellar blackbody distribution (mostly pale blue-white, white, warm ivory, rare amber)
    spectral = ["#B8D4FF", "#DCEBFF", "#F5F8FF", "#FFFFFF", "#FFF5E4", "#FFE4BD", "#F7C59F"]
    weights = [16, 22, 24, 16, 12, 7, 3]
    parts = [f'<g id="{tile_id}">']
    for i in range(count):
        x = rng.uniform(6, width - 6)
        y = rng.uniform(8, height - 8)
        r = rng.uniform(r_range[0], r_range[1])
        # Power-law skew so most stars are pinpoint dust, few are bright
        r = r_range[0] + (r - r_range[0]) * (rng.random() ** 1.4)
        col = rng.choices(spectral, weights=weights)[0]
        base_op = rng.uniform(0.35, 0.95)
        tw = f' class="tw{(i % 3) + 1}" style="animation-delay:{-rng.uniform(0, 7):.2f}s"' if i % 3 == 0 else ""
        if i < with_spikes:
            # Subtle JWST/Hubble 4-point optical diffraction spikes on brightest stars
            sp = r * 5.2
            parts.append(
                f'<g opacity="{base_op:.2f}"{tw}>'
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r*2.4:.1f}" fill="{col}" opacity="0.16"/>'
                f'<line x1="{x-sp:.1f}" y1="{y:.1f}" x2="{x+sp:.1f}" y2="{y:.1f}" stroke="{col}" stroke-width="0.55" stroke-opacity="0.55"/>'
                f'<line x1="{x:.1f}" y1="{y-sp:.1f}" x2="{x:.1f}" y2="{y+sp:.1f}" stroke="{col}" stroke-width="0.55" stroke-opacity="0.55"/>'
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.2f}" fill="#FFFFFF"/>'
                f'</g>'
            )
        else:
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.2f}" fill="{col}" opacity="{base_op:.2f}"{tw}/>')
    parts.append("</g>")
    return "\n    ".join(parts)


def build_realistic_spiral_galaxy(cx: float, cy: float, radius: float, tilt_deg: float, squash: float, seed: int, spin_class: str = "gal-spin") -> str:
    """Procedural logarithmic spiral galaxy (Andromeda/Whirlpool fidelity: bulge, dust puffs, H-II knots, resolved stars)."""
    rng = random.Random(seed)
    clouds: list[str] = []
    dust: list[str] = []
    stars: list[str] = []

    # 2 major + 2 faint secondary logarithmic spiral arms: r = a * exp(b * theta)
    arm_specs = [(0.0, 1.0), (math.pi, 1.0), (math.pi * 0.52, 0.55), (math.pi * 1.52, 0.55)]
    for arm_offset, strength in arm_specs:
        steps = 28 if strength > 0.8 else 16
        for s in range(steps):
            t = (s + 0.5) / steps
            theta = arm_offset + t * 3.8
            r = radius * (0.10 + 0.88 * (t ** 1.15))
            spread = radius * (0.04 + 0.14 * t)
            x = r * math.cos(theta) + rng.gauss(0, spread * 0.4)
            y = r * math.sin(theta) + rng.gauss(0, spread * 0.4)

            # Soft ionized blue-white star-cloud puff
            cloud_r = radius * rng.uniform(0.055, 0.12) * (1.1 - 0.35 * t)
            c_col = "#A8C6ED" if t > 0.32 else "#E8D7BC"
            c_op = strength * rng.uniform(0.035, 0.09) * (1.15 - 0.55 * t)
            clouds.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{cloud_r:.1f}" fill="{c_col}" opacity="{c_op:.3f}"/>')

            # Inner dark interstellar dust knot along primary arms
            if strength > 0.8 and s % 3 == 1 and t < 0.82:
                dr = r * 0.90
                dx = dr * math.cos(theta - 0.08)
                dy = dr * math.sin(theta - 0.08)
                dust.append(f'<circle cx="{dx:.1f}" cy="{dy:.1f}" r="{cloud_r*0.75:.1f}" fill="#140D12" opacity="0.24"/>')

            # Resolved pinpoint stars & occasional H-II star-forming pink-amber region
            for _ in range(3 if strength > 0.8 else 1):
                sx = x + rng.gauss(0, spread * 0.55)
                sy = y + rng.gauss(0, spread * 0.55)
                sr = rng.uniform(0.32, 0.88)
                scol = rng.choices(["#FFFFFF", "#CFE2FF", "#FFF1D6", "#D98A9C"], weights=[32, 40, 20, 8])[0]
                sop = strength * rng.uniform(0.25, 0.85) * (1.1 - 0.45 * t)
                stars.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="{sr:.2f}" fill="{scol}" opacity="{sop:.2f}"/>')

    # Outer diffuse stellar halo specks
    for _ in range(36):
        ang = rng.uniform(0, math.tau)
        rr = radius * (rng.random() ** 0.7) * 1.08
        stars.append(
            f'<circle cx="{rr*math.cos(ang):.1f}" cy="{rr*math.sin(ang):.1f}" r="{rng.uniform(0.3,0.65):.2f}" '
            f'fill="#DCE8FF" opacity="{rng.uniform(0.12,0.45):.2f}"/>'
        )

    return (
        f'<g transform="translate({cx:.1f}, {cy:.1f}) rotate({tilt_deg:.1f}) scale(1, {squash:.2f})">\n'
        f'  <g class="{spin_class}">\n'
        f'    <circle cx="0" cy="0" r="{radius*1.08:.1f}" fill="url(#galHalo)"/>\n'
        f'    <g filter="url(#galBlur)">{"".join(clouds)}{"".join(dust)}</g>\n'
        f'    <ellipse cx="0" cy="0" rx="{radius*0.28:.1f}" ry="{radius*0.21:.1f}" fill="url(#galCore)"/>\n'
        f'    <circle cx="0" cy="0" r="{radius*0.075:.1f}" fill="#FFFDF8" opacity="0.92" filter="url(#softBlur)"/>\n'
        f'    {"".join(stars)}\n'
        f'  </g>\n'
        f'</g>'
    )


def build_edge_on_galaxy(cx: float, cy: float, rx: float, tilt_deg: float) -> str:
    """Sombrero-style (M104) edge-on lenticular galaxy with crisp equatorial dust lane."""
    return (
        f'<g transform="translate({cx:.1f}, {cy:.1f}) rotate({tilt_deg:.1f})" class="drift-slow">\n'
        f'  <ellipse cx="0" cy="0" rx="{rx*1.15:.1f}" ry="{rx*0.34:.1f}" fill="url(#sombreroHalo)"/>\n'
        f'  <ellipse cx="0" cy="0" rx="{rx:.1f}" ry="{rx*0.11:.1f}" fill="url(#sombreroDisk)" opacity="0.9"/>\n'
        f'  <ellipse cx="0" cy="0" rx="{rx*0.32:.1f}" ry="{rx*0.20:.1f}" fill="url(#galCore)" opacity="0.92"/>\n'
        f'  <path d="M {-rx*0.92:.1f} 1.4 Q 0 5.6 {rx*0.92:.1f} 1.4 Q 0 3.2 {-rx*0.92:.1f} 1.4 Z" fill="#07050A" opacity="0.82"/>\n'
        f'</g>'
    )


def build_milky_way_band(width: int, height: int) -> str:
    """Subtle diagonal galactic dust & star-cluster stream weaving continuously from top to bottom."""
    rng = random.Random(777)
    puffs = []
    dust_specks = []
    # Path sweeps from (690, 90) -> (420, 560) -> (260, 1020) -> (560, height-140)
    samples = 46
    for i in range(samples):
        t = i / (samples - 1)
        x = 690 - 440 * math.sin(t * math.pi * 0.85) + 120 * math.sin(t * math.pi * 2.0) * 0.35
        y = 70 + t * (height - 150)
        pr = rng.uniform(55, 110)
        col = rng.choice(["#172947", "#1F2645", "#2B1E33", "#1A324A"])
        op = rng.uniform(0.06, 0.13)
        puffs.append(f'<ellipse cx="{x:.1f}" cy="{y:.1f}" rx="{pr:.1f}" ry="{pr*0.62:.1f}" transform="rotate(-28 {x:.1f} {y:.1f})" fill="{col}" opacity="{op:.3f}"/>')
        for _ in range(4):
            sx = x + rng.gauss(0, 52)
            sy = y + rng.gauss(0, 38)
            if 10 < sx < width - 10 and 10 < sy < height - 10:
                dust_specks.append(
                    f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="{rng.uniform(0.3, 0.65):.2f}" fill="#DCE8FF" opacity="{rng.uniform(0.14, 0.42):.2f}"/>'
                )
    return f'<g filter="url(#nebBlur)">{"".join(puffs)}</g>\n  <g>{"".join(dust_specks)}</g>'


def build_saturn_rings(half: str) -> str:
    """Physically layered multi-band concentric planetary rings with a crisp Cassini Division gap."""
    # (rx, ry, width, color, opacity)
    bands = [
        (110, 29.0, 2.2, "#9AA6B8", 0.32),
        (105, 27.6, 4.4, "#C5BCA9", 0.56),
        (99, 26.0, 3.2, "#DDD4C1", 0.70),
        (94, 24.7, 2.0, "#A99F8E", 0.48),
        # Cassini Division dark gap around rx=88..91
        (84, 22.1, 5.2, "#E3D9C4", 0.82),
        (78, 20.5, 4.2, "#CABEA7", 0.72),
        (72, 18.9, 3.0, "#99938B", 0.46),
        (66, 17.3, 2.2, "#717A8A", 0.25),
    ]
    sweep = 1 if half == "back" else 0
    op_mul = 0.68 if half == "back" else 1.0
    paths = []
    for rx, ry, sw, col, op in bands:
        paths.append(
            f'<path d="M {-rx:.1f} 0 A {rx:.1f} {ry:.1f} 0 0 {sweep} {rx:.1f} 0" '
            f'fill="none" stroke="{col}" stroke-width="{sw:.1f}" stroke-opacity="{op*op_mul:.2f}"/>'
        )
    return "".join(paths)


def render_universe(profile: dict[str, Any], stats: dict[str, Any]) -> str:
    W = 850
    repos = (stats.get("repositories") or [])[:6]
    repo_rows = max(1, math.ceil(len(repos) / 2))

    # Vertical section anchors — all seamlessly unified on ONE continuous deep-space canvas
    Y_HERO = 0
    Y_STACK = 338
    Y_TELEM = 668
    Y_CONTRIB = 966
    Y_REPOS = 1316
    REPOS_H = 62 + repo_rows * 112 + 12
    Y_FOOTER = Y_REPOS + REPOS_H + 18
    H = Y_FOOTER + 104

    # Hero data
    raw_display = str(profile.get("display_name") or profile.get("username", "Developer"))
    raw_username = str(profile.get("username", "SeishiKun9"))
    raw_tagline = str(profile.get("tagline", "Exploring the code cosmos"))
    raw_status = str(profile.get("status", "ONLINE · OPEN TO COLLABORATE"))
    display = esc(raw_display)
    username = esc(raw_username)
    tagline_lines = wrap_text(raw_tagline, 54, 1)
    tagline = esc(tagline_lines[0] if tagline_lines else raw_tagline)
    status = esc(raw_status)
    bio_lines = [esc(wrap_text(line, 62, 1)[0]) for line in (profile.get("bio") or [])[:2] if line.strip()]
    meta = profile.get("meta") or {}

    status_w = max(168, len(raw_status) * 6.7 + 36)
    handle_x = 46 + int(status_w) + 10
    handle_w = max(78, (len(raw_username) + 1) * 7.4 + 18)

    # Hero metadata pills
    meta_items = []
    if meta.get("location"):
        meta_items.append(("pin", str(meta["location"]), C_STAR_BLUE))
    if meta.get("focus"):
        meta_items.append(("spark", str(meta["focus"]), C_STAR_WARM))
    if meta.get("email"):
        meta_items.append(("mail", str(meta["email"]), C_STAR_ROSE))

    hero_pills = []
    px = 46
    for kind, label, accent in meta_items[:3]:
        clean = esc(label)
        pw = max(94, len(label) * 6.8 + 34)
        if px + pw > 530:
            break
        if kind == "pin":
            icon = f'<path d="M{px+14} 259a3.8 3.8 0 1 1 7.6 0c0 2.9-3.8 6.2-3.8 6.2s-3.8-3.3-3.8-6.2zm3.8 1.2a1.3 1.3 0 1 0 0-2.6 1.3 1.3 0 0 0 0 2.6z" fill="{accent}"/>'
        elif kind == "spark":
            icon = f'<path d="M{px+18} 255l1.3 3.4 3.4 1.3-3.4 1.3-1.3 3.4-1.3-3.4-3.4-1.3 3.4-1.3z" fill="{accent}"/>'
        else:
            icon = f'<rect x="{px+12}" y="256" width="11.5" height="8" rx="1.4" fill="none" stroke="{accent}" stroke-width="1.2"/><path d="M{px+12.7} 257l5 3.6 5-3.6" fill="none" stroke="{accent}" stroke-width="1.15"/>'
        hero_pills.append(
            f'<g>'
            f'<rect x="{px}" y="247" width="{pw:.0f}" height="26" rx="6" fill="{C_HUD_BG}" fill-opacity="0.78" stroke="{C_HUD_LINE}" stroke-width="0.9"/>'
            f'{icon}'
            f'<text x="{px+29}" y="264" fill="{C_TEXT_SEC}" font-size="11" class="mono">{clean}</text>'
            f'</g>'
        )
        px += int(pw) + 10

    # Tech stack rows (Sector 02)
    groups = (profile.get("tech_stack") or [])[:4]
    stack_rows = []
    for idx, grp in enumerate(groups):
        ry = Y_STACK + 64 + idx * 58
        cat = esc(grp.get("category", "Stack").upper())
        accent = ASTRO_ACCENTS[idx % len(ASTRO_ACCENTS)]
        stack_rows.append(
            f'<g>'
            f'<circle cx="332" cy="{ry - 4}" r="2.8" fill="{accent}"/>'
            f'<text x="344" y="{ry}" fill="{C_TEXT_MUTED}" font-size="10" font-weight="700" letter-spacing="1.4" class="mono">{cat}</text>'
            f'</g>'
        )
        tx = 332
        ty = ry + 11
        for item in (grp.get("items") or [])[:6]:
            label = esc(item)
            pw = max(62, int(len(str(item)) * 7.0 + 24))
            if tx + pw > W - 36:
                break
            stack_rows.append(
                f'<g>'
                f'<rect x="{tx}" y="{ty}" width="{pw}" height="25" rx="5" fill="{C_HUD_BG}" fill-opacity="0.78" stroke="{C_HUD_LINE}" stroke-width="0.9"/>'
                f'<circle cx="{tx + 11}" cy="{ty + 12.5}" r="2.4" fill="{accent}"/>'
                f'<text x="{tx + 20}" y="{ty + 16.5}" fill="{C_TEXT_PRI}" font-size="11.2" font-weight="500" class="sans">{label}</text>'
                f'</g>'
            )
            tx += pw + 8

    # Telemetry (Sector 03)
    streak = stats["current_streak"]
    best = stats["longest_streak"]
    live_badge = f"LIVE TELEMETRY · {stats['updated_at']}" if stats["live"] else "PREVIEW TELEMETRY · SYNC VIA ACTION"
    badge_color = C_STATUS_OK if stats["live"] else C_STAR_WARM

    gauge_r = 50
    gauge_circ = 2 * math.pi * gauge_r
    gauge_ratio = min(1.0, max(0.14, streak / 30.0)) if streak > 0 else 0.08
    gauge_dash = gauge_circ * gauge_ratio

    # Astrolabe tick marks around streak gauge
    astro_ticks = []
    for deg in range(0, 360, 10):
        rad = math.radians(deg)
        inner = 60 if deg % 30 == 0 else 62.5
        outer = 66.5
        astro_ticks.append(
            f'<line x1="{inner*math.cos(rad):.1f}" y1="{inner*math.sin(rad):.1f}" '
            f'x2="{outer*math.cos(rad):.1f}" y2="{outer*math.sin(rad):.1f}" '
            f'stroke="{C_STAR_BLUE}" stroke-opacity="{0.52 if deg % 30 == 0 else 0.22}" stroke-width="{1.0 if deg % 30 == 0 else 0.6}"/>'
        )

    telem_cards = [
        ("COMMITS (YEAR)", fmt_num(stats["commits"]), "Code transmissions", C_STAR_BLUE, "commit"),
        ("CONTRIBUTIONS", fmt_num(stats["contributions"]), "365-day activity", C_STAR_ICE, "nova"),
        ("PRs & ISSUES", f"{fmt_num(stats['prs'])} / {fmt_num(stats['issues'])}", f"{fmt_num(stats['reviews'])} reviews", C_STAR_ROSE, "pr"),
        ("STARS & REPOS", f"{fmt_num(stats['stars'])} / {fmt_num(stats['repo_count'])}", f"{fmt_num(stats['followers'])} followers", C_STAR_WARM, "star"),
    ]
    telem_cards_svg = []
    for idx, (label, val, sub, accent, kind) in enumerate(telem_cards):
        col, row = idx % 2, idx // 2
        x = 236 + col * 294
        y = Y_TELEM + 58 + row * 62
        cw, ch = 280, 52
        if kind == "commit":
            icon = f'<circle cx="{x+22}" cy="{y+26}" r="4.2" fill="none" stroke="{accent}" stroke-width="1.5"/><line x1="{x+11}" y1="{y+26}" x2="{x+17.8}" y2="{y+26}" stroke="{accent}" stroke-width="1.5"/><line x1="{x+26.2}" y1="{y+26}" x2="{x+33}" y2="{y+26}" stroke="{accent}" stroke-width="1.5"/>'
        elif kind == "nova":
            icon = f'<path d="M{x+22} {y+17}l1.9 5.9 5.9 1.9-5.9 1.9-1.9 5.9-1.9-5.9-5.9-1.9 5.9-1.9z" fill="{accent}"/>'
        elif kind == "pr":
            icon = f'<circle cx="{x+17}" cy="{y+19}" r="2.4" fill="none" stroke="{accent}" stroke-width="1.4"/><circle cx="{x+17}" cy="{y+33}" r="2.4" fill="none" stroke="{accent}" stroke-width="1.4"/><circle cx="{x+27}" cy="{y+33}" r="2.4" fill="none" stroke="{accent}" stroke-width="1.4"/><line x1="{x+17}" y1="{y+21.4}" x2="{x+17}" y2="{y+30.6}" stroke="{accent}" stroke-width="1.4"/><path d="M{x+19.5} {y+19}h3.5a4 4 0 0 1 4 4v7.6" fill="none" stroke="{accent}" stroke-width="1.4"/>'
        else:
            icon = f'<path d="M{x+22} {y+16.5}l2.3 4.9 5.4.8-3.9 3.8.9 5.4-4.7-2.5-4.7 2.5.9-5.4-3.9-3.8 5.4-.8z" fill="{accent}"/>'
        telem_cards_svg.append(
            f'<g>'
            f'<rect x="{x}" y="{y}" width="{cw}" height="{ch}" rx="8" fill="{C_HUD_BG}" fill-opacity="0.76" stroke="{C_HUD_LINE}" stroke-width="0.9"/>'
            f'{hud_crosshairs(x, y, cw, ch, 3.5)}'
            f'<rect x="{x+1}" y="{y+10}" width="2.2" height="{ch-20}" rx="1" fill="{accent}"/>'
            f'{icon}'
            f'<text x="{x+43}" y="{y+20}" fill="{C_TEXT_MUTED}" font-size="9.5" font-weight="700" letter-spacing="1.1" class="mono">{esc(label)}</text>'
            f'<text x="{x+43}" y="{y+40}" fill="{C_TEXT_PRI}" font-size="18" font-weight="700" class="sans">{esc(val)}</text>'
            f'<text x="{x+cw-14}" y="{y+38}" text-anchor="end" fill="{C_TEXT_MUTED}" font-size="10" class="mono">{esc(sub)}</text>'
            f'</g>'
        )

    # Language spectrograph
    langs = stats.get("top_languages") or []
    bar_x, bar_y, bar_w, bar_h = 46, Y_TELEM + 210, 764, 9
    total_pct = sum(l["pct"] for l in langs) or 100.0
    lang_segs, lang_leg = [], []
    cur_x = float(bar_x)
    lx = 46
    if not langs:
        lang_leg.append(f'<text x="46" y="{bar_y+30}" fill="{C_TEXT_MUTED}" font-size="11" class="mono">No public language telemetry yet</text>')
    for i, lang in enumerate(langs[:6]):
        seg_w = (lang["pct"] / total_pct) * bar_w
        if i == len(langs[:6]) - 1:
            seg_w = max(0.0, (bar_x + bar_w) - cur_x)
        col = lang.get("color") or C_STAR_BLUE
        lang_segs.append(f'<rect x="{cur_x:.1f}" y="{bar_y}" width="{seg_w:.1f}" height="{bar_h}" fill="{col}"/>')
        cur_x += seg_w
        text_l = f"{lang['name']} {lang['pct']:.1f}%"
        item_w = int(len(text_l) * 7.0 + 22)
        if lx + item_w <= W - 36:
            lang_leg.append(
                f'<g><circle cx="{lx + 4}" cy="{bar_y + 26}" r="3.4" fill="{col}"/>'
                f'<text x="{lx + 12}" y="{bar_y + 30}" fill="{C_TEXT_SEC}" font-size="11" class="mono">{esc(text_l)}</text></g>'
            )
            lx += item_w + 8

    # Contributions Starfield & 30-day wave (Sector 04)
    weeks = (stats.get("weeks") or [])[-53:]
    flat = [d for w in weeks for d in w.get("contributionDays") or []]
    max_day = max((d["contributionCount"] for d in flat), default=1) or 1
    gx, gy = 62, Y_CONTRIB + 68
    step, cell = 14, 10.5
    # Authentic deep-space stellar brightness ramp (obsidian -> deep sapphire -> nebula blue -> starlight ice -> bright white star)
    levels = ["#0B1020", "#192D4E", "#2C5587", "#67A0D6", "#E2F0FF"]
    cells_svg, months_svg = [], []
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
            cls = f' class="tw{(wi + wd) % 3 + 1}"' if lvl == 4 else ""
            extra = ' filter="url(#softBlur)"' if lvl == 4 else (' stroke="#16223C" stroke-width="0.6"' if lvl == 0 else "")
            cells_svg.append(
                f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2" fill="{levels[lvl]}"{cls}{extra}/>'
            )

    last30 = flat[-30:] if len(flat) >= 2 else [{"date": "2026-01-01", "contributionCount": 0}, {"date": "2026-01-02", "contributionCount": 0}]
    wx, wy, ww, wh = 62, Y_CONTRIB + 210, 742, 74
    wmax = max((d["contributionCount"] for d in last30), default=1) or 1
    pts = []
    for i, d in enumerate(last30):
        px_w = wx + (i / max(1, len(last30) - 1)) * ww
        py_w = wy + wh - (d["contributionCount"] / wmax) * (wh - 12) - 4
        pts.append((px_w, py_w, d["contributionCount"]))
    path_d = f"M {pts[0][0]:.1f} {pts[0][1]:.1f}"
    for i in range(1, len(pts)):
        x0, y0, _ = pts[i - 1]
        x1, y1, _ = pts[i]
        mx = (x0 + x1) / 2.0
        path_d += f" C {mx:.1f} {y0:.1f}, {mx:.1f} {y1:.1f}, {x1:.1f} {y1:.1f}"
    area_d = f"{path_d} L {pts[-1][0]:.1f} {wy + wh} L {pts[0][0]:.1f} {wy + wh} Z"
    peak_dots = [
        f'<circle cx="{px_w:.1f}" cy="{py_w:.1f}" r="2.8" fill="#E8F4FF" class="tw{(i % 3) + 1}" filter="url(#softBlur)"/>'
        for i, (px_w, py_w, cnt) in enumerate(pts)
        if cnt >= wmax * 0.65 and cnt > 0
    ]
    last30_total = sum(d["contributionCount"] for d in last30)
    legend_cells = "".join(f'<rect x="{704 + i * 15}" y="{Y_CONTRIB + 174}" width="10.5" height="10.5" rx="2" fill="{col}"/>' for i, col in enumerate(levels))

    # Repositories Star Chart (Sector 05)
    card_w, card_h = 372, 96
    gap_x, gap_y = 20, 16
    r_start_x, r_start_y = 46, Y_REPOS + 54
    centers = []
    for idx in range(len(repos)):
        col, row = idx % 2, idx // 2
        centers.append((r_start_x + col * (card_w + gap_x) + card_w / 2, r_start_y + row * (card_h + gap_y) + card_h / 2))
    constellation_lines = [
        f'<line x1="{centers[i][0]:.1f}" y1="{centers[i][1]:.1f}" x2="{centers[i+1][0]:.1f}" y2="{centers[i+1][1]:.1f}" '
        f'stroke="{C_STAR_BLUE}" stroke-opacity="0.22" stroke-width="0.9" stroke-dasharray="3 6"/>'
        for i in range(len(centers) - 1)
    ]
    repo_cards = []
    if not repos:
        repo_cards.append(
            f'<rect x="{r_start_x}" y="{r_start_y}" width="{W - 2*r_start_x}" height="90" rx="8" fill="{C_HUD_BG}" fill-opacity="0.76" stroke="{C_HUD_LINE}" stroke-width="0.9"/>'
            f'<text x="{W/2:.0f}" y="{r_start_y + 49}" text-anchor="middle" fill="{C_TEXT_MUTED}" font-size="12.5" class="mono">No public repositories charted yet — launch your first mission.</text>'
        )
    for idx, repo in enumerate(repos):
        col, row = idx % 2, idx // 2
        x = r_start_x + col * (card_w + gap_x)
        y = r_start_y + row * (card_h + gap_y)
        name = repo.get("name", "repository")
        if len(name) > 28:
            name = name[:27] + "…"
        desc_lines = wrap_text(repo.get("description") or "Exploring new frontiers in this repository.", 47, 2)
        lang_obj = repo.get("primaryLanguage") or {}
        lang_name = lang_obj.get("name") or "Code"
        lang_color = lang_obj.get("color") or LANG_COLORS.get(lang_name, C_STAR_BLUE)
        stars = fmt_num(int(repo.get("stargazerCount", 0)))
        forks = fmt_num(int(repo.get("forkCount", 0)))
        desc_svg = "".join(
            f'<text x="{x+18}" y="{y+45 + li * 16}" fill="{C_TEXT_SEC}" font-size="11.3" class="sans">{esc(line)}</text>'
            for li, line in enumerate(desc_lines)
        )
        repo_cards.append(
            f'<g>'
            f'<rect x="{x}" y="{y}" width="{card_w}" height="{card_h}" rx="8" fill="{C_HUD_BG}" fill-opacity="0.78" stroke="{C_HUD_LINE}" stroke-width="0.9"/>'
            f'{hud_crosshairs(x, y, card_w, card_h, 3.5)}'
            f'<path d="M{x+18} {y+15}h9.5a1.4 1.4 0 0 1 1.4 1.4v9.6a1.4 1.4 0 0 1-1.4 1.4H{x+18}a1.4 1.4 0 0 1-1.4-1.4v-9.6A1.4 1.4 0 0 1 {x+18} {y+15}zm1 2v7.8h7.5v-7.8z" fill="{C_STAR_BLUE}"/>'
            f'<text x="{x+35}" y="{y+26}" fill="{C_TEXT_PRI}" font-size="13.8" font-weight="700" class="sans">{esc(name)}</text>'
            f'<circle cx="{x+card_w-16}" cy="{y+21}" r="2.4" fill="{lang_color}" class="tw{(idx % 3) + 1}"/>'
            f'{desc_svg}'
            f'<circle cx="{x+21}" cy="{y+80}" r="3.6" fill="{lang_color}"/>'
            f'<text x="{x+30}" y="{y+84}" fill="{C_TEXT_MUTED}" font-size="10.8" class="mono">{esc(lang_name)}</text>'
            f'<path d="M{x+238} {y+74}l1.7 3.5 3.8.5-2.8 2.7.7 3.8-3.4-1.8-3.4 1.8.7-3.8-2.8-2.7 3.8-.5z" fill="{C_STAR_WARM}"/>'
            f'<text x="{x+248}" y="{y+84}" fill="{C_TEXT_SEC}" font-size="10.8" class="mono">{stars}</text>'
            f'<circle cx="{x+308} {y+76}" r="1.9" fill="none" stroke="{C_STAR_BLUE}" stroke-width="1.2"/>'.replace(f'cx="{x+308} {y+76}"', f'cx="{x+308}" cy="{y+76}"') +
            f'<circle cx="{x+316}" cy="{y+76}" r="1.9" fill="none" stroke="{C_STAR_BLUE}" stroke-width="1.2"/>'
            f'<circle cx="{x+312}" cy="{y+84}" r="1.9" fill="none" stroke="{C_STAR_BLUE}" stroke-width="1.2"/>'
            f'<path d="M{x+308} {y+78}v2h8v-2M{x+312} {y+80}v2" fill="none" stroke="{C_STAR_BLUE}" stroke-width="1.2"/>'
            f'<text x="{x+323}" y="{y+84}" fill="{C_TEXT_SEC}" font-size="10.8" class="mono">{forks}</text>'
            f'</g>'
        )

    # Orbital animation keyframes for realistic moons & wandering parallax stars
    saturn_cx, saturn_cy = 708, 198
    terra_cx, terra_cy = 164, Y_STACK + 158

    kf_css = "\n".join([
        orbit_keyframes("saturnMoon", saturn_cx, saturn_cy, 118, 32, -16, start_deg=25, steps=28),
        orbit_keyframes("terraMoon1", terra_cx, terra_cy, 74, 24, -15, start_deg=15, steps=24),
        orbit_keyframes("terraMoon2", terra_cx, terra_cy, 104, 34, -15, start_deg=195, steps=24),
        orbit_keyframes("terraProbe", terra_cx, terra_cy, 128, 42, -15, start_deg=105, steps=24),
    ])

    footer_text = esc(profile.get("footer_text", "TRANSMISSION OPEN · EXPLORE THE REPOSITORIES ABOVE"))

    # Continuous vertical star-chart spine connecting every sector
    spine_nodes = [
        (22, 46, "01"),
        (22, Y_STACK + 24, "02"),
        (22, Y_TELEM + 24, "03"),
        (22, Y_CONTRIB + 24, "04"),
        (22, Y_REPOS + 24, "05"),
    ]
    spine_svg = [
        f'<line x1="22" y1="46" x2="22" y2="{Y_FOOTER + 46}" stroke="{C_HUD_LINE}" stroke-width="0.9" stroke-opacity="0.7"/>'
    ]
    for sx, sy, code in spine_nodes:
        spine_svg.append(
            f'<g>'
            f'<circle cx="{sx}" cy="{sy}" r="4.5" fill="{C_VOID_1}" stroke="{C_STAR_BLUE}" stroke-width="1"/>'
            f'<circle cx="{sx}" cy="{sy}" r="1.8" fill="{C_STAR_ICE}"/>'
            f'<line x1="{sx+5}" y1="{sy}" x2="40" y2="{sy}" stroke="{C_HUD_LINE}" stroke-width="0.8" stroke-opacity="0.7"/>'
            f'</g>'
        )

    # Traveling faint telemetry pulse gliding continuously down the connecting spine
    css = f"""
    .sans {{ font-family: {FONT_SANS}; }}
    .mono {{ font-family: {FONT_MONO}; }}
    @keyframes twinkleA {{ 0%, 100% {{ opacity: 0.25; }} 50% {{ opacity: 1; }} }}
    @keyframes twinkleB {{ 0%, 100% {{ opacity: 0.92; }} 50% {{ opacity: 0.22; }} }}
    @keyframes twinkleC {{ 0%, 100% {{ opacity: 0.45; }} 40% {{ opacity: 0.95; }} 75% {{ opacity: 0.18; }} }}
    @keyframes wanderFar {{ from {{ transform: translateX(0px); }} to {{ transform: translateX(-850px); }} }}
    @keyframes wanderMid {{ from {{ transform: translate(0px, 0px); }} to {{ transform: translate(850px, -420px); }} }}
    @keyframes wanderNear {{
      0% {{ transform: translate(0px, 0px); }}
      25% {{ transform: translate(-22px, 11px); }}
      50% {{ transform: translate(-36px, -8px); }}
      75% {{ transform: translate(-14px, -16px); }}
      100% {{ transform: translate(0px, 0px); }}
    }}
    @keyframes galSpin {{ from {{ transform: rotate(0deg); }} to {{ transform: rotate(360deg); }} }}
    @keyframes driftSlow {{ 0%, 100% {{ transform: translate(0px, 0px); }} 50% {{ transform: translate(-8px, 4px); }} }}
    @keyframes nebulaBreath {{ 0%, 100% {{ opacity: 0.72; }} 50% {{ opacity: 0.95; }} }}
    @keyframes pulseDot {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.42; }} }}
    @keyframes pulseRing {{ 0% {{ opacity: 0.65; transform: scale(0.9); }} 100% {{ opacity: 0; transform: scale(2.3); }} }}
    @keyframes blink {{ 0%, 49% {{ opacity: 1; }} 50%, 100% {{ opacity: 0; }} }}
    @keyframes scanBar {{ 0% {{ transform: translateX(-140px); opacity: 0; }} 20% {{ opacity: 0.55; }} 80% {{ opacity: 0.55; }} 100% {{ transform: translateX(840px); opacity: 0; }} }}
    @keyframes spinePulse {{ 0% {{ transform: translateY(46px); opacity: 0; }} 8% {{ opacity: 0.9; }} 92% {{ opacity: 0.9; }} 100% {{ transform: translateY({Y_FOOTER + 38}px); opacity: 0; }} }}
    @keyframes cometSweep {{ 0% {{ transform: translateX(-90px); opacity: 0; }} 10% {{ opacity: 0.9; }} 88% {{ opacity: 0.9; }} 100% {{ transform: translateX(780px); opacity: 0; }} }}
    @keyframes meteorA {{
      0%, 76% {{ transform: translate(0px, 0px); opacity: 0; }}
      79% {{ opacity: 0.9; }}
      88% {{ transform: translate(-220px, 88px); opacity: 0; }}
      100% {{ transform: translate(-220px, 88px); opacity: 0; }}
    }}
    @keyframes meteorB {{
      0%, 34% {{ transform: translate(0px, 0px); opacity: 0; }}
      37% {{ opacity: 0.75; }}
      45% {{ transform: translate(-190px, 74px); opacity: 0; }}
      100% {{ transform: translate(-190px, 74px); opacity: 0; }}
    }}
    @keyframes meteorC {{
      0%, 56% {{ transform: translate(0px, 0px); opacity: 0; }}
      59% {{ opacity: 0.7; }}
      67% {{ transform: translate(-175px, 70px); opacity: 0; }}
      100% {{ transform: translate(-175px, 70px); opacity: 0; }}
    }}
    {kf_css}
    .tw1 {{ animation: twinkleA 4.2s ease-in-out infinite; }}
    .tw2 {{ animation: twinkleB 5.6s ease-in-out infinite; }}
    .tw3 {{ animation: twinkleC 6.8s ease-in-out infinite; }}
    .wander-far {{ animation: wanderFar 165s linear infinite; }}
    .wander-mid {{ animation: wanderMid 96s linear infinite; }}
    .wander-near {{ animation: wanderNear 68s ease-in-out infinite; }}
    .gal-spin {{ animation: galSpin 210s linear infinite; }}
    .gal-spin-rev {{ animation: galSpin 260s linear infinite reverse; }}
    .astro-spin {{ animation: galSpin 90s linear infinite; }}
    .drift-slow {{ animation: driftSlow 26s ease-in-out infinite; }}
    .nebula-breath {{ animation: nebulaBreath 14s ease-in-out infinite; }}
    .status-pulse {{ animation: pulseRing 2.6s ease-out infinite; }}
    .status-dot {{ animation: pulseDot 2.6s ease-in-out infinite; }}
    .blink {{ animation: blink 1.15s steps(1, end) infinite; }}
    .scan-bar {{ animation: scanBar 6.5s ease-in-out infinite; }}
    .spine-pulse {{ animation: spinePulse 14s linear infinite; }}
    .comet {{ animation: cometSweep 12s ease-in-out infinite; }}
    .meteor-a {{ animation: meteorA 13s ease-out infinite; }}
    .meteor-b {{ animation: meteorB 18s ease-out infinite; }}
    .meteor-c {{ animation: meteorC 22s ease-out infinite; }}
    .saturn-moon {{ animation: saturnMoon 21s linear infinite; }}
    .terra-moon-1 {{ animation: terraMoon1 15s linear infinite; }}
    .terra-moon-2 {{ animation: terraMoon2 24s linear infinite; }}
    .terra-probe {{ animation: terraProbe 31s linear infinite; }}
    @media (prefers-reduced-motion: reduce) {{
      * {{ animation: none !important; transition: none !important; }}
    }}
    """

    bio_markup = "".join(
        f'<text x="46" y="{190 + idx * 22}" fill="{C_TEXT_SEC}" font-size="13.3" class="sans">{line}</text>'
        for idx, line in enumerate(bio_lines)
    )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="u-title u-desc">
  <title id="u-title">{display} — Deep Space GitHub Profile</title>
  <desc id="u-desc">{tagline}. Continuous deep-space profile featuring wandering parallax starfields, procedural nebulae, realistic spiral and edge-on galaxies, ringed gas giant, terrestrial exoplanet, tech stack, GitHub telemetry, contribution starfield, and repositories.</desc>
  <defs>
    <!-- Deep obsidian space backdrop -->
    <linearGradient id="spaceBg" x1="0" y1="0" x2="0.3" y2="1">
      <stop offset="0%" stop-color="{C_VOID_0}"/>
      <stop offset="35%" stop-color="{C_VOID_1}"/>
      <stop offset="72%" stop-color="{C_VOID_2}"/>
      <stop offset="100%" stop-color="{C_VOID_0}"/>
    </linearGradient>

    <linearGradient id="outerBorder" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#334B73" stop-opacity="0.7"/>
      <stop offset="50%" stop-color="#1E2C47" stop-opacity="0.5"/>
      <stop offset="100%" stop-color="#4A5A75" stop-opacity="0.65"/>
    </linearGradient>

    <linearGradient id="nameGrad" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#FFFFFF"/>
      <stop offset="65%" stop-color="#DCEBFF"/>
      <stop offset="100%" stop-color="#B8D0EC"/>
    </linearGradient>

    <!-- Realistic Galaxy Core & Halos -->
    <radialGradient id="galCore" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#FFFDF6" stop-opacity="1"/>
      <stop offset="28%" stop-color="#F1DCB7" stop-opacity="0.82"/>
      <stop offset="62%" stop-color="#8FAED8" stop-opacity="0.28"/>
      <stop offset="100%" stop-color="#4A6B9C" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="galHalo" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#A8C4E8" stop-opacity="0.24"/>
      <stop offset="52%" stop-color="#3E5C8A" stop-opacity="0.09"/>
      <stop offset="100%" stop-color="#14233C" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="sombreroHalo" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#EED9B5" stop-opacity="0.34"/>
      <stop offset="50%" stop-color="#6F8AB5" stop-opacity="0.1"/>
      <stop offset="100%" stop-color="#1A2640" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="sombreroDisk" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#9BB6DB" stop-opacity="0"/>
      <stop offset="22%" stop-color="#C8D7EC" stop-opacity="0.62"/>
      <stop offset="50%" stop-color="#FFF5E0" stop-opacity="0.95"/>
      <stop offset="78%" stop-color="#C8D7EC" stop-opacity="0.62"/>
      <stop offset="100%" stop-color="#9BB6DB" stop-opacity="0"/>
    </linearGradient>

    <!-- Photorealistic Ringed Gas Giant (Saturn-like chiaroscuro lighting from upper-left) -->
    <radialGradient id="saturnBase" cx="28%" cy="24%" r="74%">
      <stop offset="0%" stop-color="#E7DEC9"/>
      <stop offset="28%" stop-color="#C2B193"/>
      <stop offset="58%" stop-color="#6D6A6B"/>
      <stop offset="82%" stop-color="#1F2433"/>
      <stop offset="100%" stop-color="#03050B"/>
    </radialGradient>
    <radialGradient id="terminatorShadow" cx="25%" cy="22%" r="76%">
      <stop offset="0%" stop-color="#000000" stop-opacity="0"/>
      <stop offset="46%" stop-color="#03050B" stop-opacity="0.12"/>
      <stop offset="70%" stop-color="#02040A" stop-opacity="0.72"/>
      <stop offset="100%" stop-color="#010206" stop-opacity="0.97"/>
    </radialGradient>
    <radialGradient id="saturnRim" cx="22%" cy="20%" r="72%">
      <stop offset="78%" stop-color="#BBD7F5" stop-opacity="0"/>
      <stop offset="94%" stop-color="#D8E8FA" stop-opacity="0.32"/>
      <stop offset="100%" stop-color="#FFFFFF" stop-opacity="0.48"/>
    </radialGradient>

    <!-- Photorealistic Terrestrial Ocean & Cloud World -->
    <radialGradient id="terraOcean" cx="26%" cy="24%" r="74%">
      <stop offset="0%" stop-color="#4A8BC2"/>
      <stop offset="34%" stop-color="#1E4E82"/>
      <stop offset="65%" stop-color="#0B2242"/>
      <stop offset="86%" stop-color="#040B1A"/>
      <stop offset="100%" stop-color="#020409"/>
    </radialGradient>
    <radialGradient id="terraAtmo" cx="42%" cy="40%" r="54%">
      <stop offset="78%" stop-color="#78B4F2" stop-opacity="0"/>
      <stop offset="93%" stop-color="#8BC4FA" stop-opacity="0.35"/>
      <stop offset="100%" stop-color="#4A8BD9" stop-opacity="0"/>
    </radialGradient>

    <!-- Realistic Half-Lit Rocky Moon & Distant Mars-like World -->
    <radialGradient id="rockMoon" cx="28%" cy="26%" r="72%">
      <stop offset="0%" stop-color="#DBD7CE"/>
      <stop offset="45%" stop-color="#8B8985"/>
      <stop offset="76%" stop-color="#22252D"/>
      <stop offset="100%" stop-color="#05070C"/>
    </radialGradient>
    <radialGradient id="rustPlanet" cx="26%" cy="24%" r="74%">
      <stop offset="0%" stop-color="#C98D6B"/>
      <stop offset="42%" stop-color="#7D4937"/>
      <stop offset="74%" stop-color="#291716"/>
      <stop offset="100%" stop-color="#040509"/>
    </radialGradient>

    <!-- Realistic Gravitational Lens / Black Hole Accretion Disk (Bottom Horizon) -->
    <radialGradient id="bhHalo" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#000000" stop-opacity="1"/>
      <stop offset="32%" stop-color="#000000" stop-opacity="1"/>
      <stop offset="38%" stop-color="#FFF2D6" stop-opacity="0.88"/>
      <stop offset="48%" stop-color="#D49556" stop-opacity="0.36"/>
      <stop offset="72%" stop-color="#5B3624" stop-opacity="0.1"/>
      <stop offset="100%" stop-color="#000000" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="accretionDisk" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#8A522B" stop-opacity="0"/>
      <stop offset="22%" stop-color="#D99B58" stop-opacity="0.65"/>
      <stop offset="50%" stop-color="#FFF5DF" stop-opacity="0.95"/>
      <stop offset="78%" stop-color="#C98648" stop-opacity="0.6"/>
      <stop offset="100%" stop-color="#8A522B" stop-opacity="0"/>
    </linearGradient>

    <!-- Telemetry & Meteor Gradients -->
    <linearGradient id="meteorGrad" x1="0" y1="1" x2="1" y2="0">
      <stop offset="0%" stop-color="#FFFFFF"/>
      <stop offset="24%" stop-color="#BFD8FA" stop-opacity="0.72"/>
      <stop offset="100%" stop-color="#7EA6D8" stop-opacity="0"/>
    </linearGradient>
    <linearGradient id="cometTail" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#88B4E8" stop-opacity="0"/>
      <stop offset="74%" stop-color="#C8E0FA" stop-opacity="0.58"/>
      <stop offset="100%" stop-color="#FFFFFF" stop-opacity="0.96"/>
    </linearGradient>
    <linearGradient id="arcGrad" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#CBE2FF"/>
      <stop offset="55%" stop-color="#7CAEE8"/>
      <stop offset="100%" stop-color="#E8CFA6"/>
    </linearGradient>
    <linearGradient id="waveStroke" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#6B8DC2"/>
      <stop offset="50%" stop-color="#BBD8FA"/>
      <stop offset="100%" stop-color="#DFC49C"/>
    </linearGradient>
    <linearGradient id="waveFill" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#7FAEE6" stop-opacity="0.28"/>
      <stop offset="100%" stop-color="#10203E" stop-opacity="0.01"/>
    </linearGradient>
    <linearGradient id="sheen" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#FFFFFF" stop-opacity="0"/>
      <stop offset="50%" stop-color="#FFFFFF" stop-opacity="0.4"/>
      <stop offset="100%" stop-color="#FFFFFF" stop-opacity="0"/>
    </linearGradient>

    <!-- Procedural Interstellar Nebula & Planet Cloud Filters (high-contrast wispy gas filaments) -->
    <filter id="nebTexBlue" x="-10%" y="-10%" width="120%" height="120%">
      <feTurbulence type="fractalNoise" baseFrequency="0.0068" numOctaves="4" seed="17" result="noise"/>
      <feColorMatrix in="noise" type="matrix" values="0 0 0 0 0.14  0 0 0 0 0.30  0 0 0 0 0.52  0 0 0 0.95 -0.38"/>
    </filter>
    <filter id="nebTexWarm" x="-10%" y="-10%" width="120%" height="120%">
      <feTurbulence type="fractalNoise" baseFrequency="0.0078" numOctaves="4" seed="43" result="noise"/>
      <feColorMatrix in="noise" type="matrix" values="0 0 0 0 0.48  0 0 0 0 0.22  0 0 0 0 0.28  0 0 0 0.88 -0.37"/>
    </filter>
    <filter id="terraLand" x="0%" y="0%" width="100%" height="100%">
      <feTurbulence type="fractalNoise" baseFrequency="0.032" numOctaves="3" seed="29" result="l"/>
      <feColorMatrix in="l" type="matrix" values="0 0 0 0 0.28  0 0 0 0 0.42  0 0 0 0 0.34  0 0 0 1.45 -0.76"/>
    </filter>
    <filter id="terraClouds" x="0%" y="0%" width="100%" height="100%">
      <feTurbulence type="fractalNoise" baseFrequency="0.042 0.088" numOctaves="3" seed="11" result="c"/>
      <feColorMatrix in="c" type="matrix" values="0 0 0 0 0.94  0 0 0 0 0.96  0 0 0 0 1.0  0 0 0 1.15 -0.52"/>
    </filter>
    <filter id="saturnBands" x="0%" y="0%" width="100%" height="100%">
      <feTurbulence type="fractalNoise" baseFrequency="0.015 0.14" numOctaves="2" seed="7" result="b"/>
      <feColorMatrix in="b" type="matrix" values="0 0 0 0 0.85  0 0 0 0 0.76  0 0 0 0 0.62  0 0 0 0.36 -0.06"/>
    </filter>
    <filter id="galBlur" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="3.4"/>
    </filter>
    <filter id="nebBlur" x="-25%" y="-25%" width="150%" height="150%">
      <feGaussianBlur stdDeviation="24"/>
    </filter>
    <filter id="softBlur" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur stdDeviation="1.8" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>

    <!-- Masks for Organic Nebula Fades & Physically Accurate Planet Ring Shadow -->
    <radialGradient id="maskFade" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#FFFFFF" stop-opacity="1"/>
      <stop offset="55%" stop-color="#FFFFFF" stop-opacity="0.5"/>
      <stop offset="100%" stop-color="#FFFFFF" stop-opacity="0"/>
    </radialGradient>
    <mask id="nebMask1"><ellipse cx="640" cy="210" rx="340" ry="220" fill="url(#maskFade)"/></mask>
    <mask id="nebMask2"><ellipse cx="210" cy="640" rx="310" ry="230" fill="url(#maskFade)"/></mask>
    <mask id="nebMask3"><ellipse cx="620" cy="1180" rx="350" ry="260" fill="url(#maskFade)"/></mask>
    <mask id="ringShadowMask" maskUnits="userSpaceOnUse" x="-130" y="-45" width="260" height="90">
      <rect x="-130" y="-45" width="260" height="90" fill="#FFFFFF"/>
      <path d="M 16 -34 L 120 -26 L 120 4 L 36 2 Z" fill="#222222"/>
    </mask>

    <!-- Seamless Tiled Wandering Starfields (Horizontal + 2D Diagonal Parallax) -->
    {build_star_tile("starsFar", W, H, 195, seed=1001, r_range=(0.35, 0.78), with_spikes=0)}
    {build_star_tile("starsMid", W, 420, 42, seed=2002, r_range=(0.60, 1.15), with_spikes=0)}
    {build_star_tile("starsNear", W, H, 30, seed=3003, r_range=(0.95, 1.65), with_spikes=10)}

    <!-- Clips -->
    <clipPath id="canvasClip"><rect x="1" y="1" width="{W-2}" height="{H-2}" rx="16"/></clipPath>
    <clipPath id="saturnClip"><circle cx="{saturn_cx}" cy="{saturn_cy}" r="48"/></clipPath>
    <clipPath id="terraClip"><circle cx="{terra_cx}" cy="{terra_cy}" r="45"/></clipPath>
    <clipPath id="langBarClip"><rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" rx="4.5"/></clipPath>
    <clipPath id="calGridClip"><rect x="{gx}" y="{gy - 4}" width="{53 * step}" height="{7 * step + 8}"/></clipPath>

    <style>{css}</style>
  </defs>

  <g clip-path="url(#canvasClip)">
    <!-- 1. OBSIDIAN DEEP SPACE VOID -->
    <rect width="{W}" height="{H}" fill="url(#spaceBg)"/>

    <!-- 2. CONTINUOUS MILKY WAY DUST BAND + PROCEDURAL GASEOUS NEBULAE -->
    {build_milky_way_band(W, H)}
    <g class="nebula-breath">
      <rect x="280" y="0" width="570" height="440" filter="url(#nebTexBlue)" mask="url(#nebMask1)"/>
      <rect x="0" y="380" width="540" height="500" filter="url(#nebTexWarm)" mask="url(#nebMask2)"/>
      <rect x="260" y="900" width="590" height="560" filter="url(#nebTexBlue)" mask="url(#nebMask3)"/>
    </g>

    <!-- 3. THREE-LAYER WANDERING PARALLAX STARFIELDS (MULTI-DIRECTIONAL SEAMLESS DRIFT) -->
    <g class="wander-far">
      <use href="#starsFar" x="0" y="0"/>
      <use href="#starsFar" x="{W}" y="0"/>
    </g>
    <g class="wander-mid">
      {"".join(f'<use href="#starsMid" x="{tx}" y="{ty}"/>' for tx in (-W, 0) for ty in range(0, H + 420, 420))}
    </g>
    <g class="wander-near">
      <use href="#starsNear" x="15" y="0"/>
    </g>

    <!-- Subtle High-Altitude Meteors -->
    <g class="meteor-a">
      <line x1="620" y1="24" x2="688" y2="-4" stroke="url(#meteorGrad)" stroke-width="1.3" stroke-linecap="round"/>
      <circle cx="620" cy="24" r="1.4" fill="#FFFFFF"/>
    </g>
    <g class="meteor-b">
      <line x1="810" y1="540" x2="868" y2="517" stroke="url(#meteorGrad)" stroke-width="1.1" stroke-linecap="round"/>
      <circle cx="810" cy="540" r="1.2" fill="#E8F4FF"/>
    </g>
    <g class="meteor-c">
      <line x1="460" y1="1060" x2="515" y2="1038" stroke="url(#meteorGrad)" stroke-width="1.1" stroke-linecap="round"/>
      <circle cx="460" cy="1060" r="1.2" fill="#FFF2D6"/>
    </g>

    <!-- 4. REALISTIC DISTANT GALAXIES & CELESTIAL BODIES ACROSS THE CONTINUOUS CANVAS -->
    <!-- Hero Upper-Right: Andromeda-style Logarithmic Spiral Galaxy -->
    {build_realistic_spiral_galaxy(566, 94, 72, -26, 0.42, seed=808, spin_class="gal-spin")}

    <!-- Mid-Cosmos: Sombrero-style Edge-On Lenticular Galaxy -->
    {build_edge_on_galaxy(744, Y_TELEM + 26, 62, -14)}

    <!-- Lower-Cosmos: Distant Faint Whirlpool Spiral Galaxy + Rust Rocky World -->
    {build_realistic_spiral_galaxy(116, Y_REPOS + 148, 56, 22, 0.50, seed=909, spin_class="gal-spin-rev")}
    <g transform="translate(788, {Y_REPOS + 38})">
      <circle cx="0" cy="0" r="22" fill="url(#rustPlanet)"/>
      <circle cx="0" cy="0" r="22" fill="url(#terminatorShadow)"/>
    </g>

    <!-- Hero Primary Planet: Photorealistic Cassini-Style Ringed Gas Giant + Cratered Moon -->
    <g>
      <!-- Back Rings masked by physically accurate planet shadow cone -->
      <g transform="translate({saturn_cx}, {saturn_cy}) rotate(-16)" mask="url(#ringShadowMask)">
        {build_saturn_rings("back")}
      </g>
      <!-- Planet Sphere + Turbulent Atmospheric Zonal Bands + Chiaroscuro Nightside -->
      <circle cx="{saturn_cx}" cy="{saturn_cy}" r="48" fill="url(#saturnBase)"/>
      <g clip-path="url(#saturnClip)">
        <rect x="{saturn_cx - 50}" y="{saturn_cy - 50}" width="100" height="100" filter="url(#saturnBands)" opacity="0.58"/>
        <path d="M {saturn_cx-52} {saturn_cy-20} Q {saturn_cx} {saturn_cy-28} {saturn_cx+52} {saturn_cy-14}" fill="none" stroke="#EAE1CE" stroke-width="5" opacity="0.22"/>
        <path d="M {saturn_cx-52} {saturn_cy-4} Q {saturn_cx} {saturn_cy-12} {saturn_cx+52} {saturn_cy+2}" fill="none" stroke="#9B8972" stroke-width="6.5" opacity="0.28"/>
        <path d="M {saturn_cx-52} {saturn_cy+14} Q {saturn_cx} {saturn_cy+7} {saturn_cx+52} {saturn_cy+20}" fill="none" stroke="#C9B99F" stroke-width="4" opacity="0.2"/>
        <!-- Subtle ring shadow cast across the southern hemisphere -->
        <path d="M {saturn_cx-50} {saturn_cy+6} Q {saturn_cx+4} {saturn_cy+22} {saturn_cx+52} {saturn_cy+2}" fill="none" stroke="#020308" stroke-width="4.5" opacity="0.48"/>
        <!-- True nightside terminator shadow -->
        <circle cx="{saturn_cx}" cy="{saturn_cy}" r="48" fill="url(#terminatorShadow)"/>
        <circle cx="{saturn_cx}" cy="{saturn_cy}" r="48" fill="url(#saturnRim)"/>
      </g>
      <!-- Front Rings crossing in front of sphere -->
      <g transform="translate({saturn_cx}, {saturn_cy}) rotate(-16)">
        {build_saturn_rings("front")}
      </g>
      <!-- Orbiting Realistic Half-Lit Rocky Moon -->
      <g class="saturn-moon">
        <circle cx="0" cy="0" r="5.6" fill="url(#rockMoon)"/>
        <circle cx="-1.6" cy="-1.2" r="1.1" fill="#6F6E6A" opacity="0.45"/>
        <circle cx="1.2" cy="1.1" r="0.8" fill="#3D3E42" opacity="0.5"/>
      </g>
    </g>

    <!-- 5. CONTINUOUS ASTRONOMICAL STAR-CHART SPINE CONNECTING EVERY SECTION -->
    {''.join(spine_svg)}
    <circle cx="22" cy="0" r="2.6" fill="{C_STAR_ICE}" filter="url(#softBlur)" class="spine-pulse"/>

    <!-- ==================== SECTOR 01: HERO & BIO ==================== -->
    <g>
      <text x="46" y="34" fill="{C_TEXT_MUTED}" font-size="9.5" letter-spacing="1.6" class="mono">SECTOR 01 // DEEP FIELD PROFILE · RA 09h 42m · DEC +18° 12&#39;</text>

      <!-- Status Beacon + Handle Pill -->
      <g transform="translate(46, 48)">
        <rect x="0" y="0" width="{status_w:.0f}" height="24" rx="5" fill="{C_HUD_BG}" fill-opacity="0.82" stroke="{C_HUD_LINE}" stroke-width="0.9"/>
        <g transform="translate(14, 12)">
          <circle cx="0" cy="0" r="4" fill="{C_STATUS_OK}" class="status-pulse"/>
          <circle cx="0" cy="0" r="3" fill="{C_STATUS_OK}" class="status-dot"/>
        </g>
        <text x="25" y="15.8" fill="{C_STATUS_OK}" font-size="10" font-weight="600" letter-spacing="0.9" class="mono">{status}</text>
      </g>
      <g transform="translate({handle_x}, 48)">
        <rect x="0" y="0" width="{handle_w:.0f}" height="24" rx="5" fill="{C_HUD_BG}" fill-opacity="0.82" stroke="{C_HUD_LINE}" stroke-width="0.9"/>
        <text x="{handle_w/2:.0f}" y="15.8" text-anchor="middle" fill="{C_STAR_ICE}" font-size="10.8" font-weight="600" class="mono">@{username}</text>
      </g>

      <!-- Display Name & Tagline -->
      <text x="46" y="120" fill="url(#nameGrad)" font-size="40" font-weight="800" letter-spacing="-0.6" class="sans">{display}</text>
      <text x="46" y="150" fill="{C_STAR_BLUE}" font-size="13" font-weight="500" class="mono">{tagline}<tspan class="blink" fill="{C_STAR_WARM}"> ▌</tspan></text>
      <line x1="46" y1="165" x2="505" y2="165" stroke="{C_HUD_LINE}" stroke-width="0.9"/>

      <!-- Bio -->
      {bio_markup}

      <!-- Metadata Pills -->
      {''.join(hero_pills)}
    </g>

    <!-- Subtle Orbital Arc Bridging Sector 01 -> Sector 02 -->
    <path d="M 46 {Y_STACK - 16} Q 425 {Y_STACK - 34} 810 {Y_STACK - 16}" fill="none" stroke="{C_HUD_LINE}" stroke-width="0.8" stroke-opacity="0.65"/>

    <!-- ==================== SECTOR 02: PLANETARY TECH STACK ==================== -->
    <g>
      <text x="46" y="{Y_STACK + 28}" fill="{C_TEXT_PRI}" font-size="13.5" font-weight="700" letter-spacing="1.4" class="mono">02 // PLANETARY TECH STACK</text>
      <text x="810" y="{Y_STACK + 28}" text-anchor="end" fill="{C_TEXT_MUTED}" font-size="10" letter-spacing="1.2" class="mono">ORBITAL SYSTEM · 3 SATELLITES</text>
      <line x1="46" y1="{Y_STACK + 39}" x2="810" y2="{Y_STACK + 39}" stroke="{C_HUD_LINE}" stroke-width="0.8"/>

      <!-- Left Realistic Terrestrial Ocean/Cloud Exoplanet + Orbital Tracks -->
      <g transform="translate({terra_cx}, {terra_cy}) rotate(-15)">
        <ellipse cx="0" cy="0" rx="74" ry="24" fill="none" stroke="{C_STAR_BLUE}" stroke-opacity="0.24" stroke-width="0.8"/>
        <ellipse cx="0" cy="0" rx="104" ry="34" fill="none" stroke="{C_STAR_ICE}" stroke-opacity="0.18" stroke-width="0.8" stroke-dasharray="3 5"/>
        <ellipse cx="0" cy="0" rx="128" ry="42" fill="none" stroke="{C_STAR_WARM}" stroke-opacity="0.15" stroke-width="0.7"/>
      </g>
      <!-- Atmospheric Rayleigh Halo + Ocean World + Continents + Weather Clouds + Chiaroscuro Shadow -->
      <circle cx="{terra_cx}" cy="{terra_cy}" r="53" fill="url(#terraAtmo)"/>
      <circle cx="{terra_cx}" cy="{terra_cy}" r="45" fill="url(#terraOcean)"/>
      <g clip-path="url(#terraClip)">
        <rect x="{terra_cx - 48}" y="{terra_cy - 48}" width="96" height="96" filter="url(#terraLand)" opacity="0.58"/>
        <rect x="{terra_cx - 48}" y="{terra_cy - 48}" width="96" height="96" filter="url(#terraClouds)" opacity="0.72"/>
        <circle cx="{terra_cx}" cy="{terra_cy}" r="45" fill="url(#terminatorShadow)"/>
        <circle cx="{terra_cx}" cy="{terra_cy}" r="45" fill="url(#saturnRim)" opacity="0.85"/>
      </g>
      <!-- Orbiting Realistic Moons & Deep-Space Probe -->
      <g class="terra-moon-1">
        <circle cx="0" cy="0" r="4.6" fill="url(#rockMoon)"/>
      </g>
      <g class="terra-moon-2">
        <circle cx="0" cy="0" r="3.4" fill="url(#rockMoon)"/>
      </g>
      <g class="terra-probe">
        <circle cx="0" cy="0" r="1.8" fill="#FFFFFF" filter="url(#softBlur)"/>
      </g>
      <text x="{terra_cx}" y="{Y_STACK + 278}" text-anchor="middle" fill="{C_TEXT_MUTED}" font-size="9.5" letter-spacing="1.4" class="mono">KEPLER-186 // STACK ORBIT</text>

      <!-- Subtle Vertical Divider -->
      <line x1="310" y1="{Y_STACK + 56}" x2="310" y2="{Y_STACK + 286}" stroke="{C_HUD_LINE}" stroke-width="0.8" stroke-dasharray="2 5"/>

      <!-- Tech Stack Constellation Rows -->
      {''.join(stack_rows)}
    </g>

    <!-- Subtle Orbital Arc Bridging Sector 02 -> Sector 03 -->
    <path d="M 46 {Y_TELEM - 16} Q 425 {Y_TELEM - 30} 810 {Y_TELEM - 16}" fill="none" stroke="{C_HUD_LINE}" stroke-width="0.8" stroke-opacity="0.65"/>

    <!-- ==================== SECTOR 03: COSMIC TELEMETRY & LANGUAGES ==================== -->
    <g>
      <text x="46" y="{Y_TELEM + 28}" fill="{C_TEXT_PRI}" font-size="13.5" font-weight="700" letter-spacing="1.4" class="mono">03 // COSMIC TELEMETRY</text>
      <text x="810" y="{Y_TELEM + 28}" text-anchor="end" fill="{badge_color}" font-size="10" font-weight="600" letter-spacing="1" class="mono">{esc(live_badge)}</text>
      <line x1="46" y1="{Y_TELEM + 39}" x2="810" y2="{Y_TELEM + 39}" stroke="{C_HUD_LINE}" stroke-width="0.8"/>

      <!-- Precision Astrolabe Streak Gauge -->
      <g transform="translate(132, {Y_TELEM + 120})">
        <g class="astro-spin">
          {''.join(astro_ticks)}
          <circle cx="0" cy="-64" r="2.2" fill="{C_STAR_ICE}" filter="url(#softBlur)"/>
        </g>
        <circle cx="0" cy="0" r="{gauge_r}" fill="{C_HUD_BG}" fill-opacity="0.82" stroke="#182642" stroke-width="5.5"/>
        <circle cx="0" cy="0" r="{gauge_r}" fill="none" stroke="url(#arcGrad)" stroke-width="5.5" stroke-linecap="round"
          stroke-dasharray="{gauge_dash:.1f} {gauge_circ:.1f}" transform="rotate(-90)"/>
        <text x="0" y="-2" text-anchor="middle" fill="{C_TEXT_PRI}" font-size="25" font-weight="700" class="sans">{streak}</text>
        <text x="0" y="14" text-anchor="middle" fill="{C_STAR_BLUE}" font-size="9" font-weight="700" letter-spacing="1.2" class="mono">DAY STREAK</text>
        <text x="0" y="29" text-anchor="middle" fill="{C_TEXT_MUTED}" font-size="9.5" class="mono">Best: {best}d</text>
      </g>

      <!-- 2x2 Telemetry HUD Cards -->
      {''.join(telem_cards_svg)}

      <!-- Stellar Spectrograph Language Bar -->
      <text x="46" y="{bar_y - 10}" fill="{C_TEXT_MUTED}" font-size="9.8" font-weight="700" letter-spacing="1.3" class="mono">SPECTRAL LANGUAGE ANALYSIS</text>
      <g clip-path="url(#langBarClip)">
        <rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" fill="#111A30"/>
        {''.join(lang_segs)}
        <rect x="{bar_x}" y="{bar_y}" width="110" height="{bar_h}" fill="url(#sheen)" class="scan-bar"/>
      </g>
      {''.join(lang_leg)}
    </g>

    <!-- Subtle Orbital Arc Bridging Sector 03 -> Sector 04 -->
    <path d="M 46 {Y_CONTRIB - 16} Q 425 {Y_CONTRIB - 30} 810 {Y_CONTRIB - 16}" fill="none" stroke="{C_HUD_LINE}" stroke-width="0.8" stroke-opacity="0.65"/>

    <!-- ==================== SECTOR 04: CONTRIBUTION STARFIELD & WAVE ==================== -->
    <g>
      <text x="46" y="{Y_CONTRIB + 28}" fill="{C_TEXT_PRI}" font-size="13.5" font-weight="700" letter-spacing="1.4" class="mono">04 // CONTRIBUTION STARFIELD</text>
      <text x="810" y="{Y_CONTRIB + 28}" text-anchor="end" fill="{C_STAR_ICE}" font-size="11" font-weight="600" class="mono">{fmt_num(stats['contributions'])} stars ignited (365d)</text>
      <line x1="46" y1="{Y_CONTRIB + 39}" x2="810" y2="{Y_CONTRIB + 39}" stroke="{C_HUD_LINE}" stroke-width="0.8"/>

      <!-- Translucent Observatory Panel Backdrop for Heatmap + Wave -->
      <rect x="46" y="{Y_CONTRIB + 49}" width="764" height="262" rx="8" fill="{C_HUD_BG}" fill-opacity="0.62" stroke="{C_HUD_LINE}" stroke-width="0.8"/>
      {hud_crosshairs(46, Y_CONTRIB + 49, 764, 262, 4.0)}

      <!-- Weekday & Month Labels -->
      <text x="54" y="{gy + 1 * step + 8.5}" text-anchor="end" fill="{C_TEXT_MUTED}" font-size="8.5" class="mono" opacity="0.8">M</text>
      <text x="54" y="{gy + 3 * step + 8.5}" text-anchor="end" fill="{C_TEXT_MUTED}" font-size="8.5" class="mono" opacity="0.8">W</text>
      <text x="54" y="{gy + 5 * step + 8.5}" text-anchor="end" fill="{C_TEXT_MUTED}" font-size="8.5" class="mono" opacity="0.8">F</text>
      {''.join(months_svg)}

      <!-- Heatmap Star Cells -->
      {''.join(cells_svg)}

      <!-- Faint Icy Comet Sweeping Across Starfield -->
      <g clip-path="url(#calGridClip)">
        <g class="comet">
          <line x1="{gx - 78}" y1="{gy + 46}" x2="{gx}" y2="{gy + 46}" stroke="url(#cometTail)" stroke-width="1.8" stroke-linecap="round"/>
          <circle cx="{gx}" cy="{gy + 46}" r="2.6" fill="#FFFFFF" filter="url(#softBlur)"/>
        </g>
      </g>

      <!-- Legend -->
      <text x="670" y="{Y_CONTRIB + 183}" fill="{C_TEXT_MUTED}" font-size="9" class="mono">Void</text>
      {legend_cells}
      <text x="784" y="{Y_CONTRIB + 183}" fill="{C_TEXT_MUTED}" font-size="9" class="mono">Star</text>

      <!-- 30-Day Activity Wave -->
      <text x="62" y="{Y_CONTRIB + 202}" fill="{C_TEXT_MUTED}" font-size="9.8" font-weight="700" letter-spacing="1.2" class="mono">30-DAY ORBITAL ACTIVITY WAVE</text>
      <text x="{wx + ww}" y="{Y_CONTRIB + 202}" text-anchor="end" fill="{C_TEXT_SEC}" font-size="10" class="mono">{fmt_num(last30_total)} recent · peak {wmax}/day</text>
      <line x1="{wx}" y1="{wy + wh}" x2="{wx + ww}" y2="{wy + wh}" stroke="{C_HUD_LINE}" stroke-width="0.8"/>
      <line x1="{wx}" y1="{wy + wh // 2}" x2="{wx + ww}" y2="{wy + wh // 2}" stroke="{C_HUD_LINE}" stroke-opacity="0.45" stroke-width="0.8" stroke-dasharray="3 5"/>
      <path d="{area_d}" fill="url(#waveFill)"/>
      <path d="{path_d}" fill="none" stroke="url(#waveStroke)" stroke-width="1.9" stroke-linecap="round"/>
      {''.join(peak_dots)}
      <text x="{wx}" y="{wy + wh + 14}" fill="{C_TEXT_MUTED}" font-size="9" class="mono">30d ago</text>
      <text x="{wx + ww}" y="{wy + wh + 14}" text-anchor="end" fill="{C_TEXT_MUTED}" font-size="9" class="mono">Today</text>
    </g>

    <!-- Subtle Orbital Arc Bridging Sector 04 -> Sector 05 -->
    <path d="M 46 {Y_REPOS - 14} Q 425 {Y_REPOS - 28} 810 {Y_REPOS - 14}" fill="none" stroke="{C_HUD_LINE}" stroke-width="0.8" stroke-opacity="0.65"/>

    <!-- ==================== SECTOR 05: REPOSITORIES STAR CHART ==================== -->
    <g>
      <text x="46" y="{Y_REPOS + 28}" fill="{C_TEXT_PRI}" font-size="13.5" font-weight="700" letter-spacing="1.4" class="mono">05 // STAR CHART · REPOSITORIES</text>
      <text x="810" y="{Y_REPOS + 28}" text-anchor="end" fill="{C_TEXT_MUTED}" font-size="10" letter-spacing="1" class="mono">{len(repos)} sectors charted</text>
      <line x1="46" y1="{Y_REPOS + 39}" x2="810" y2="{Y_REPOS + 39}" stroke="{C_HUD_LINE}" stroke-width="0.8"/>

      <!-- Constellation Connector Threads -->
      {''.join(constellation_lines)}

      <!-- Repository Cards -->
      {''.join(repo_cards)}
    </g>

    <!-- ==================== DEEP-SPACE EVENT HORIZON FOOTER ==================== -->
    <g transform="translate(0, {Y_FOOTER})">
      <!-- Distant Realistic Black Hole / Gravitational Lens Accretion Horizon -->
      <g transform="translate(425, 92)">
        <circle cx="0" cy="0" r="88" fill="url(#bhHalo)"/>
        <!-- Relativistic lensed upper accretion halo bent over event horizon -->
        <path d="M -38 0 A 38 36 0 0 1 38 0" fill="none" stroke="#F5D7A8" stroke-width="5" stroke-opacity="0.48" filter="url(#softBlur)"/>
        <path d="M -33 0 A 33 32 0 0 1 33 0" fill="none" stroke="#FFF6E3" stroke-width="1.8" stroke-opacity="0.78"/>
        <ellipse cx="0" cy="-6" rx="190" ry="12" fill="url(#accretionDisk)" opacity="0.68" filter="url(#softBlur)"/>
        <ellipse cx="0" cy="-6" rx="135" ry="4.5" fill="url(#accretionDisk)" opacity="0.92"/>
        <circle cx="0" cy="0" r="30" fill="#000000"/>
        <circle cx="0" cy="0" r="30.8" fill="none" stroke="#FFF4DC" stroke-opacity="0.75" stroke-width="1"/>
      </g>
      <line x1="46" y1="8" x2="810" y2="8" stroke="{C_HUD_LINE}" stroke-width="0.7" stroke-opacity="0.6"/>
      <text x="425" y="42" text-anchor="middle" fill="{C_TEXT_SEC}" font-size="10.5" font-weight="600" letter-spacing="2" class="mono">{footer_text}</text>
    </g>
  </g>

  <rect x="1" y="1" width="{W-2}" height="{H-2}" rx="16" fill="none" stroke="url(#outerBorder)" stroke-width="1"/>
</svg>
"""


def render_readme(profile: dict[str, Any], stats: dict[str, Any]) -> str:
    username = profile.get("username", "SeishiKun9")
    display = profile.get("display_name") or username
    links = profile.get("links") or []
    repo_links = [f"[{r['name']}]({r['url']})" for r in (stats.get("repositories") or [])[:6]]
    nav_parts = [f"[{l['label']}]({l['url']})" for l in links] + [f"[All Repositories](https://github.com/{username}?tab=repositories)"]
    nav_line = " · ".join(nav_parts)
    repo_line = " · ".join(repo_links)

    lines = [
        '<div align="center">',
        "",
        f'<a href="https://github.com/{username}">',
        f'  <img src="./assets/universe.svg" alt="{esc(display)} — Seamless Animated Deep-Space GitHub Profile" width="100%" />',
        "</a>",
        "",
        nav_line,
        "",
        f"**Repositories:** {repo_line}" if repo_line else "",
        "",
        "</div>",
        "",
    ]
    return "\n".join(line for line in lines if line is not None)


def verify_svgs(svg_path: Path) -> None:
    assert svg_path.exists(), f"Missing {svg_path}"
    raw = svg_path.read_text(encoding="utf-8")
    root = ET.fromstring(raw)
    assert root.tag.endswith("svg"), "root is not <svg>"
    assert "@keyframes" in raw, "missing CSS animations"
    assert "wanderFar" in raw and "wanderMid" in raw, "missing wandering starfield animations"
    assert "prefers-reduced-motion" in raw, "missing reduced-motion media query"
    assert "<title" in raw, "missing accessible <title>"
    assert "<script" not in raw.lower(), "forbidden <script> tag"


def run_self_checks() -> None:
    assert esc('C++ & <script>"x"') == "C++ &amp; &lt;script&gt;&quot;x&quot;"
    wrapped = wrap_text("A very long description about cosmic distributed systems and galaxies", 22, 2)
    assert len(wrapped) == 2 and wrapped[-1].endswith("…")
    assert wrap_text("", 20, 2) == []

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

    verify_svgs(OUTPUT_SVG)

    # Edge-case injection & empty-stats render validation
    nasty_profile = {
        "username": "test_user",
        "display_name": 'A&B <Cosmic> "Dev"',
        "tagline": "C++ & C# <3 Space",
        "status": "ONLINE & READY",
        "bio": ["Uses <tags> & 'quotes' safely"],
        "meta": {"location": "Mars & Phobos"},
        "tech_stack": [{"category": "Langs & More", "items": ["C++", "C#", "R&D"]}],
        "footer_text": "A & B < C",
    }
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
    ET.fromstring(render_universe(nasty_profile, empty_stats))
    print("All self-checks passed.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate seamless animated deep-space GitHub profile SVG.")
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
        print("ERROR: GITHUB_TOKEN is not set. Pass --preview to generate offline starter SVG.", file=sys.stderr)
        return 1

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_SVG.write_text(render_universe(profile, stats), encoding="utf-8")
    README_PATH.write_text(render_readme(profile, stats), encoding="utf-8")
    run_self_checks()
    mode = "live GitHub API" if stats["live"] else "offline preview"
    print(f"Generated {OUTPUT_SVG.name} + README.md ({mode}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
