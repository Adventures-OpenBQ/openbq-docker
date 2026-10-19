"""Container readiness includes the selected store, without command-line secrets."""
import base64
import os
import urllib.request
from .config import backend


def main():
    try:
        headers = {}
        path = "/widgets.json"
        if backend() == "postgresql":
            if os.environ.get("OPENBQ_SETTINGS_GATEWAY_STATE") == "1":
                path = "/_openbq/settings/v1/state/0"
                headers["Authorization"] = "Bearer " + os.environ["GATEWAY_TOKEN"]
            else:
                path = "/pro/user"
                pair = os.environ["OPENBB_API_USERNAME"] + ":" + os.environ["OPENBB_API_PASSWORD"]
                headers["Authorization"] = "Basic " + base64.b64encode(pair.encode()).decode()
        with urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:6900" + path, headers=headers), timeout=8) as response:
            return 0 if response.status == 200 else 1
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
