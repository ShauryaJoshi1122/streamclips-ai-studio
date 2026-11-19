"""Indian meme templates integration from templates.meme/templates/country/IN.

Scrapes, searches, and matches Indian meme templates (e.g. Paisa Barbaad, Babu Rao,
Khatam Tata Bye Bye, Climax Baaki Hai, MS Dhoni Attitude) according to the clip's
content, mood, and transcript, then splices the meme as an insert or punchline outro.
"""

import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .common import CACHE, DATA, ENV_DIR, Problem, probe, run, safe_unlink, say

MEMES_DIR = ENV_DIR / "memes"
CATALOG_NAME = "indian_memes.json"
BASE_URL = "https://templates.meme/templates/country/IN"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# Keyword to meme mapping heuristics for instant viral punchlines
TRIGGER_MAP = {
    # Fail / Loss / Regret / Death / Waste of money
    ("paisa", "paise", "barbaad", "waste", "loss", "gaya", "chud", "ruin"): [
        "paisa-barbaad", "humko-pareshan-kiya-gaya", "mere-haatho-se-buri-maut-marta-ye"
    ],
    ("khatam", "bye", "over", "dead", "mar gaya", "finish", "end"): [
        "humko-pareshan-kiya-gaya", "paisa-barbaad", "mere-haatho-se-buri-maut-marta-ye"
    ],
    # Climax / Suspense / Wait for it
    ("climax", "ruko", "sabar", "wait", "baaki", "dekho"): [
        "aur-abhi-to-ruko-climax-abhi-baaki-hai", "samaj-rahe-ho"
    ],
    # Savage / Attitude / Chad / Clutch / God play
    ("attitude", "clutch", "headshot", "ace", "pro", "god", "badass", "win", "chad"): [
        "ms-dhoni-attitude", "virat-kohli-receiving-award"
    ],
    # Laugh / Comedy / Funny fail
    ("haha", "lol", "lmao", "hasna", "laugh", "funny", "roast", "joke"): [
        "abhijeet-laughing", "kanhaiya-meme", "ya-ya-ya"
    ],
    # Shock / Surprise / Confusion
    ("shock", "kya", "what", "hein", "impossible", "kaise"): [
        "samaj-rahe-ho", "aee-lakdi-kyu-phasi-ho", "kyu-nahi-bol-rahe-ho-kuch-to-bolo"
    ],
    # Anger / Rage / Frustration
    ("gussa", "rage", "anger", "bhai", "abe", "chup", "maut"): [
        "bhen-ke-lun-autat-mai", "mere-haatho-se-buri-maut-marta-ye"
    ]
}


def _find_catalog_file():
    candidates = [
        Path(__file__).resolve().parent.parent.parent / "data" / CATALOG_NAME,
        Path(__file__).resolve().parent.parent / "data" / CATALOG_NAME,
        DATA / "memes" / CATALOG_NAME,
        MEMES_DIR / CATALOG_NAME,
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


def load_catalog():
    """Load Indian meme catalog with all scraped templates."""
    cat_file = _find_catalog_file()
    if cat_file.exists():
        try:
            return json.loads(cat_file.read_text(encoding="utf-8"))
        except Exception as exc:
            say(f"failed reading meme catalog: {exc}", "warn")
    return []


def search_memes(query="", mood=None, limit=10):
    """Search catalog for templates matching query or mood."""
    catalog = load_catalog()
    if not catalog:
        return []
    words = [w.lower() for w in re.findall(r"\w+", query or "")]
    results = []
    for m in catalog:
        if not m.get("video_url"):
            continue
        score = 0
        text = (m.get("title", "") + " " + m.get("id", "") + " " +
                m.get("desc", "") + " " + " ".join(m.get("tags", []))).lower()
        if mood and mood.lower() in [md.lower() for md in m.get("moods", [])]:
            score += 30
        for w in words:
            if w in m.get("id", "").lower():
                score += 25
            elif w in m.get("title", "").lower():
                score += 20
            elif w in text:
                score += 8
        if score > 0 or not words:
            results.append((score, m))
    results.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in results[:limit]]


