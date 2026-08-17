import re
import subprocess
from pathlib import Path
from urllib.request import Request, urlopen

PAGE_URL = "https://m.momoshop.com.tw/live.momo"
BASE_URLS = [
    "https://livestream-source.momoshop.com.tw/live/{id}.m3u8",
    "https://livestream-dev-source.momoshop.com.tw/live/{id}.m3u8",
]
FALLBACK_IDS = [
    "0601100008j8dsB000",
    "0527090004rwwhA000",
]
YOUTUBE_CHANNELS = [
    ("MOMO1-YT", "MOMO購物一台 CH48 - YouTube", "https://www.youtube.com/@momoch4812/streams"),
    ("MOMO2-YT", "MOMO購物二台 CH35 - YouTube", "https://www.youtube.com/@momoch3571/streams"),
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
    for pattern in [
        r"liveId[=:/\\\"']+([A-Za-z0-9]+)",
        r"live[/\\]([A-Za-z0-9]+)\\?orientation",
    ]:
        ids.extend(re.findall(pattern, html))
    return list(dict.fromkeys(x for x in ids if len(x) >= 8))


def resolve_momo_stream(live_id):
    for base in BASE_URLS:
        stream = base.format(id=live_id)
        if stream_works(stream):
            return stream
    return None


def resolve_youtube_stream(channel_streams_url):
    """Find the current live video and resolve it to a direct HLS URL."""
    common = [
        "--no-warnings",
        "--ignore-config",
        "--flat-playlist",
        "--playlist-end", "10",
        "--match-filter", "live_status=is_live",
        "--print", "id",
        channel_streams_url,
    ]
    try:
        result = subprocess.run(
            ["yt-dlp", *common],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        video_ids = [x.strip() for x in result.stdout.splitlines() if re.fullmatch(r"[A-Za-z0-9_-]{11}", x.strip())]
        if not video_ids:
            print(f"No active YouTube live found: {channel_streams_url}")
            if result.stderr:
                print(result.stderr[-2000:])
            return None

        video_url = f"https://www.youtube.com/watch?v={video_ids[0]}"
        extractors = [
            "youtube:player_client=web,android,tv",
            "youtube:player_client=web_safari",
        ]
        for extractor_args in extractors:
            result = subprocess.run(
                [
                    "yt-dlp", "--no-warnings", "--ignore-config",
                    "--extractor-args", extractor_args,
                    "--get-url", "-f", "best[protocol^=m3u8]/best",
                    video_url,
                ],
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            urls = [x.strip() for x in result.stdout.splitlines() if x.strip().startswith("http")]
            for url in urls:
                if ".m3u8" in url or "googlevideo.com" in url:
                    print(f"Resolved YouTube {video_ids[0]} -> direct stream")
                    return url
            if result.stderr:
                print(result.stderr[-1000:])
    except Exception as exc:
        print(f"YouTube resolver error for {channel_streams_url}: {exc}")
    return None


def read_existing_entries():
    if not W3U.exists():
        return {}
    text = W3U.read_text(encoding="utf-8", errors="ignore")
    entries = {}
    current_id = None
    for line in text.splitlines():
        if line.startswith("#EXTINF"):
            match = re.search(r'tvg-id="([^"]+)"', line)
            current_id = match.group(1) if match else None
        elif current_id and line.startswith("http"):
            entries[current_id] = line.strip()
            current_id = None
    return entries


def main():
    existing = read_existing_entries()

    try:
        html = fetch(PAGE_URL)
        discovered = find_ids(html)
    except Exception as exc:
        print(f"Could not fetch official MOMO live page: {exc}")
        discovered = []

    candidate_ids = list(dict.fromkeys(discovered + FALLBACK_IDS))
    momo_streams = []
    seen = set()
    for live_id in candidate_ids:
        stream = resolve_momo_stream(live_id)
        if stream and stream not in seen:
            momo_streams.append(stream)
            seen.add(stream)
        if len(momo_streams) == 2:
            break

    if len(momo_streams) < 2:
        print("Warning: fewer than 2 official MOMO HLS streams resolved; retaining previous entries where possible")

    lines = ["#EXTM3U", ""]
    momo_names = ["MOMO購物台 1", "MOMO購物台 2"]
    for index in range(2):
        tvg_id = f"MOMO{index + 1}"
        stream = momo_streams[index] if index < len(momo_streams) else existing.get(tvg_id)
        if not stream:
            continue
        lines += [
            f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{momo_names[index]}" group-title="MOMO",{momo_names[index]}',
            stream,
            "",
        ]

    for tvg_id, name, channel_url in YOUTUBE_CHANNELS:
        stream = resolve_youtube_stream(channel_url)
        if not stream:
            stream = existing.get(tvg_id)
            if stream:
                print(f"Keeping previous YouTube HLS URL for {tvg_id}")
            else:
                print(f"No YouTube HLS URL available yet for {tvg_id}; skipping")
                continue
        lines += [
            f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{name}" group-title="MOMO YouTube",{name}',
            stream,
            "",
        ]

    if len(lines) <= 2:
        raise RuntimeError("No playable MOMO streams could be generated")

    W3U.write_text("\n".join(lines), encoding="utf-8")
    print("MOMO IPTV playlist updated")


if __name__ == "__main__":
    main()
