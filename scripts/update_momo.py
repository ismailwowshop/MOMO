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
    """Return the official MOMO CDN URL without probing the live segment.

    GitHub Actions runners may be unable to fetch a live playlist even when
    IPTV clients can play it. Therefore URL discovery must not depend on a
    successful HTTP probe from the runner.
    """
    for base in BASE_URLS:
        return base.format(id=live_id)
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
    streams_by_id = {}

    for live_id in candidate_ids:
        stream = resolve_momo_stream(live_id)
        if stream:
            streams_by_id[live_id] = stream
            print(f"Resolved MOMO live ID {live_id}: {stream}")

    # The two verified official MOMO live IDs are the source channels we need.
    # Keep the four legacy playlist IDs for compatibility, but do not pretend
    # that CH48/CH35 are four different underlying streams.
    ch48 = streams_by_id.get(FALLBACK_IDS[0]) or existing.get("MOMO1")
    ch35 = streams_by_id.get(FALLBACK_IDS[1]) or existing.get("MOMO2")

    entries = [
        ("MOMO1", "MOMO購物台 1", ch48),
        ("MOMO2", "MOMO購物台 2", ch35),
        ("MOMO48", "MOMO CH48", ch48),
        ("MOMO35", "MOMO CH35", ch35),
    ]

    resolved = [(tvg_id, name, url) for tvg_id, name, url in entries if url]

    print(f"Resolved {len(resolved)}/4 playlist entries")
    for tvg_id, name, stream in resolved:
        print(f"OK   {tvg_id} | {name} | {stream}")

    if len(resolved) != 4:
        raise RuntimeError("Could not resolve the required MOMO playlist entries")

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
