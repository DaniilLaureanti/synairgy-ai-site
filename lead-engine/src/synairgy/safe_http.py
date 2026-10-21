"""Bounded public-web fetching with IP-pinned connections and redirect checks."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import urllib3

MAX_BYTES = 2_000_000
USER_AGENT = "SynAirgyLeadEngine/2.0 (+https://synairgy.ai)"


def public_target(url: str) -> tuple[str, str, int, str]:
    parsed = urlsplit(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("invalid_public_url")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in {80, 443}:
        raise ValueError("unsupported_port")
    hostname = parsed.hostname.encode("idna").decode("ascii")
    addresses = sorted({item[4][0] for item in socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)})
    if not addresses or any(not ipaddress.ip_address(addr).is_global for addr in addresses):
        raise ValueError("non_public_address")
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return hostname, addresses[0], port, path


def get_public(url: str, timeout: int = 10) -> tuple[int, str, bytes, str]:
    for _ in range(6):
        hostname, address, port, path = public_target(url)
        parsed = urlsplit(url)
        if parsed.scheme == "https":
            pool = urllib3.HTTPSConnectionPool(address, port, server_hostname=hostname, assert_hostname=hostname)
        else:
            pool = urllib3.HTTPConnectionPool(address, port)
        response = None
        try:
            host_header = f"[{hostname}]" if ":" in hostname else hostname
            if port != (443 if parsed.scheme == "https" else 80):
                host_header += f":{port}"
            response = pool.request(
                "GET",
                path,
                headers={"Host": host_header, "User-Agent": USER_AGENT, "Accept": "text/html,text/plain"},
                timeout=urllib3.Timeout(total=timeout),
                retries=False,
                redirect=False,
                preload_content=False,
            )
            if response.status in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location")
                if not location:
                    raise ValueError("invalid_redirect")
                target = urljoin(url, location)
                if parsed.scheme == "https" and urlsplit(target).scheme != "https":
                    raise ValueError("insecure_redirect")
                url = target
                continue
            body = response.read(MAX_BYTES + 1, decode_content=True)
            if len(body) > MAX_BYTES:
                raise ValueError("response_too_large")
            return response.status, response.headers.get("Content-Type", ""), body, url
        finally:
            if response is not None:
                response.close()
            pool.close()
    raise ValueError("too_many_redirects")
