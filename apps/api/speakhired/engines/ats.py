"""Resume Radar: ATS-readiness estimate. Deterministic checks plus a judged content score.

There is no public formula for real ATS products, so this is an estimate built on widely documented
parsing and matching practice (clean single-column text, standard headings, contact details, keywords).
"""
import json
import re
from functools import lru_cache
from pathlib import Path

from ..ingest.documents import ResumeFacts
from ..privacy import has_phone
from ..schemas import AtsCheck, AtsKeywords, AtsSection

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
PHONE = re.compile(r"(?<!\w)(\+?\d[\d\s().-]{8,}\d)(?!\w)")
LINKS = re.compile(r"linkedin\.com/\S+|github\.com/\S+", re.I)
BULLET = re.compile(r"^\s*(?:[^\w\s(\"'#@|/\\<>]{1,2}|\d+[.)])\s+(.+)$")
FIRST_PERSON = re.compile(r"\b(i|my|me)\b", re.I)
SYMBOLS = re.compile(r"[☀-➿-\U0001F300-\U0001FAFF]")
NUMBER = re.compile(r"\d|%|\$|₹")

HEADINGS = {
    "summary": ["summary", "professional summary", "profile", "objective", "career objective", "about me"],
    "experience": ["experience", "work experience", "professional experience", "employment", "employment history", "work history"],
    "education": ["education", "academic background", "qualifications", "academics"],
    "skills": ["skills", "technical skills", "key skills", "core competencies", "technologies", "tech stack"],
    "projects": ["projects", "key projects", "personal projects", "academic projects"],
}
ACTION_VERBS = set("""achieved administered analysed analyzed architected automated built championed collaborated configured created
cut delivered deployed designed developed directed drove eliminated enabled engineered enhanced established executed expanded
fixed generated handled implemented improved increased integrated introduced launched led maintained managed measured migrated
mentored modernised modernized monitored negotiated optimised optimized orchestrated organised organized owned partnered planned
prevented produced programmed reduced refactored released replaced resolved restructured reviewed scaled secured shipped simplified
solved spearheaded streamlined supported tested trained transformed upgraded wrote""".split())
BUZZWORDS = ["team player", "hard-working", "hardworking", "go-getter", "results-driven", "self-starter", "synergy", "think outside the box",
             "detail-oriented", "passionate", "dynamic", "highly motivated", "fast learner"]
MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
DATE_STYLES = {
    "month_year": re.compile(rf"\b{MONTHS}\s+\d{{4}}\b", re.I),
    "numeric": re.compile(r"\b\d{1,2}/\d{4}\b"),
    "year_only": re.compile(r"\b(?:19|20)\d{2}\s*[-–—to]+\s*(?:(?:19|20)\d{2}|present|current)\b", re.I),
}

# (section id, display name, max points)
SECTIONS = [("format", "Format and parseability", 25), ("structure", "Contact and structure", 20),
            ("content", "Content strength", 25), ("keywords", "Keyword match", 20), ("readability", "Readability and length", 10)]


