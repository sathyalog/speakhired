"""Technical vocabulary, used in both directions.

Speech out: a voice reads "ChatGPT" as "cheat", "GPT" as a word, "kubectl" as gibberish. `prepare_speech` rewrites text so
the voice says it the way an engineer would ("Chat G P T", "cube control").
Speech in: recognisers hear "chat gpt" or "post gress". `correct_transcript` puts the standard spelling back, and
`whisper_prompt` primes the recogniser with the words this interview is likely to contain (the question, the job's stack).
"""
import json
import re
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

# Misheard spellings that are also real words or names: only fixed when the interview context contains the real term.
LOOSE = {"sequel", "jason", "pseudo", "red is", "lama", "jupiter notebook", "express", "rest", "cloud", "pass", "view", "spark"}
SPELL_OUT_SKIP = {"OK", "I", "A", "US", "AM", "PM", "AI", "OR", "AND", "IT"}   # handled separately or read as words
POPULAR = ["ChatGPT", "Claude", "Anthropic", "OpenAI", "LLM", "Kubernetes", "Kafka", "PostgreSQL", "Redis", "Docker", "AWS", "GraphQL", "gRPC",
           "OAuth", "Terraform", "CI/CD", "microservices", "React", "TypeScript", "Spring Boot", "Node.js", "FastAPI", "Django", "MongoDB", "REST API"]

_TECH_TOKEN = re.compile(r"\b(?:[A-Z][a-z]+[A-Z]\w*|[A-Za-z]+\.js|[A-Z]{2,}\d*[a-z]?|[A-Za-z]+-\d+\w*|[A-Z][a-z]+(?:\s[A-Z][a-z]+)?(?=\s(?:models?|API|SDK|framework)\b))")


@lru_cache(maxsize=1)
def _bank() -> dict:
    raw = json.loads((Path(__file__).resolve().parent.parent / "data" / "termbank.json").read_text(encoding="utf-8"))
    terms = raw["terms"]
    by_lower = {t["term"].lower(): t for t in terms}
    heard: dict[str, str] = {}
    for t in terms:
        for h in t.get("heard", []):
            heard[h.lower()] = t["term"]
    return {"terms": terms, "by_lower": by_lower, "heard": heard, "as_word": set(raw.get("say_as_word", []))}


def _boundary(term: str, flags: int = re.I) -> re.Pattern:
    body = r"\s+".join(re.escape(p) for p in term.split())
    return re.compile(r"(?<![\w+#.])" + body + r"(?![\w+#])", flags)


# ---------------------------------------------------------------- speech out
_PUNCT = [("‑", "-"), ("‐", "-"), ("‒", "-"), ("–", ", "), ("—", ", "), ("―", ", "), ("‘", "'"), ("’", "'"),
          ("“", '"'), ("”", '"'), ("…", "..."), ("≈", " about "), ("→", " to "), ("↔", " and "), ("×", " times "),
          (" ", " "), (" ", " "), ("​", ""), ("%", " percent"), ("&", " and "), ("+", " plus ")]


@lru_cache(maxsize=1)
def _speech_rules() -> list[tuple[re.Pattern, str]]:
    rules = []
    for t in sorted(_bank()["terms"], key=lambda x: -len(x["term"])):
        say = t.get("say")
        if say:
            rules.append((_boundary(t["term"]), say))
    return rules


def _spell(m: re.Match) -> str:
    w = m.group()
    if w in _bank()["as_word"] or w in SPELL_OUT_SKIP or len(w) > 6:
        return w
    return " ".join(w)


def prepare_speech(text: str) -> str:
    """Text as an engineer would say it aloud."""
    t = text
    for a, b in _PUNCT:
        if a == "+":
            t = re.sub(r"(?<=\w)\+(?=\w)", b, t)  # only a plus between words; C++ is handled as a term
        else:
            t = t.replace(a, b)
    t = re.sub(r"[*`]+|(?m:^[#>\s]+)", lambda m: "" if m.group().strip() else m.group(), t)   # markdown marks (but not the # in C#)
    t = re.sub(r"(?<=\w)/(?=\w)", " ", t)              # client/server
    for rx, say in _speech_rules():
        t = rx.sub(say, t)
    t = re.sub(r"\bOK\b", "okay", t)
    t = re.sub(r"(?<![\w-])[A-Z]{2,6}(?![\w-])", _spell, t)
    t = re.sub(r"\s+", " ", t).strip()
    return t if t[-1:] in ".!?" else t + "." if t else t


