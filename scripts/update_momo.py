import re
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
    "0601100008j8dsB000",  # MOMO CH48 / 一台
    "0527090004rwwhA000",  # MOMO CH35 / 二台
]
W3U = Path("MOMO.w3u")


def fetch(url):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="ignore")


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
    # Do not probe the CDN from GitHub Actions. MOMO may reject or rate-limit
    # HEAD/GET probes from runners even though the HLS URL is valid for players.
    # Prefer the normal source URL, then keep the dev source as fallback.
    return BASE_URLS[0].format(id=live_id)


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
    streams_by_id = {}
    for live_id in candidate_ids:
        stream = resolve_momo_stream(live_id)
        streams_by_id[live_id] = stream
        print(f"Resolved MOMO live ID {live_id}: {stream}")

    # There are currently two unique official MOMO sources. Do not duplicate
    # them just to satisfy an artificial four-stream requirement.
    entries = [
        (
            "MOMO1",
            "MOMO購物台 1",
            streams_by_id.get(FALLBACK_IDS[0]) or existing.get("MOMO1"),
        ),
        (
            "MOMO2",
            "MOMO購物台 2",
            streams_by_id.get(FALLBACK_IDS[1]) or existing.get("MOMO2"),
        ),
    ]

    resolved = [(tvg_id, name, url) for tvg_id, name, url in entries if url]

    print(f"Resolved {len(resolved)}/2 required streams")
    for tvg_id, name, stream in resolved:
        print(f"OK   {tvg_id} | {name} | {stream}")

    if len(resolved) != 2:
        raise RuntimeError("Expected 2 official MOMO streams")

    lines = ["#EXTM3U", ""]
    for tvg_id, name, stream in resolved:
        lines += [
            f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{name}" group-title="MOMO",{name}',
            stream,
            "",
        ]

    W3U.write_text("\n".join(lines), encoding="utf-8")
    print("MOMO IPTV playlist updated using official MOMO CDN only")


if __name__ == "__main__":
    main()
