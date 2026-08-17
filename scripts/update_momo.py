import re
import subprocess
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import parse_qs, urlparse

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

YOUTUBE_SOURCES = [
    ("MOMO1-YT", "MOMO購物一台 CH48 - YouTube", "https://www.youtube.com/@momoch4812/streams", "https://www.youtube.com/watch?v=7__QARkZdNs"),
    ("MOMO2-YT", "MOMO購物二台 CH35 - YouTube", "https://www.youtube.com/@momoch3571/streams", "https://www.youtube.com/watch?v=xbNWkUyxQGM"),
]
W3U = Path("MOMO.w3u")


def fetch(url):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="ignore")


def stream_works(url):
    if not url or not url.startswith("http"):
        return False
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=15) as response:
            return response.status < 400
    except Exception:
        return False


def is_youtube_stream(url):
    return bool(url and url.startswith("http") and (".m3u8" in url or "googlevideo.com" in url))


def youtube_video_id(url):
    parsed = urlparse(url)
    if parsed.hostname in {"youtu.be", "www.youtu.be"}:
        return parsed.path.strip("/").split("/")[0]
    return parse_qs(parsed.query).get("v", [None])[0]


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


def get_channel_candidates(channel_url):
    result = subprocess.run(
        [
            "yt-dlp", "--no-warnings", "--ignore-config",
            "--flat-playlist", "--playlist-end", "20",
            "--print", "%(id)s|%(title)s|%(live_status)s", channel_url,
        ],
        capture_output=True, text=True, timeout=120, check=False,
    )

    candidates = []
    for line in result.stdout.splitlines():
        parts = line.split("|", 2)
        if not parts:
            continue
        video_id = parts[0].strip()
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            live_status = parts[2].strip().lower() if len(parts) >= 3 else ""
            candidates.append((video_id, live_status))

    if result.returncode != 0:
        print(f"yt-dlp channel lookup failed: {channel_url}")
        print(result.stderr[-2000:])

    candidates.sort(key=lambda item: 0 if item[1] == "is_live" else 1)
    return list(dict.fromkeys(video_id for video_id, _ in candidates))


def extract_youtube_hls(video_url):
    """Resolve YouTube Live to HLS, preferring clients that avoid GVS PO-token checks.

    Current yt-dlp documentation says HLS live streams do not require a PO token
    for GVS (except iOS). web_safari exposes HLS formats, while embedded clients
    can avoid the normal logged-in web request when the video is embeddable.
    """
    video_id = youtube_video_id(video_url)
    if not video_id:
        return None

    canonical_url = f"https://www.youtube.com/watch?v={video_id}"
    client_attempts = [
        "youtube:player_client=web_safari",
        "youtube:player_client=web_embedded",
        "youtube:player_client=tv_embedded",
        "youtube:player_client=tv",
    ]

    for extractor_args in client_attempts:
        result = subprocess.run(
            [
                "yt-dlp", "--no-warnings", "--ignore-config",
                "--extractor-args", extractor_args,
                "--get-url",
                "-f", "best[protocol^=m3u8]/best",
                canonical_url,
            ],
            capture_output=True, text=True, timeout=120, check=False,
        )

        for value in result.stdout.splitlines():
            value = value.strip()
            if ".m3u8" in value and value.startswith("http"):
                return value

        if result.stderr:
            error = result.stderr.strip().replace("\n", " ")
            print(f"yt-dlp {extractor_args} failed for {video_id}: {error[-1200:]}")

    return None


def resolve_youtube_stream(channel_url, seed_video_url):
    try:
        video_ids = get_channel_candidates(channel_url)
        seed_id = youtube_video_id(seed_video_url)
        if seed_id:
            video_ids.append(seed_id)
        video_ids = list(dict.fromkeys(video_ids))

        print(f"YouTube candidates for {channel_url}: {len(video_ids)}")
        for video_id in video_ids:
            print(f"Trying YouTube video: {video_id}")
            stream = extract_youtube_hls(f"https://www.youtube.com/watch?v={video_id}")
            if stream:
                print(f"Resolved YouTube HLS: {video_id}")
                return stream
    except Exception as exc:
        print(f"YouTube resolver error for {channel_url}: {exc}")
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
    resolved = []

    for index, name in enumerate(["MOMO購物台 1", "MOMO購物台 2"]):
        tvg_id = f"MOMO{index + 1}"
        stream = momo_streams[index] if index < len(momo_streams) else existing.get(tvg_id)
        if stream:
            lines += [f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{name}" group-title="MOMO",{name}', stream, ""]
            resolved.append((tvg_id, name, stream))

    for tvg_id, name, channel_url, seed_video_url in YOUTUBE_SOURCES:
        stream = resolve_youtube_stream(channel_url, seed_video_url)
        previous = existing.get(tvg_id)
        if not stream and is_youtube_stream(previous):
            stream = previous
            print(f"Using previous resolved stream for {tvg_id}")

        if stream and is_youtube_stream(stream):
            lines += [f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{name}" group-title="MOMO YouTube",{name}', stream, ""]
            resolved.append((tvg_id, name, stream))

    print(f"Resolved {len(resolved)}/4 required streams")
    for tvg_id, name, stream in resolved:
        print(f"OK   {tvg_id} | {name} | {stream}")

    if len(resolved) != 4:
        raise RuntimeError("Expected exactly 4 playable MOMO streams")

    W3U.write_text("\n".join(lines), encoding="utf-8")
    print("MOMO IPTV playlist updated")


if __name__ == "__main__":
    main()
