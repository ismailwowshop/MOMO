import re
from pathlib import Path
from urllib.request import Request, urlopen

PAGE_URL = "https://m.momoshop.com.tw/live.momo"
BASE_URLS = [
    "https://livestream-source.momoshop.com.tw/live/{id}.m3u8",
    "https://livestream-dev-source.momoshop.com.tw/live/{id}.m3u8",
]
W3U = Path("MOMO.w3u")


def fetch(url):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="ignore")


def main():
    html = fetch(PAGE_URL)
    ids = []
    for pattern in [
        r"liveId[=:/\\\"']+([A-Za-z0-9]+)",
        r"live[/\\]([A-Za-z0-9]+)\\?orientation",
    ]:
        ids.extend(re.findall(pattern, html))

    # Keep order and remove duplicates / invalid short values.
    ids = list(dict.fromkeys(x for x in ids if len(x) >= 8))
    if not ids:
        raise RuntimeError("No MOMO liveId found on official live page")

    for live_id in ids:
        for base in BASE_URLS:
            stream = base.format(id=live_id)
            try:
                req = Request(stream, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
                with urlopen(req, timeout=15) as response:
                    if response.status < 400:
                        content = (
                            "#EXTM3U\n\n"
                            '#EXTINF:-1 tvg-id="MOMO" tvg-name="MOMO購物台" group-title="Taiwan",MOMO購物台\n'
                            + stream + "\n"
                        )
                        W3U.write_text(content, encoding="utf-8")
                        print(f"Updated MOMO stream: {stream}")
                        return
            except Exception:
                continue

    raise RuntimeError("MOMO live IDs were found, but no playable HLS stream responded")


if __name__ == "__main__":
    main()
