import base64
import json

import httpx
import pytest

from speakhired.agents import proof
from speakhired.engines import github
from speakhired.engines.github import GithubError, RepoSummary, evidence_text, parse_profile
from speakhired.llm import LLMUnavailable


def profile_client(repos, readmes=None, status=200, rate_limited=False):
    readmes = readmes or {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/users/alice/repos":
            if status != 200:
                return httpx.Response(status, json={"message": "Not Found"})
            if rate_limited:
                return httpx.Response(403, json={"message": "rate limit"}, headers={"x-ratelimit-remaining": "0"})
            return httpx.Response(200, json=repos)
        if path.endswith("/readme"):
            name = path.split("/")[3]
            if name in readmes:
                return httpx.Response(200, json={"content": base64.b64encode(readmes[name].encode()).decode()})
            return httpx.Response(404, json={})
        if "/git/trees/" in path:
            return httpx.Response(200, json={"tree": [{"path": "agents/crew.py", "type": "blob"}, {"path": "docs", "type": "tree"}]})
        return httpx.Response(404)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


REPOS = [
    {"name": "mcp-crew", "html_url": "https://github.com/alice/mcp-crew", "description": "Multi-agent CrewAI pipeline", "language": "Python",
     "topics": ["crewai", "agents"], "updated_at": "2026-05-01T10:00:00Z", "stargazers_count": 3, "default_branch": "main", "fork": False},
    {"name": "forked-thing", "html_url": "https://github.com/alice/forked-thing", "description": "copy", "fork": True},
    {"name": "old-site", "html_url": "https://github.com/alice/old-site", "description": "Static site", "language": "HTML", "topics": [],
     "updated_at": "2020-01-01T00:00:00Z", "fork": False, "archived": True},
]


@pytest.mark.parametrize("text, name", [
    ("github.com/alice", "alice"), ("https://github.com/alice/", "alice"), ("https://www.github.com/alice/mcp-crew", "alice"), ("alice", "alice"),
    ("", ""),
])
def test_profile_address_is_understood(text, name):
    assert parse_profile(text) == name


@pytest.mark.parametrize("bad", ["github.com/-bad-", "https://example.com/alice", "a b c", "x" * 45])
def test_bad_addresses_are_refused(bad):
    with pytest.raises(GithubError):
        parse_profile(bad)


async def test_only_own_non_fork_active_repos_are_read_and_readmes_kept():
    async with profile_client(REPOS, readmes={"mcp-crew": "Uses CrewAI agents."}) as client:
        repos = await github.fetch_repos("alice", client)
    assert [r.name for r in repos] == ["mcp-crew"]
    assert repos[0].readme == "Uses CrewAI agents." and repos[0].files == ["agents/crew.py"]


async def test_missing_profile_and_rate_limit_have_clear_messages():
    github._cache.clear()
    async with profile_client([], status=404) as client:
        with pytest.raises(GithubError) as e:
            await github.fetch_repos("nobody-here", client)
    assert "could not find" in str(e.value)
    github._cache.clear()
    async with profile_client([], rate_limited=True) as client:
        with pytest.raises(GithubError) as e:
            await github.fetch_repos("alice", client)
    assert "limit" in str(e.value)


async def test_results_are_cached_per_profile():
    github._cache.clear()
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=[]) if request.url.path == "/users/alice/repos" else httpx.Response(404)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await github.fetch_repos("alice", client)
        await github.fetch_repos("alice", client)
    assert calls.count("/users/alice/repos") == 1


class ProofLLM:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.seen = reply, error, []

    async def chat_json(self, system, user, schema, temperature=0.2):
        self.seen.append(user)
        if self.error:
            raise self.error
        return self.reply


CREW = RepoSummary(name="mcp-crew", url="https://github.com/alice/mcp-crew", description="Multi-agent CrewAI pipeline", language="Python",
                   topics=["crewai"], readme="Uses CrewAI agents to triage tickets.", files=["agents/crew.py"])


async def test_proof_point_for_a_real_match():
    llm = ProofLLM({"repo": "mcp-crew", "evidence": "Uses CrewAI agents", "claim": "You already built multi-agent workflows with CrewAI"})
    pp = await proof.find_proof(llm, "How would you use CrewAI agents?", "Use several agents.", [CREW])
    assert pp.repo == "mcp-crew" and pp.url.endswith("/mcp-crew") and "CrewAI" in pp.claim and pp.summary.startswith("Multi-agent")


async def test_invented_repo_or_evidence_is_dropped():
    assert await proof.find_proof(ProofLLM({"repo": "imaginary", "evidence": "x", "claim": "y"}), "q", "a", [CREW]) is None
    assert await proof.find_proof(ProofLLM({"repo": "mcp-crew", "evidence": "Kubernetes operators", "claim": "y"}), "q", "a", [CREW]) is None
    assert await proof.find_proof(ProofLLM({"repo": "mcp-crew", "evidence": "", "claim": "y"}), "q", "a", [CREW]) is None


async def test_no_repos_or_ai_failure_means_no_card():
    assert await proof.find_proof(ProofLLM({}), "q", "a", []) is None
    assert await proof.find_proof(ProofLLM(error=LLMUnavailable("x", "y")), "q", "a", [CREW]) is None
    assert await proof.find_proof(ProofLLM(error=ValueError("bad json")), "q", "a", [CREW]) is None


async def test_repo_text_is_redacted_before_the_model_sees_it():
    # emails and phone numbers are always removed; a name written mid-sentence is NOT detected (see the README limitation)
    secret = RepoSummary(name="notes", url="u", description="Built by priya@example.com", readme="Contact 9876543210 for details.")
    llm = ProofLLM({"repo": "", "evidence": "", "claim": ""})
    await proof.find_proof(llm, "q", "a", [secret])
    assert "priya@example.com" not in llm.seen[0] and "9876543210" not in llm.seen[0]


def test_evidence_index_covers_description_readme_files_and_topics():
    text = evidence_text([CREW])["mcp-crew"]
    assert "CrewAI" in text and "agents/crew.py" in text and "triage" in text


def test_offline_mode_never_contacts_github(monkeypatch):
    """Option 1: GitHub is only contacted in Online mode. Offline must not touch GitHub at all."""
    import tempfile
    from pathlib import Path
    from fastapi.testclient import TestClient
    from speakhired import main
    from speakhired.llm import ModeStore, RoutingLLM
    from test_api import FakeLLM
    from test_ats import GOOD, docx_bytes

    called = []

    async def spy(*a, **k):
        called.append(a)
        raise AssertionError("GitHub must not be contacted in Offline mode")
    monkeypatch.setattr(github, "fetch_repos", spy)
    main.mode_store = ModeStore(path=Path(tempfile.mkdtemp()) / "mode.json")
    main.mode_store.set("offline")
    main.llm = RoutingLLM(main.mode_store, FakeLLM(), main.grok)
    client = TestClient(main.app)
    body = client.post("/api/sessions", data={"round_no": "1", "jd_text": "We need Python and Kafka engineers for backend APIs and services.",
                                              "github_url": "github.com/alice"},
                       files={"resume": ("cv.docx", docx_bytes(GOOD), "application/octet-stream")}).json()
    assert called == [] and body.get("repos") == [] and "Online mode" in body["github_note"], body
