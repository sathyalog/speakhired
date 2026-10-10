"""Resume Radar orchestration: judge content (LEV or Ollama), match keywords, build suggestions."""
import re

from ..engines import ats
from ..ingest.documents import ResumeFacts
from ..llm import LLM, LLMUnavailable
from ..privacy import Redactor, describe
from ..reasoning.lev import LevClient, LevUnavailable
from ..reasoning.questions import MIN_CONFIDENCE, level_to_unit, resume_questions
from ..schemas import AtsKeywords, AtsReport, AtsSuggestion

STR_LIST = {"type": "array", "items": {"type": "string"}}
SCORE_KEYS = ["action_verbs", "quantified", "clarity", "specific_tech"]
# share of the content section each judged dimension is worth
CONTENT_WEIGHTS = {"has_summary": 0.12, "action_verbs": 0.24, "quantified": 0.28, "clarity": 0.16, "specific_tech": 0.20}


def prepare_for_remote(text: str) -> str:
    """Redacted, trimmed copy for any judge that is not on this computer: no names, contact details, IDs or addresses."""
    return Redactor().clean(text)[:5000]


def _norm(score: float) -> float:
    return max(0.0, min(1.0, (score - 1) / 4))


async def _judge_lev(lev: LevClient, text: str) -> tuple[dict[str, float], float]:
    ans = await lev.decide(prepare_for_remote(text), resume_questions())
    scores = {k: level_to_unit(ans[k]["score"]) for k in SCORE_KEYS if k in ans}
    scores["has_summary"] = float(ans.get("has_summary", {}).get("noul", 0.0))
    confs = [float(ans[k].get("confidence", 0)) for k in SCORE_KEYS if k in ans]
    return scores, (sum(confs) / len(confs) if confs else 0.0)


def condense_for_judge(text: str, limit: int = 2800) -> str:
    """The model only needs headings and bullets to judge content; sending less makes small local models much faster."""
    keep = [ln for ln in ats.lines_of(text) if ats.BULLET.match(ln) or len(ln) <= 40]
    out = "\n".join(keep)
    return (out if len(out) > 400 else text)[:limit]


async def _judge_llm(llm: LLM, text: str) -> dict[str, float]:
    dim = {"type": "integer", "minimum": 1, "maximum": 5}
    schema = {"type": "object", "properties": {"has_summary": {"type": "boolean"}, **{k: dim for k in SCORE_KEYS}}, "required": ["has_summary", *SCORE_KEYS]}
    d = await llm.chat_json(
        "You are a strict ATS and recruiter reviewer. Score the resume 1 (very poor) to 5 (excellent): action_verbs = bullets start with strong "
        "action verbs; quantified = bullets show measurable impact with numbers; clarity = concise, free of buzzwords; specific_tech = names "
        "concrete technologies in context. has_summary = a short professional summary opens the resume.", condense_for_judge(text), schema, temperature=0)
    return {**{k: _norm(float(d[k])) for k in SCORE_KEYS}, "has_summary": 1.0 if d["has_summary"] else 0.0}


async def judge_content(llm: LLM, lev: LevClient, text: str, use_lev: bool, use_ai: bool = True, online: bool = False, model_name: str = "Grok") -> tuple[dict[str, float] | None, str, list[str]]:
    """Returns (scores 0..1 per dimension or None, judge label, notes).

    Offline: LEV scores it when allowed, and Ollama only steps in if LEV is missing or unsure (a second slow call is avoided).
    Online: Grok always reviews it too, and the two sets of scores are averaged. Remote LEV is used only when the caller allowed it."""
    notes: list[str] = []
    if not use_ai:
        return _blend(None, text), "rules only", ["AI content check skipped for an instant score. Turn it on for a deeper review."]
    model = model_name if online else "Ollama"
    results: list[dict[str, float]] = []
    used: list[str] = []
    if lev.enabled and lev.is_remote and not use_lev:
        notes.append("LEV on your remote server was not used. Switch it on to include it (a redacted copy is sent).")
    if lev.enabled and (not lev.is_remote or use_lev):
        try:
            scores, conf = await _judge_lev(lev, text)
            if conf >= MIN_CONFIDENCE:
                results.append(scores)
                used.append("LEV")
            else:
                notes.append(f"LEV was unsure, so {model} double-checked.")
        except LevUnavailable as e:
            notes.append(f"LEV was unavailable ({e}).")
        except Exception:  # noqa: BLE001
            notes.append("LEV returned an unexpected answer.")
    if online or not results:
        try:
            results.append(await _judge_llm(llm, text))
            used.append(model)
        except LLMUnavailable as e:
            notes.append(e.message)
        except Exception:  # noqa: BLE001 - model offline or bad answer
            notes.append(f"{model} could not be reached.")
    if not results:
        notes.append("No AI model answered, so content strength is estimated from simple rules only.")
        return _blend(None, text), "rules only", notes
    merged = {k: sum(r.get(k, 0.0) for r in results) / len(results) for k in results[0]}
    return _blend(merged, text), " + ".join(used), notes


