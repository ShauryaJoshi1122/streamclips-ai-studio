"""yt-dlp wrappers. A stream is fetched as audio first; video only for the seconds that
become clips, so a 6-hour stream costs a few hundred MB instead of many GB."""

import shutil
import time
from pathlib import Path

from .common import Problem, probe, read_json, run, safe_unlink, say, write_json

META_KEYS = ("id", "title", "channel", "uploader", "duration", "view_count", "live_status",
             "is_live", "was_live", "webpage_url", "extractor_key", "timestamp",
             "release_timestamp", "upload_date")


def ytdlp_args(url, cookies=None):
    """Options every yt-dlp call for this URL needs."""
    args = ["--no-playlist", "--no-warnings"]
    youtube = "youtu" in url
    if youtube and not shutil.which("deno"):
        for runtime in ("node", "bun"):
            path = shutil.which(runtime)
            if path:
                args += ["--js-runtimes", f"{runtime}:{path}"]
                break
    if cookies:
        args += ["--cookies-from-browser", cookies]
    return args


def resolve_channel_url(url, cookies=None):
    """If given a channel URL (like https://kick.com/gamerfleet), resolve it to the latest public VOD."""
    import json, re
    m = re.match(r'^https?://(?:www\.)?kick\.com/([a-zA-Z0-9_-]+)/?$', url)
    if m and m.group(1).lower() not in ('video', 'videos', 'categories', 'search'):
        handle = m.group(1)
        page = f"https://kick.com/{handle}/videos"
        args = ytdlp_args(page, cookies)
        try:
            out = run(["yt-dlp", "--flat-playlist", "--playlist-end", "5", "-J", *args, page],
                      timeout=30, quiet_fail=True)
            if out:
                data = json.loads(out)
                for e in data.get("entries") or []:
                    if e.get("availability") == "public" and e.get("id"):
                        return f"https://kick.com/{handle}/videos/{e['id']}"
        except Exception:
            pass
    return url


def friendly(exc, url):
    """Turn common yt-dlp failures into the fix the user needs."""
    text = str(exc)
    low = text.lower()
    if "confirm your age" in low or "sign in to confirm" in low or "age-restricted" in low:
        return Problem("YouTube needs a login for this video (age-restricted). Run again with "
                       "--cookies chrome (or the browser you are signed in with).")
    if "kick" in url and ("403" in text or "forbidden" in low):
        return Problem("Kick blocked the download. Run again with --cookies chrome.")
    if "subscriber" in low or "sub-only" in low or "only available to" in low:
        return Problem("This VOD is subscriber-only. Run again with --cookies <browser> from an "
                       "account that can watch it.")
    if "not a bot" in low:
        return Problem("YouTube is asking to confirm you're not a bot. Run again with "
                       "--cookies chrome, or wait a while.")
    return exc if isinstance(exc, Problem) else Problem(text)


def is_local_file(url):
    if not url:
        return False
    s = str(url).strip()
    if s.startswith(("http://", "https://", "ftp://", "www.")):
        return False
    p = Path(s)
    return p.is_file() or p.exists()


def metadata(url, args, work, refresh=False):
    cached = work / "meta.json"
    meta = read_json(cached)
    if is_local_file(url):
        if meta and not refresh:
            return meta
        p = Path(url).resolve()
        info = probe(p)
        dur = float(info.get("duration") or 0.0)
        stem = p.stem
        creator = stem.split("__")[0] if "__" in stem else "Creator"
        title = stem.replace("_", " ").replace("-", " ").title()
        meta = {
            "id": stem,
            "title": title,
            "channel": creator,
            "uploader": creator,
            "name": creator,
            "duration": dur,
            "view_count": 1000,
            "live_status": "not_live",
            "is_live": False,
            "was_live": False,
            "webpage_url": str(p),
            "extractor_key": "LocalFile",
            "_at": time.time(),
        }
        write_json(cached, meta)
        return meta

    stale = meta and meta.get("live_status") == "is_live" and time.time() - meta.get("_at", 0) > 300
    if meta and not refresh and not stale:
        return meta
    import json
    try:
        full = json.loads(run(["yt-dlp", "-J", *args, url], timeout=240))
    except Problem as exc:
        raise friendly(exc, url) from None
    meta = {k: full.get(k) for k in META_KEYS}
    meta["name"] = meta.get("channel") or meta.get("uploader") or "creator"
    meta["_at"] = time.time()
    write_json(cached, meta)
    return meta


