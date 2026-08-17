import re
from pathlib import Path
from urllib.request import Request, urlopen

PAGE_URL = "https://m.momoshop.com.tw/live.momo"
BASE_URLS = [
    "https://livestream-source.momoshop.com.tw/live/{id}.m3u8",
    "https://livestream-dev-source.momoshop.com.tw/live/{id}.m3u8",
]
# Official MOMO live pages previously exposed these two live streams.
# They are fallbacks only; the script always prefers IDs discovered from MOMO's live page.
FALLBACK_IDS = [
    "0601100008j8dsB000",
    "0527090004rwwhA000",
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


def resolve_stream(live_id):
    for base in BASE_URLS:
        stream = base.format(id=live_id)
        if stream_works(stream):
            return stream
    return None


def main():
    try:
        html = fetch(PAGE_URL)
        discovered = find_ids(html)
    except Exception as exc:
        print(f"Could not fetch official MOMO live page: {exc}")
        discovered = []

    # Prefer IDs currently exposed by MOMO; use official historical IDs only as fallback.
    candidate_ids = list(dict.fromkeys(discovered + FALLBACK_IDS))
    streams = []
    seen = set()

    for live_id in candidate_ids:
        stream = resolve_stream(live_id)
        if stream and stream not in seen:
            streams.append(stream)
            seen.add(stream)
        if len(streams) == 2:
            break

    if not streams:
        raise RuntimeError("No playable MOMO HLS streams found")

    names = ["MOMO購物台 1", "MOMO購物台 2"]
    lines = ["#EXTM3U", ""]
    for index, stream in enumerate(streams):
        name = names[index]
        lines.append(
            f'#EXTINF:-1 tvg-id="MOMO{index + 1}" tvg-name="{name}" group-title="MOMO",{name}'
        )
        lines.append(stream)
        lines.append("")

    W3U.write_text("\n".join(lines), encoding="utf-8")
    print(f"Updated {len(streams)} MOMO live stream(s)")
    for stream in streams:
        print(stream)


if __name__ == "__main__":
    main()
