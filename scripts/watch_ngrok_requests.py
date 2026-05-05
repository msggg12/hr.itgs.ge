from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.request import urlopen


API_ROOT = "http://127.0.0.1:4040/api/requests/http"
OUTPUT_PATH = Path("tmp/dahua-webhook-capture.log")
POLL_SECONDS = 2


def get_json(url: str) -> dict:
    with urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    if OUTPUT_PATH.exists():
        for line in OUTPUT_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            request_id = record.get("request_id")
            if request_id:
                seen.add(request_id)

    while True:
        try:
            listing = get_json(API_ROOT)
            requests = listing.get("requests", [])
            for item in requests:
                request_id = item.get("id")
                if not request_id or request_id in seen:
                    continue
                detail = get_json(f"{API_ROOT}/{request_id}")
                output = {
                    "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "request_id": request_id,
                    "uri": item.get("uri"),
                    "method": item.get("method"),
                    "headers": detail.get("request", {}).get("headers", {}),
                    "raw": detail,
                }
                with OUTPUT_PATH.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(output, ensure_ascii=False) + "\n")
                seen.add(request_id)
        except Exception:
            pass
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