def match_meme_for_clip(pick, words=None, catalog=None):
    """Match the best Indian meme according to the clip's moment, type, title and words."""
    if catalog is None:
        catalog = load_catalog()
    if not catalog:
        return None

    by_id = {m["id"]: m for m in catalog if m.get("video_url")}
    if not by_id:
        return None

    # 1. If pick specifically requested a meme by id
    req_meme = pick.get("meme")
    if req_meme and req_meme in by_id:
        return by_id[req_meme]

    # 2. Build full text context from pick details and spoken words
    clip_text = " ".join([
        pick.get("title") or "",
        pick.get("type") or "",
        pick.get("why") or "",
        pick.get("caption") or "",
        " ".join(pick.get("hashtags") or []),
        " ".join(w["w"] for w in (words or []))
    ]).lower()

    # 3. Check direct trigger keyword mappings
    for keywords, meme_ids in TRIGGER_MAP.items():
        if any(kw in clip_text for kw in keywords):
            for mid in meme_ids:
                if mid in by_id:
                    return by_id[mid]

    # 4. Fallback to scoring based on moment type & semantic mood
    moment_type = (pick.get("type") or "reaction").lower()
    mood_map = {
        "reaction": ["reaction", "shock", "rage"],
        "funny": ["funny", "laugh", "reaction"],
        "skill": ["skill", "attitude", "win"],
        "reveal": ["reveal", "shock"],
        "story": ["reaction", "funny"],
        "take": ["attitude", "reaction"],
        "fail": ["fail", "sad", "reaction"]
    }
    target_moods = mood_map.get(moment_type, ["reaction"])

    best_meme = None
    best_score = -1

    for m in catalog:
        if not m.get("video_url"):
            continue
        score = 0
        meme_moods = [md.lower() for md in m.get("moods", [])]
        for tm in target_moods:
            if tm in meme_moods:
                score += 20
        # Check text overlaps
        m_tokens = set(re.findall(r"\w{3,}", (m.get("title", "") + " " + m.get("desc", "")).lower()))
        for tok in m_tokens:
            if tok in clip_text:
                score += 10
        if score > best_score:
            best_score = score
            best_meme = m

    return best_meme or by_id.get("paisa-barbaad") or list(by_id.values())[0]


def download_meme(meme, timeout=20):
    """Ensure meme video is downloaded to ~/.streamclips/memes/<id>.mp4."""
    MEMES_DIR.mkdir(parents=True, exist_ok=True)
    dst = MEMES_DIR / f"{meme['id']}.mp4"
    if dst.exists() and dst.stat().st_size > 10000:
        return dst

    url = meme.get("video_url")
    if not url:
        raise Problem(f"meme '{meme['id']}' has no video URL")

    say(f"downloading Indian meme: {meme.get('title')} ({meme['id']})", "step")
    req = urllib.request.Request(url, headers=HEADERS)
    tmp = dst.with_suffix(".tmp.mp4")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(tmp, "wb") as f:
            shutil.copyfileobj(resp, f)
        tmp.replace(dst)
        return dst
    except Exception as exc:
        safe_unlink(tmp)
        raise Problem(f"failed downloading meme video {url}: {exc}") from exc


def format_meme_916(src_mp4, dst_mp4, duration=2.5, width=1080, height=1920, fps=30.0):
    """Format meme into a 9:16 vertical video with blurred background and aligned audio."""
    info = probe(src_mp4)
    d = min(duration, info.get("duration") or duration)
    # Filter: split into blurred background and sharp centered foreground
    filter_complex = (
        f"[0:v]split=2[bg][fg];"
        f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},boxblur=25:10[bgblur];"
        f"[fg]scale={width}:-2:flags=lanczos[fgscaled];"
        f"[bgblur][fgscaled]overlay=(W-w)/2:(H-h)/2[vout]"
    )
    cmd = [
        "ffmpeg", "-y", "-v", "error", "-nostdin",
        "-i", str(src_mp4),
        "-t", f"{d:.3f}",
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22", "-pix_fmt", "yuv420p",
        "-r", f"{fps:.3f}",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        str(dst_mp4)
    ]
    run(cmd)
    return dst_mp4


def splice_meme_into_clip(clip_mp4, meme_916_mp4, out_mp4, style="insert", fps=30.0):
    """Splice the formatted 9:16 meme into the vertical clip."""
    c_info = probe(clip_mp4)
    w = c_info.get("width") or 1080
    h = c_info.get("height") or 1920
    f = min(60.0, c_info.get("fps") or fps)
    filter_complex = (
        f"[0:v]scale={w}:{h},fps={f:.3f},setsar=1[v0];"
        f"[1:v]scale={w}:{h},fps={f:.3f},setsar=1[v1];"
        f"[0:a]aresample=48000[a0];[1:a]aresample=48000[a1];"
        f"[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]"
    )
    cmd = [
        "ffmpeg", "-y", "-v", "error", "-nostdin",
        "-i", str(clip_mp4),
        "-i", str(meme_916_mp4),
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        str(out_mp4)
    ]
    run(cmd)
    return out_mp4