def _finished(folder, stem):
    return [p for p in folder.glob(stem + ".*")
            if not p.name.endswith((".part", ".ytdl", ".json", ".tmp")) and ".part-" not in p.name]


def audio(url, args, work, live=False, section=None):
    """The full audio track of the stream (reused between runs unless the stream is live)."""
    have = _finished(work, "audio")
    if have and not live:
        say(f"reusing audio ({have[0].stat().st_size / 1e6:.0f} MB)", "good")
        return have[0]

    # Clean old completed audio files safely; leave active partial downloads to resume
    for old in work.glob("audio.*"):
        if not old.name.endswith((".part", ".ytdl", ".tmp")):
            safe_unlink(old)

    if is_local_file(url):
        say("extracting audio track from local media file...", "step")
        dest = work / "audio.mp3"
        run(["ffmpeg", "-y", "-v", "error", "-nostdin", "-i", str(Path(url).resolve()),
             "-vn", "-acodec", "libmp3lame", "-b:a", "128k", str(dest)])
        say(f"audio ready ({dest.stat().st_size / 1e6:.1f} MB)", "good")
        return dest

    say("downloading the audio track (video comes later, only for the clips)...", "step")
    extra = ["--live-from-start"] if live and "youtu" in url else []
    if section:
        extra += ["--download-sections", section]

    # Format preference: dedicated audio stream first, then lowest video resolution (160p or 360p)
    fmt = "ba/b[height<=160]/b[height<=360]/worst[acodec!=none]/b"
    try:
        run(["yt-dlp", *args, *extra, "-f", fmt, "-N", "4",
             "-o", str(work / "audio.%(ext)s"), url], timeout=4 * 3600)
    except Problem as exc:
        raise friendly(exc, url) from None
    have = _finished(work, "audio")
    if not have:
        raise Problem("the download finished but no audio file appeared")
    say(f"audio ready ({have[0].stat().st_size / 1e6:.0f} MB)", "good")
    return have[0]


def video_slice(url, args, start, end, dest: Path, max_height):
    """Only [start, end] seconds of the video, as an mp4."""
    if dest.exists() and dest.stat().st_size > 50_000:
        return dest
    for old in dest.parent.glob(dest.stem + ".*"):
        if not old.name.endswith((".part", ".ytdl", ".tmp")):
            safe_unlink(old)

    if is_local_file(url):
        p = Path(url).resolve()
        start = max(0.0, start)
        dur = max(0.1, end - start)
        say(f"slicing local video {start:.1f}s - {end:.1f}s...", "step")
        run(["ffmpeg", "-y", "-v", "error", "-nostdin", "-ss", f"{start:.2f}", "-t", f"{dur:.2f}",
             "-i", str(p), "-c:v", "libx264", "-crf", "18", "-preset", "ultrafast", "-c:a", "aac", str(dest)])
        return dest

    fmt = (f"bv*[height<={max_height}][vcodec^=avc1]+ba/bv*[height<={max_height}]+ba/"
           f"b[height<={max_height}]/bv*+ba/b")
    try:
        run(["yt-dlp", *args, "-f", fmt, "--merge-output-format", "mp4",
             "--download-sections", f"*{max(0, start):.2f}-{end:.2f}",
             "-o", str(dest.with_suffix(".%(ext)s")), url], timeout=1800)
    except Problem as exc:
        raise friendly(exc, url) from None
    got = _finished(dest.parent, dest.stem)
    if not got:
        raise Problem(f"no video came back for {start:.0f}-{end:.0f}s")
    if got[0] != dest:
        try:
            got[0].replace(dest)
        except OSError:
            safe_unlink(dest)
            got[0].replace(dest)
    return dest
