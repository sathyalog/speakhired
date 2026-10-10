"""Public GitHub repos of a candidate, summarised for "proof points" (no login, no token).

Only the username goes to GitHub. Repo text is untrusted: it is redacted before any AI step and never treated as instructions.
"""
import base64
import re
import time
from dataclasses import dataclass, field

import httpx

API = "https://api.github.com"
USERNAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_cache: dict[str, tuple[float, list["RepoSummary"]]] = {}
CACHE_SECONDS = 3600
MAX_REPOS = 12          # most recently updated, non-fork repos
README_CHARS = 4000


class GithubError(Exception):
    pass


@dataclass
class RepoSummary:
    name: str
    url: str
    description: str = ""
    language: str = ""
    topics: list[str] = field(default_factory=list)
    updated: str = ""
    stars: int = 0
    readme: str = ""
    files: list[str] = field(default_factory=list)


def parse_profile(text: str) -> str:
    """Accepts `github.com/name`, `https://github.com/name/...` or a bare name; returns the username."""
    t = (text or "").strip().rstrip("/")
    if not t:
        return ""
    m = re.search(r"github\.com/([^/\s?#]+)", t, re.I)
    name = m.group(1) if m else t
    if not USERNAME.match(name):
        raise GithubError("That GitHub address doesn't look right. Use the form github.com/your-username.")
    return name


def _raise_for(r: httpx.Response, what: str) -> None:
    if r.status_code == 404:
        raise GithubError(f"GitHub could not find {what}. Check the address.")
    if r.status_code == 403 and r.headers.get("x-ratelimit-remaining") == "0":
        raise GithubError("GitHub's public limit has been reached for now. Try again in about an hour.")
    if r.status_code >= 400:
        raise GithubError(f"GitHub returned an error ({r.status_code}) for {what}.")


async def fetch_repos(username: str, client: httpx.AsyncClient | None = None) -> list[RepoSummary]:
    cached = _cache.get(username.lower())
    if cached and time.time() - cached[0] < CACHE_SECONDS:
        return cached[1]
    own = client is None
    client = client or httpx.AsyncClient(timeout=20, headers={"User-Agent": "SpeakHired", "Accept": "application/vnd.github+json"})
    try:
        r = await client.get(f"{API}/users/{username}/repos", params={"per_page": 100, "sort": "updated", "type": "owner"})
        _raise_for(r, f"the GitHub profile '{username}'")
        repos = [x for x in r.json() if not x.get("fork") and not x.get("archived")][:MAX_REPOS]
        out: list[RepoSummary] = []
        for x in repos:
            s = RepoSummary(name=x["name"], url=x["html_url"], description=x.get("description") or "", language=x.get("language") or "",
                            topics=x.get("topics") or [], updated=(x.get("updated_at") or "")[:10], stars=x.get("stargazers_count", 0))
            s.readme, s.files = await _readme_and_files(client, username, x["name"], x.get("default_branch") or "main")
            out.append(s)
    except httpx.HTTPError as e:
        raise GithubError("Couldn't reach GitHub. Check your internet connection.") from e
    finally:
        if own:
            await client.aclose()
    _cache[username.lower()] = (time.time(), out)
    return out


async def _readme_and_files(client: httpx.AsyncClient, owner: str, repo: str, branch: str) -> tuple[str, list[str]]:
    readme = ""
    r = await client.get(f"{API}/repos/{owner}/{repo}/readme")
    if r.status_code == 200:
        try:
            readme = base64.b64decode(r.json().get("content", "")).decode("utf-8", "ignore")[:README_CHARS]
        except (ValueError, KeyError):
            readme = ""
    t = await client.get(f"{API}/repos/{owner}/{repo}/git/trees/{branch}")
    files = [i["path"] for i in t.json().get("tree", []) if i.get("type") == "blob"][:80] if t.status_code == 200 else []
    return readme, files


def evidence_text(repos: list[RepoSummary]) -> dict[str, str]:
    """Everything a proof point is allowed to quote, per repo name."""
    return {r.name: "\n".join([r.description, r.readme, *r.files, *r.topics]) for r in repos}