def _blend(scores: dict[str, float] | None, text: str) -> dict[str, float]:
    """Judged scores are averaged with measurable facts so a noisy model cannot swing the result alone."""
    bullets = ats.bullets_of(text)
    rules = {"action_verbs": min(1.0, ats.action_verb_ratio(bullets) / 0.7), "quantified": min(1.0, ats.quantified_ratio(bullets) / 0.5)}
    if scores is None:
        scores = {"has_summary": 1.0 if "summary" in ats.found_headings(text) else 0.0, "clarity": 0.5, "specific_tech": 0.5, **rules}
        return scores
    return {**scores, "action_verbs": (scores["action_verbs"] + rules["action_verbs"]) / 2,
            "quantified": (scores["quantified"] + rules["quantified"]) / 2}


def content_total(scores: dict[str, float]) -> dict[str, float]:
    """Weighted values for the content section: keeps the section's 0..1 average honest to CONTENT_WEIGHTS."""
    return {k: scores.get(k, 0.0) for k in CONTENT_WEIGHTS}


def content_fraction(scores: dict[str, float]) -> float:
    return sum(CONTENT_WEIGHTS[k] * scores.get(k, 0.0) for k in CONTENT_WEIGHTS)


async def extract_keywords(llm: LLM, jd_text: str, always_ask: bool = False) -> list[str]:
    from_vocab = ats.vocabulary_keywords(jd_text)
    if len(from_vocab) >= 6 and not always_ask:  # the built-in vocabulary already covers a typical IT job description, so skip the slow AI call
        return from_vocab[:30]
    try:
        d = await llm.chat_json("List the specific skills, tools, technologies and qualifications this job description asks for (at most 25). Short items only.",
                                jd_text[:6000], {"type": "object", "properties": {"keywords": STR_LIST}, "required": ["keywords"]}, temperature=0)
        extra = [k.strip() for k in d["keywords"] if 1 < len(k.strip()) <= 40]
    except Exception:  # noqa: BLE001
        extra = []
    out, seen = [], set()
    for k in [*extra, *from_vocab]:
        if k.lower() not in seen:
            seen.add(k.lower())
            out.append(k)
    return out[:30]


# ---------- suggestions ----------
FIXES = {
    "extractable": ("high", "Format", "Use a text-based file", "Your file has little readable text. Export the resume as a PDF from Word or Google Docs (File, Download, PDF) instead of scanning or screenshotting it."),
    "file_type": ("medium", "Format", "Use PDF or Word", "Save the resume as a .pdf or .docx file."),
    "pages": ("medium", "Format", "Trim to two pages", "Keep it to one page (under 5 years) or two pages. Remove old or unrelated roles and shorten bullets."),
    "tables": ("high", "Format", "Remove tables", "Many ATS read tables out of order. Rebuild the layout with plain paragraphs and simple bullet points."),
    "images": ("medium", "Format", "Remove images and graphics", "Photos, logos and skill bars are ignored by ATS. Replace skill bars with a plain list of skills."),
    "text_boxes": ("high", "Format", "Remove text boxes", "Text inside text boxes is often skipped. Move that text into the normal page body."),
    "columns": ("high", "Format", "Use a single column", "Two-column layouts can mix up sections when parsed. Use one column with clear headings."),
    "symbols": ("low", "Format", "Remove decorative symbols", "Icons and emoji can appear as strange characters. Use plain text such as 'Email:' and 'Phone:'."),
    "email": ("high", "Contact", "Add your email in the page body", "Put your email address at the top of the page body, not only in the header."),
    "phone": ("high", "Contact", "Add a phone number", "Add a phone number with country code, for example +91 98765 43210."),
    "profile_link": ("medium", "Contact", "Add your LinkedIn or GitHub link", "Add a link such as linkedin.com/in/your-name near your contact details."),
    "experience": ("high", "Structure", "Use a standard 'Experience' heading", "Name the section 'Work Experience' or 'Professional Experience' so the ATS can find it."),
    "education": ("medium", "Structure", "Add an 'Education' heading", "Add a section called 'Education' with your degree, college and year."),
    "skills": ("high", "Structure", "Add a 'Skills' section", "List your tools and technologies under a heading called 'Skills' or 'Technical Skills'."),
    "summary": ("low", "Structure", "Add a short summary", "Open with two or three lines: your role, years of experience, key technologies and one achievement."),
    "dates": ("low", "Structure", "Use one date format", "Pick one style, for example 'Jan 2022 – Mar 2024', and use it everywhere."),
    "length": ("medium", "Readability", "Adjust the length", "Aim for 250 to 900 words. Add detail to thin roles or cut older, less relevant content."),
    "bullets": ("medium", "Readability", "Use bullet points for experience", "Write each role as 3 to 6 bullets, one achievement per bullet."),
    "bullet_length": ("low", "Readability", "Keep bullets 8 to 28 words", "Shorten long bullets and expand one-word ones so each reads as a clear achievement."),
    "no_first_person": ("low", "Readability", "Remove 'I' and 'my'", "Start bullets with a verb instead of 'I' or 'my', for example 'Built...' instead of 'I built...'."),
    "buzzwords": ("low", "Readability", "Replace buzzwords with evidence", "Phrases like 'team player' say little. Show it: 'Led a team of 4 to ship X in 3 months'."),
}