def apply_meme_pipeline(clip_path, pick, words, cfg, work_dir):
    """Finds, formats, and attaches matching Indian meme to clip if meme option is active."""
    meme_opt = cfg.get("meme") or "auto"
    if str(meme_opt).lower() in ("none", "false", "off", "0"):
        return None

    catalog = load_catalog()
    if not catalog:
        say("meme catalog empty; run 'streamclips memes update'", "warn")
        return None

    # Match meme
    meme = match_meme_for_clip(pick, words, catalog)
    if not meme or not meme.get("video_url"):
        return None

    say(f"  matching meme: '{meme['title']}' ({meme['id']})", "info")
    meme_raw = download_meme(meme)

    # Prepare formatted 9:16 version in work_dir
    memes_work = Path(work_dir) / "memes_proc"
    memes_work.mkdir(parents=True, exist_ok=True)
    meme_916 = memes_work / f"{meme['id']}_916.mp4"
    format_meme_916(
        meme_raw, meme_916,
        duration=cfg.get("meme_duration", 2.5),
        width=cfg.get("width", 1080),
        height=cfg.get("height", 1920)
    )

    # Splice into clip
    final_tmp = clip_path.with_name(clip_path.stem + "_with_meme.mp4")
    splice_meme_into_clip(clip_path, meme_916, final_tmp, style=cfg.get("meme_style", "insert"))

    # Replace original clip with spliced version
    final_tmp.replace(clip_path)
    say(f"  added meme reaction '{meme['title']}'", "good")
    return meme


def update_catalog(verbose=True):
    """Scrape all pages from https://templates.meme/templates/country/IN and update catalog."""
    if verbose:
        say("Scraping all pages from https://templates.meme/templates/country/IN ...", "step")

    all_items = []
    for page in range(1, 40):
        url = f"{BASE_URL}?page={page}" if page > 1 else BASE_URL
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
                cards = re.findall(
                    r'<a\s+href="(/templates/[a-zA-Z0-9_-]+)"[^>]*>.*?'
                    r'<img\s+src="([^"]+)"\s+alt="([^"]*)"[^>]*>.*?'
                    r'<h3[^>]*>(.*?)</h3>.*?</a>',
                    html, re.DOTALL
                )
                if not cards:
                    break
                if verbose:
                    say(f"  page {page}: {len(cards)} templates", "info")
                for href, thumb, alt, title in cards:
                    slug = href.split("/")[-1]
                    all_items.append({
                        "id": slug,
                        "title": title.strip(),
                        "url": f"https://templates.meme{href}",
                        "thumb": thumb,
                        "alt": alt.strip()
                    })
        except Exception:
            break

    if verbose:
        say(f"Found {len(all_items)} templates. Fetching video URLs and metadata...", "step")

    def fetch_details(item):
        try:
            req = urllib.request.Request(item["url"], headers=HEADERS)
            with urllib.request.urlopen(req, timeout=12) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
                mp4s = re.findall(r'(https://cdn\.templates\.meme/file/templates-meme/templates/[^"\'<>]+\.mp4)', html)
                desc_m = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', html)
                kw_m = re.search(r'<meta\s+name="keywords"\s+content="([^"]*)"', html)
                desc = desc_m.group(1) if desc_m else ""
                kw = kw_m.group(1) if kw_m else ""
                text = (item["title"] + " " + desc + " " + kw).lower()
                tags = [w.strip() for w in kw.split(",") if w.strip()]
                moods = []
                if any(w in text for w in ["laugh", "funny", "hasna", "joke", "roast", "comedy"]):
                    moods.append("funny")
                if any(w in text for w in ["cry", "sad", "rona", "crying", "dukh", "dard"]):
                    moods.append("sad")
                if any(w in text for w in ["anger", "rage", "gussa", "maut", "attitude", "dhoni"]):
                    moods.append("rage")
                if any(w in text for w in ["shock", "surprised", "hairan", "climax", "ruko"]):
                    moods.append("reveal")
                if any(w in text for w in ["fail", "pareshan", "barbaad", "khatam", "gaya"]):
                    moods.append("fail")
                if any(w in text for w in ["attitude", "swag", "sigma", "pro", "win", "clutch", "award"]):
                    moods.append("skill")
                if not moods:
                    moods.append("reaction")
                return {
                    "id": item["id"], "title": item["title"], "url": item["url"],
                    "video_url": mp4s[0] if mp4s else None, "thumb": item["thumb"],
                    "desc": desc, "tags": tags, "moods": moods
                }
        except Exception:
            return {**item, "video_url": None, "desc": "", "tags": [], "moods": ["reaction"]}

    with ThreadPoolExecutor(max_workers=25) as pool:
        catalog = list(pool.map(fetch_details, all_items))

    cat_file = _find_catalog_file()
    cat_file.parent.mkdir(parents=True, exist_ok=True)
    cat_file.write_text(json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8")
    if verbose:
        videos_count = sum(1 for m in catalog if m.get("video_url"))
        say(f"Catalog updated: {len(catalog)} templates ({videos_count} videos) -> {cat_file}", "good")
    return catalog