@lru_cache(maxsize=1)
def _aliases() -> dict[str, list[str]]:
    raw = json.loads((Path(__file__).resolve().parent.parent / "data" / "skill_aliases.json").read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def lines_of(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def bullets_of(text: str) -> list[str]:
    return [m.group(1).strip() for ln in lines_of(text) if (m := BULLET.match(ln))]


def found_headings(text: str) -> set[str]:
    found = set()
    for ln in lines_of(text):
        low = re.sub(r"[:\-–—_•]+", " ", ln.lower()).strip()
        if len(low) > 40:
            continue
        for key, names in HEADINGS.items():
            if low in names:
                found.add(key)
    return found


def date_styles(text: str) -> dict[str, int]:
    return {k: len(rx.findall(text)) for k, rx in DATE_STYLES.items() if rx.search(text)}


def action_verb_ratio(bullets: list[str]) -> float:
    if not bullets:
        return 0.0
    return sum(1 for b in bullets if re.findall(r"[a-z]+", b.lower())[:1] and re.findall(r"[a-z]+", b.lower())[0] in ACTION_VERBS) / len(bullets)


def quantified_ratio(bullets: list[str]) -> float:
    return sum(1 for b in bullets if NUMBER.search(b)) / len(bullets) if bullets else 0.0


def weak_bullets(bullets: list[str], limit: int = 5) -> list[str]:
    """Bullets without an action verb or any number, longest first (most room to improve)."""
    weak = [b for b in bullets if not NUMBER.search(b) or not (re.findall(r"[a-z]+", b.lower())[:1] or [""])[0] in ACTION_VERBS]
    return sorted(weak, key=len, reverse=True)[:limit]


def run_checks(f: ResumeFacts) -> list[AtsCheck]:
    text = f.text
    words = len(text.split())
    bullets = bullets_of(text)
    heads = found_headings(text)
    styles = date_styles(text)
    c: list[AtsCheck] = []

    def add(cid, section, label, ok, detail="", credit=None):
        c.append(AtsCheck(id=cid, section=section, label=label, passed=ok, credit=(1.0 if ok else 0.0) if credit is None else credit, detail=detail))

    # --- format and parseability
    add("extractable", "format", "Text can be read by a machine", f.extractable,
        "" if f.extractable else "Little or no text could be extracted. This looks like a scanned or image-only file, which most ATS cannot read.")
    add("file_type", "format", "Standard file type (PDF or Word)", f.file_type in ("pdf", "docx"), f.file_type.upper())
    pages_ok = f.pages <= 2
    add("pages", "format", "One or two pages", pages_ok, f"{f.pages} page(s)", credit=1.0 if pages_ok else (0.5 if f.pages == 3 else 0.0))
    add("tables", "format", "No tables for layout", f.tables == 0, f"{f.tables} table(s) found" if f.tables else "")
    add("images", "format", "No images or graphics", f.images == 0, f"{f.images} image(s) found" if f.images else "")
    add("text_boxes", "format", "No text boxes", f.text_boxes == 0, f"{f.text_boxes} text box(es) found" if f.text_boxes else "")
    add("columns", "format", "Single-column layout", not f.columns_likely, "Looks like a multi-column layout" if f.columns_likely else "")
    # --- contact and structure
    head_contact = bool(EMAIL.search(f.header_footer_text) or has_phone(f.header_footer_text))
    add("email", "structure", "Email address present", bool(EMAIL.search(text)),
        "Contact details only in the header or footer may be skipped by some ATS" if head_contact and not EMAIL.search(text) else "",
        credit=1.0 if EMAIL.search(text) else (0.4 if head_contact else 0.0))
    add("phone", "structure", "Phone number present", has_phone(text))
    add("profile_link", "structure", "LinkedIn or GitHub link present", bool(LINKS.search(text)))
    for key, label, weight_note in [("experience", "Experience section with a standard heading", ""), ("education", "Education section with a standard heading", ""),
                                    ("skills", "Skills section with a standard heading", ""), ("summary", "Short summary at the top", "")]:
        add(key, "structure", label, key in heads)
    # only month-name and numeric dates clash; "2017 - 2021" next to "Jan 2021" is normal on a resume
    clash = {k: v for k, v in styles.items() if k in ("month_year", "numeric")}
    consistent = len(clash) < 2 or max(clash.values()) / sum(clash.values()) >= 0.75
    add("dates", "structure", "Dates use one consistent format", consistent, "Mixed date formats: " + ", ".join(clash) if not consistent else "")
    # --- readability and length
    ok_len = 250 <= words <= 900
    add("length", "readability", "Length is 250 to 900 words", ok_len, f"{words} words", credit=1.0 if ok_len else (0.5 if 150 <= words <= 1200 else 0.0))
    add("bullets", "readability", "Experience is written as bullet points", len(bullets) >= 5, f"{len(bullets)} bullet(s)")
    avg = sum(len(b.split()) for b in bullets) / len(bullets) if bullets else 0
    add("bullet_length", "readability", "Bullets are 8 to 28 words", 8 <= avg <= 28, f"average {avg:.0f} words" if bullets else "no bullets")
    add("no_first_person", "readability", "No first-person pronouns (I, my)", len(FIRST_PERSON.findall(text)) <= 2)
    found_buzz = [b for b in BUZZWORDS if b in text.lower()]
    add("buzzwords", "readability", "Few buzzwords", len(found_buzz) <= 1, ", ".join(found_buzz))
    add("symbols", "format", "No decorative symbols or icons", len(SYMBOLS.findall(text)) <= 3,
        "Icons and emoji can turn into odd characters when parsed" if len(SYMBOLS.findall(text)) > 3 else "")
    return c


# points inside each deterministic section (sum = section max)
WEIGHTS = {
    "extractable": 8, "file_type": 2, "pages": 4, "tables": 3, "images": 2, "text_boxes": 2, "columns": 3, "symbols": 1,
    "email": 4, "phone": 3, "profile_link": 3, "experience": 3, "education": 2, "skills": 3, "summary": 1, "dates": 1,
    "length": 3, "bullets": 2, "bullet_length": 2, "no_first_person": 1.5, "buzzwords": 1.5,
}


def score_sections(checks: list[AtsCheck], extractable: bool, content: dict[str, float] | None, kw: AtsKeywords) -> list[AtsSection]:
    maxes = {sid: m for sid, _, m in SECTIONS}
    names = {sid: n for sid, n, _ in SECTIONS}
    earned = {sid: 0.0 for sid in maxes}
    for ch in checks:
        earned[ch.section] += WEIGHTS[ch.id] * ch.credit
    if not extractable:  # nothing else can be trusted if the file is unreadable
        earned = {k: (v if k == "format" else 0.0) for k, v in earned.items()}
    out = [AtsSection(id="format", name=names["format"], score=round(earned["format"], 1), max=maxes["format"]),
           AtsSection(id="structure", name=names["structure"], score=round(earned["structure"], 1), max=maxes["structure"])]
    if content is not None and extractable:
        out.append(AtsSection(id="content", name=names["content"], score=round(maxes["content"] * sum(content.values()) / max(len(content), 1), 1), max=maxes["content"]))
    if kw.provided and extractable:
        total = len(kw.matched) + len(kw.missing)
        out.append(AtsSection(id="keywords", name=names["keywords"], score=round(maxes["keywords"] * (len(kw.matched) / total if total else 0), 1), max=maxes["keywords"]))
    out.append(AtsSection(id="readability", name=names["readability"], score=round(earned["readability"], 1), max=maxes["readability"]))
    return out


def total_score(sections: list[AtsSection], extractable: bool = True) -> int:
    """Sections that could not be judged (no job description, no model) are left out and the rest rescaled to 100.
    A file with no readable text cannot pass an ATS at all, so it is capped low."""
    mx = sum(s.max for s in sections)
    score = round(100 * sum(s.score for s in sections) / mx) if mx else 0
    return score if extractable else min(score, 15)


# Critical problems limit the best possible score, however good the rest looks.
CAPS = [("email", 69, "no email address in the page body"), ("experience", 69, "no recognisable Experience section"),
        ("tables", 74, "a table is used for layout"), ("text_boxes", 74, "text boxes are used"), ("columns", 74, "a multi-column layout")]


def apply_caps(score: int, checks: list[AtsCheck]) -> tuple[int, list[str]]:
    failed = {c.id for c in checks if c.credit < 1.0}
    hits = [(cap, why) for cid, cap, why in CAPS if cid in failed and score > cap]
    if not hits:
        return score, []
    cap = min(c for c, _ in hits)
    return cap, [f"The score is capped at {cap} because of: " + "; ".join(why for _, why in hits) + "."]


def grade(score: int) -> str:
    return "Excellent" if score >= 85 else "Good" if score >= 70 else "Fair" if score >= 50 else "Needs work"


# ---------- keywords ----------
def _has(text_low: str, term: str) -> bool:
    return bool(re.search(r"(?<![a-z0-9+#.])" + re.escape(term.lower()) + r"(?![a-z0-9+#])", text_low))


def _variants(keyword: str) -> set[str]:
    k = keyword.lower().strip()
    out = {k}
    for canon, alts in _aliases().items():
        group = {canon, *alts}
        if k in group:
            out |= group
    return out


def match_keywords(resume_text: str, keywords: list[str]) -> AtsKeywords:
    low = resume_text.lower()
    matched, missing, seen = [], [], set()
    for kw in keywords:
        key = kw.lower().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        (matched if any(_has(low, v) for v in _variants(key)) else missing).append(kw.strip())
    return AtsKeywords(provided=True, matched=matched, missing=missing)


def vocabulary_keywords(jd_text: str) -> list[str]:
    """Skills from the built-in vocabulary that the job description mentions (works without any model)."""
    low = jd_text.lower()
    return [canon for canon, alts in _aliases().items() if any(_has(low, v) for v in {canon, *alts} if len(v) > 1)]
