import ipaddress
import socket
from urllib.parse import urlparse

import httpx
import trafilatura


def _assert_public(url: str) -> None:
    """Block SSRF: JD fetching must only hit public web hosts."""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("invalid URL")
    for info in socket.getaddrinfo(u.hostname, None):
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            raise ValueError("URL resolves to a private address")


async def fetch_jd_text(url: str) -> str:
    _assert_public(url)
    async with httpx.AsyncClient(timeout=20, follow_redirects=False, headers={"User-Agent": "SpeakHired/0.1"}) as client:
        r = await client.get(url)
        r.raise_for_status()
    text = trafilatura.extract(r.text) or ""
    if len(text) < 200:
        raise ValueError("couldn't read the job description from that page. Paste the text instead.")
    return text