# ---------------------------------------------------------------- speech in
def context_terms(*texts: str, extra: list[str] | None = None, limit: int = 40) -> list[str]:
    """Technical terms this interview is likely to mention: from the question, rubric and the job's stack."""
    found: list[str] = []

    def add(term: str) -> None:
        term = term.strip()
        if term and term.lower() not in {f.lower() for f in found}:
            found.append(term)

    joined = " \n".join(texts)
    for t in _bank()["terms"]:
        if _boundary(t["term"]).search(joined):
            add(t["term"])
    for m in _TECH_TOKEN.findall(joined):
        if len(m) >= 3 and m.lower() not in {"the", "what", "when", "how", "why", "tell", "you"}:
            add(_bank()["by_lower"].get(m.lower(), {}).get("term", m))
    for e in extra or []:
        add(e)
    return found[:limit]


def whisper_prompt(terms: list[str]) -> tuple[str, str]:
    """(initial_prompt, hotwords) for the speech recogniser. The prompt keeps a casual tone so fillers are not silently dropped."""
    vocab = [*[p for p in POPULAR if p.lower() not in {t.lower() for t in terms}][:18], *terms[:25]]
    prompt = "Um, so, in this technical interview I talked about " + ", ".join(vocab) + ". Uh, yeah."
    return prompt, " ".join(terms[:20])


AMBIGUOUS = {"Express", "Spark", "Flask", "Helm", "Lambda", "Gemini", "Angular", "React", "Redux", "Airflow", "Snowflake", "Pinecone", "Confluence", "Agile",
             "Scrum", "Kanban", "Azure", "Git", "Linux", "Tableau", "Jupyter", "Hibernate", "Vite", "Tailwind", "Vue", "Llama", "Mistral", "Lambda"}


def correct_transcript(text: str, terms: list[str] | None = None) -> tuple[str, list[tuple[str, str]]]:
    """Fix how technical terms were written. Returns (text, [(heard, fixed)])."""
    terms = terms or []
    context_lower = {t.lower() for t in terms}
    changes: list[tuple[str, str]] = []
    out = text

    def swap(rx: re.Pattern, canon: str) -> None:
        nonlocal out

        def repl(m: re.Match) -> str:
            if m.group() != canon:
                changes.append((m.group(), canon))
            return canon
        out = rx.sub(repl, out)

    bank = _bank()
    for heard, canon in sorted(bank["heard"].items(), key=lambda kv: -len(kv[0])):
        if heard in LOOSE and canon.lower() not in context_lower:
            continue
        swap(_boundary(heard), canon)
    # spelled-out letters: "g p t" -> GPT, when that is a known term
    def letters(m: re.Match) -> str:
        joined = re.sub(r"\s+", "", m.group()).upper()
        known = bank["by_lower"].get(joined.lower())
        if known or joined.lower() in context_lower:
            canon = known["term"] if known else next(t for t in terms if t.lower() == joined.lower())
            changes.append((m.group(), canon))
            return canon
        return m.group()
    out = re.sub(r"(?<![\w-])(?:[A-Za-z]\s){1,4}[A-Za-z](?![\w-])", letters, out)
    # a term written with the wrong spacing or case ("Chat Gpt", "node js", "kubernetes")
    # (plain words such as Express, Spark or Flask are only touched when this interview's context mentions them)
    def distinctive(t: str) -> bool:
        return bool(re.search(r"[A-Z].*[A-Z]|[\d.+#\s-]", t)) or (t[:1].isupper() and t not in AMBIGUOUS) or t.lower() in context_lower
    for t in dict.fromkeys([*terms, *[x["term"] for x in bank["terms"]]]):
        if distinctive(t):
            swap(_boundary(t), t)
    # two or three words that together sound like a context term ("post gress ql")
    words = re.findall(r"\S+", out)
    for term in terms:
        key = re.sub(r"[^a-z0-9]", "", term.lower())
        if len(key) < 6:
            continue
        for n in (3, 2):
            i = 0
            while i + n <= len(words):
                window = " ".join(words[i:i + n])
                flat = re.sub(r"[^a-z0-9]", "", window.lower())
                if flat != key and abs(len(flat) - len(key)) <= 2 and SequenceMatcher(None, flat, key).ratio() >= 0.84:
                    trail = re.search(r"[.,;:!?]+$", window)
                    words[i:i + n] = [term + (trail.group() if trail else "")]
                    changes.append((window, term))
                i += 1
        out = " ".join(words)
    return out, changes