def deterministic_suggestions(checks, kw: AtsKeywords, judged: dict[str, float] | None) -> list[AtsSuggestion]:
    out = []
    for ch in checks:
        if ch.credit < 1.0 and ch.id in FIXES:
            pr, cat, title, fix = FIXES[ch.id]
            out.append(AtsSuggestion(priority=pr, category=cat, title=title, fix=fix + (f" ({ch.detail})" if ch.detail else "")))
    if kw.provided and kw.missing:
        out.append(AtsSuggestion(priority="high", category="Keywords", title=f"Add {min(len(kw.missing), 8)} missing keywords",
                                 fix="The job description mentions: " + ", ".join(kw.missing[:12]) + ". Add the ones you truly have to your Skills section and to the bullets where you used them. Do not add skills you cannot discuss."))
    if judged:
        if judged.get("quantified", 1) < 0.5:
            out.append(AtsSuggestion(priority="high", category="Content", title="Add numbers to your achievements", fix="Aim for a number in at least half your bullets: users, requests per second, percent faster, hours saved, team size, cost."))
        if judged.get("action_verbs", 1) < 0.5:
            out.append(AtsSuggestion(priority="medium", category="Content", title="Start bullets with strong verbs", fix="Replace 'Responsible for...' with verbs such as Built, Led, Reduced, Migrated, Automated."))
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(out, key=lambda s: order[s.priority])


async def bullet_rewrites(llm: LLM, text: str, bullets: list[str] | None = None) -> list[AtsSuggestion]:
    bullets = bullets if bullets is not None else ats.bullets_of(text)
    weak = ats.weak_bullets(bullets, 5)
    if not weak:
        return []
    schema = {"type": "object", "properties": {"rewrites": {"type": "array", "items": {"type": "object", "properties": {
        "before": {"type": "string"}, "after": {"type": "string"}}, "required": ["before", "after"]}}}, "required": ["rewrites"]}
    try:
        d = await llm.chat_json(
            "Rewrite weak resume bullets to start with a strong action verb and show impact. Use British English. Keep the facts exactly as given: "
            "never invent numbers, tools or results. Where a number would help but is not given, put a placeholder like [add number]. 'before' must be copied exactly.",
            "\n".join(f"- {b}" for b in weak), schema, temperature=0.3)
    except Exception:  # noqa: BLE001
        return []
    low = text.lower()
    out = []
    for r in d["rewrites"][:5]:
        before = r["before"].strip().lstrip("-• ").strip()
        # the rewrite may only contain digits that already appear in the original bullet (no invented metrics)
        invented = set(re.findall(r"\d+", r["after"])) - set(re.findall(r"\d+", before))
        if before and before.lower() in low and r["after"].strip() and not invented:
            out.append(AtsSuggestion(priority="medium", category="Bullets", title="Make this bullet stronger", fix="Start with a verb and show the result.", before=before, after=r["after"].strip()))
    return out


async def analyze(llm: LLM, lev: LevClient, f: ResumeFacts, jd_text: str, use_lev: bool, rewrites: bool = False, use_ai: bool = True, online: bool = False, model_name: str = "Grok") -> AtsReport:
    checks = ats.run_checks(f)
    bullets = ats.bullets_of(f.text)
    kw = AtsKeywords()
    notes: list[str] = []
    if jd_text.strip() and f.extractable:
        kw = ats.match_keywords(f.text, await extract_keywords(llm, jd_text, online) if use_ai else ats.vocabulary_keywords(jd_text))
    elif not jd_text.strip():
        notes.append("Add a job description to include keyword matching in the score.")
    judged, judge, jnotes = (None, "deterministic", [])
    if f.extractable:
        judged, judge, jnotes = await judge_content(llm, lev, f.text, use_lev, use_ai, online, model_name)
    notes += jnotes
    sections = ats.score_sections(checks, f.extractable, None if judged is None else {"all": content_fraction(judged)}, kw)
    score = ats.total_score(sections, f.extractable)
    score, cap_notes = ats.apply_caps(score, checks)
    notes += cap_notes
    suggestions = deterministic_suggestions(checks, kw, judged)
    if rewrites and f.extractable and judge != "rules only":
        suggestions += await bullet_rewrites(llm, f.text, bullets)
    red = Redactor()
    red.clean(f.text)
    if red.summary():
        notes.append("Personal details were removed before any AI step (" + describe(red.summary()) + "). The AI never sees them.")
    return AtsReport(score=score, grade=ats.grade(score), sections=sections, checks=checks, keywords=kw, suggestions=suggestions, judge=judge,
                     notes=notes, words=len(f.text.split()), pages=f.pages, redactions=red.summary())
