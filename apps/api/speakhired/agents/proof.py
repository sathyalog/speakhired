"""Proof points: a repo the candidate already built that matches an interview question. Evidence must be real."""
from ..engines.github import RepoSummary, evidence_text
from ..llm import LLM, LLMUnavailable
from ..privacy import Redactor
from ..schemas import ProofPoint

SYSTEM = (
    "You match an interview answer to a candidate's own GitHub repositories. Pick at most one repository that already implements what the "
    "question is about (for example, a question about CrewAI agents matches a repo that uses CrewAI). Only use the repositories given. "
    "'repo' must be copied exactly from the list. 'evidence' must be copied exactly from that repo's description, README or file list. "
    "If nothing clearly matches, return repo as an empty string. Never invent a repository, file or claim."
)


def _catalogue(repos: list[RepoSummary]) -> str:
    lines = []
    for r in repos:
        lines.append(f"- repo: {r.name}\n  description: {r.description or '(none)'}\n  languages/topics: {r.language} {', '.join(r.topics)}\n"
                     f"  files: {', '.join(r.files[:25]) or '(none)'}\n  readme excerpt: {r.readme[:700] or '(none)'}")
    return "\n".join(lines)


async def find_proof(llm: LLM, question: str, answer: str, repos: list[RepoSummary]) -> ProofPoint | None:
    if not repos:
        return None
    red = Redactor()
    prompt = f"Question: {question}\nModel answer: {answer}\n\nRepositories:\n{_catalogue(repos)}"
    schema = {"type": "object", "properties": {"repo": {"type": "string"}, "evidence": {"type": "string"}, "claim": {"type": "string"}},
              "required": ["repo", "evidence", "claim"]}
    try:
        d = await llm.chat_json(SYSTEM, red.clean(prompt), schema, temperature=0)
    except LLMUnavailable:
        return None
    except Exception:  # noqa: BLE001 - a bad answer from a model must not break feedback
        return None
    by_name = {r.name: r for r in repos}
    repo = by_name.get((d.get("repo") or "").strip())
    if repo is None:
        return None
    evidence = (d.get("evidence") or "").strip()
    if not evidence or evidence.lower() not in evidence_text(repos)[repo.name].lower():
        return None                      # the quoted evidence must really be in the repo's text
    return ProofPoint(repo=repo.name, url=repo.url, claim=(d.get("claim") or "").strip()[:240],
                      evidence=evidence[:200], summary=(repo.description or "")[:240] or "A public repository on the candidate's GitHub.")
