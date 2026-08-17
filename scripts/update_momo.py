import re
import subprocess
from pathlib import Path
from urllib.request import Request, urlopen

PAGE_URLS = [
    "https://www.momoshop.com.tw/main/Main.jsp",
    "https://m.momoshop.com.tw/live.momo",
]
BASE_URLS = [
    "https://livestream-source.momoshop.com.tw/live/{id}.m3u8",
    "https://livestream-dev-source.momoshop.com.tw/live/{id}.m3u8",
]
FALLBACK_IDS = [
    "0601100008j8dsB000",
    "0527090004rwwhA000",
]
# Temporary YouTube sources supplied by the user for 2026-08-17.
# Keep these fixed for today's playlist; the resolver converts each live video
# to its current direct stream URL and falls back to the previous resolved URL.
YOUTUBE_SOURCES = [
    ("MOMO1-YT", "MOMO購物一台 CH48 - YouTube", "https://www.youtube.com/watch?v=7__QARkZdNs"),
    ("MOMO2-YT", "MOMO購物二台 CH35 - YouTube", "https://www.youtube.com/watch?v=xbNWkUyxQGM&list=PLNi1dgO66if4mwRZ5LdobeZYDDN53xZQm"),
]
W3U = Path("MOMO.w3u")


def fetch(url):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="ignore")


def stream_works(url):
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=15) as response:
            return response.status < 400
    except Exception:
        return False


def find_ids(html):
    ids = []
    patterns = [
        r"liveId[=:/\\\"']+([A-Za-z0-9]+)",
        r"live[/\\]([A-Za-z0-9]+)\\?orientation",
        r"liveId\\?[:=]+\\?[\"']([A-Za-z0-9]+)",
    ]
    for pattern in patterns:
        ids.extend(re.findall(pattern, html))
    return list(dict.fromkeys(x for x in ids if len(x) >= 8))


def resolve_momo_stream(live_id):
    for base in BASE_URLS:
        stream = base.format(id=live_id)
        if stream_works(stream):
            return stream
    return None


def resolve_youtube_stream(video_url):
    """Resolve a supplied YouTube live/video URL to a direct playable stream."""
    try:
        for extractor_args in [
            "youtube:player_client=web,android,tv",
            "youtube:player_client=web_safari",
        ]:
            result = subprocess.run([
                "yt-dlp", "--no-warnings", "--ignore-config",
                "--extractor-args", extractor_args,
                "--get-url", "-f", "best[protocol^=m3u8]/best", video_url,
            ], capture_output=True, text=True, timeout=90, check=False)
            for url in result.stdout.splitlines():
                url = url.strip()
                if url.startswith("http") and (".m3u8" in url or "googlevideo.com" in url):
                    return url
    except Exception as exc:
        print(f"YouTube resolver error for {video_url}: {exc}")
    return None


def read_existing_entries():
    if not W3U.exists():
        return {}
    entries, current_id = {}, None
    for line in W3U.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("#EXTINF"):
            match = re.search(r'tvg-id="([^"]+)"', line)
            current_id = match.group(1) if match else None
        elif current_id and line.startswith("http"):
            entries[current_id] = line.strip()
            current_id = None
    return entries


def main():
    existing = read_existing_entries()
    discovered = []

    # Main.jsp is the primary official MOMO source; live.momo is fallback.
    for page_url in PAGE_URLS:
        try:
            discovered.extend(find_ids(fetch(page_url)))
        except Exception as exc:
            print(f"Could not fetch {page_url}: {exc}")

    candidate_ids = list(dict.fromkeys(discovered + FALLBACK_IDS))
    momo_streams, seen = [], set()
    for live_id in candidate_ids:
        stream = resolve_momo_stream(live_id)
        if stream and stream not in seen:
            momo_streams.append(stream)
            seen.add(stream)
        if len(momo_streams) == 2:
            break

    lines = ["#EXTM3U", ""]
    for index, name in enumerate(["MOMO購物台 1", "MOMO購物台 2"]):
        tvg_id = f"MOMO{index + 1}"
        stream = momo_streams[index] if index < len(momo_streams) else existing.get(tvg_id)
        if stream:
            lines += [f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{name}" group-title="MOMO",{name}', stream, ""]

    for tvg_id, name, video_url in YOUTUBE_SOURCES:
        stream = resolve_youtube_stream(video_url) or existing.get(tvg_id)
        if stream:
            lines += [f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{name}" group-title="MOMO YouTube",{name}', stream, ""]

    if len(lines) <= 2:
        raise RuntimeError("No playable MOMO streams could be generated")
    W3U.write_text("\n".join(lines), encoding="utf-8")
    print("MOMO IPTV playlist updated")


if __name__ == "__main__":
    main()
