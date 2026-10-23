"""GitHub Actions calls a persistent runtime; it never hosts the CRM database."""

from __future__ import annotations

import json
import os
import sys
from urllib.parse import urlsplit

import requests


def main():
    base = os.getenv("LEAD_ENGINE_URL", "").rstrip("/")
    token = os.getenv("LEAD_ENGINE_ADMIN_TOKEN", "")
    parsed = urlsplit(base)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or len(token) < 32
    ):
        print(json.dumps({"status": "blocked", "code": "persistent_runtime_not_configured"}))
        return 2
    dry = os.getenv("DRY_RUN", "1").lower() not in {"0", "false"}
    headers = {"Authorization": f"Bearer {token}"}

    def call(method, path, body=None):
        # Redirects are forbidden: never forward the admin credential elsewhere.
        r = requests.request(method, base + path, json=body, headers=headers, timeout=240, allow_redirects=False)
        if r.status_code != 200:
            raise RuntimeError(f"runtime_http_{r.status_code}")
        return r.json()

    try:
        readiness = call("GET", "/api/readiness")
        if dry:
            print(json.dumps({"status": "dry_run", "readiness": readiness, "external_writes": False}))
            return 0
        acquisition_paused = readiness.get("controls", {}).get("acquisition", {}).get("paused", False)
        if not readiness["discovery"]["ready"] and not acquisition_paused:
            print(json.dumps({"status": "blocked", "code": "runtime_discovery_configuration_missing"}))
            return 2
        query = (os.getenv("LEAD_QUERY") or "").strip()
        limit = max(1, min(int(os.getenv("LEAD_LIMIT") or "20"), 20))
        if acquisition_paused:
            discovery = {"status": "paused", "code": "acquisition_paused"}
        elif query:
            discovery = call("POST", "/api/discover", {"query": query, "limit": limit})
        elif readiness.get("portfolio", {}).get("enabled"):
            discovery = call("POST", "/api/portfolio/tick", {"limit": limit})
        else:
            print(json.dumps({"status": "blocked", "code": "portfolio_disabled_and_no_explicit_query"}))
            return 2
        if discovery.get("status") not in {"completed", "paused"}:
            print(json.dumps(discovery))
            return 2
        counts = {}
        for _ in range(80):
            outcome = call("POST", "/api/worker/tick")["result"]
            if outcome == "idle":
                break
            counts[outcome] = counts.get(outcome, 0) + 1
            if outcome == "blocked":
                break
        # Sending is explicitly enabled only on the persistent runtime.
        sends = {}
        if readiness["outreach"]["enabled"] and not counts.get("blocked"):
            for _ in range(limit):
                outcome = call("POST", "/api/outreach/tick")["result"]
                sends[outcome] = sends.get(outcome, 0) + 1
                if outcome != "sent":
                    break
        status = "blocked" if counts.get("blocked") else ("failed" if counts.get("failed") else "completed")
        print(json.dumps({"status": status, "discovery": discovery, "jobs": counts, "sends": sends}))
        return 2 if status != "completed" else 0
    except (ValueError, KeyError, requests.RequestException, RuntimeError) as exc:
        # No exception strings from requests: they can contain secret-bearing URLs.
        print(json.dumps({"status": "failed", "code": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
