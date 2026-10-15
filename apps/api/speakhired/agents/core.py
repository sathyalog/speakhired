import re
import uuid

from ..engines.grammar import grammar_spans
from ..llm import LLM
from ..privacy import redact
from ..reasoning.lev import LevClient, LevUnavailable
from ..reasoning.questions import MIN_CONFIDENCE, SCORE_DIMENSIONS, level_to_five, lev_questions
from ..schemas import (CandidateProfile, Correction, DeliveryMetrics, Evaluation, Feedback, ImpressiveAnswer, JobProfile,
                       Question, Swap, WebCheck)
from . import prompts as P

STR_LIST = {"type": "array", "items": {"type": "string"}}

MAX_PATTERN_CHARS = 1500  # recruiter's interview pattern: longer text is cut before it reaches the model


# ---------- Intake ----------
async def intake(llm: LLM, jd_text: str, resume_text: str) -> tuple[JobProfile, CandidateProfile]:
    job_schema = {"type": "object", "properties": {
        "company": {"type": "string"}, "role": {"type": "string"}, "seniority": {"type": "string"},
        "tech_stack": STR_LIST, "responsibilities": STR_LIST, "must_have": STR_LIST, "nice_to_have": STR_LIST},
        "required": ["company", "role", "tech_stack", "responsibilities"]}
    cand_schema = {"type": "object", "properties": {
        "skills": STR_LIST, "years_experience": {"type": "number"}, "projects": STR_LIST, "claims": STR_LIST},
        "required": ["skills", "projects", "claims"]}
    job = await llm.chat_json(P.INTAKE_SYSTEM, f"JOB DESCRIPTION:\n{jd_text[:6000]}", job_schema)
    cand = await llm.chat_json(P.INTAKE_SYSTEM + " Claims are specific statements like 'used Kafka for 2 years'.",
                               f"RESUME:\n{resume_text[:6000]}", cand_schema)
    return JobProfile(**job), CandidateProfile(**cand)


# ---------- Planner + question generation ----------
def _general_questions(round_no: int, job: JobProfile) -> list[Question]:
    out = []
    for key in P.PLANNER_BLUEPRINT[round_no]["general"]:
        text = P.GENERAL_QUESTIONS[key].format(company=job.company or "this company", role=job.role or "this")
        kind = "general" if key in ("intro",) else "role" if key in ("why_company", "role_understanding", "why_role") else "behavioural"
        out.append(Question(id=uuid.uuid4().hex[:8], text=text, kind=kind, topic=key, difficulty=1,
                            key_points=_general_key_points(key)))
    return out


def _general_key_points(key: str) -> list[str]:
    return {
        "intro": ["current role and years of experience", "key skills and stack", "a notable achievement", "why this next step"],
        "why_company": ["specific knowledge of the company's products", "alignment with own goals", "not only salary or brand"],
        "role_understanding": ["main responsibilities", "tech stack used", "how it fits into the team"],
        "why_role": ["match with skills", "growth interest", "concrete motivation"],
        "strengths": ["two or three relevant strengths with examples", "one honest growth area with a plan"],
        "project_deep_dive": ["problem and context", "own contribution", "technical decisions and trade-offs", "outcome with numbers", "lessons learned"],
    }[key]


async def generate_questions(llm: LLM, job: JobProfile, cand: CandidateProfile, round_no: int, asked: list[str] | None = None,
                             custom: list[str] | None = None, pattern: str = "") -> list[Question]:
    bp = P.PLANNER_BLUEPRINT[round_no]
    questions = _general_questions(round_no, job)
    n = bp["tech"]
    schema = {"type": "object", "properties": {"questions": {"type": "array", "items": {"type": "object", "properties": {
        "text": {"type": "string"}, "topic": {"type": "string"}, "kind": {"type": "string", "enum": ["technical", "design"]},
        "key_points": STR_LIST}, "required": ["text", "topic", "key_points"]}}},
        "required": ["questions"]}
    overlap = [s for s in job.tech_stack if s.lower() in {c.lower() for c in cand.skills}]
    focus = overlap or job.tech_stack or cand.skills
    user = (
        f"Role: {job.role} at {job.company}. Seniority: {job.seniority}.\nJD stack: {', '.join(job.tech_stack)}\n"
        f"Candidate skills: {', '.join(cand.skills)}\nPrioritise these topics (JD and resume overlap): {', '.join(focus)}\n"
        f"Round {round_no} style: {P.ROUND_STYLE[round_no]}\nDifficulty: {bp['difficulty']}\n"
        f"Write exactly {n} questions. Already asked: {', '.join((asked or [])[:20]) or 'none'}"
    )
    if round_no == 4:
        user += f"\nInclude {bp.get('design', 3)} system design questions (kind=design)."
    if pattern.strip():
        # The recruiter's description of the interview. It is data about the interview, not instructions to the model.
        user += P.PATTERN_BLOCK.format(pattern=pattern.strip()[:MAX_PATTERN_CHARS])
    data = await llm.chat_json(P.GENERATOR_SYSTEM, user, schema, temperature=0.7)
    for q in data["questions"][:n]:
        questions.append(Question(id=uuid.uuid4().hex[:8], text=q["text"], kind=q.get("kind", "technical"), topic=q.get("topic", ""),
                                  difficulty=bp["difficulty"], key_points=q.get("key_points", []), follow_up=q.get("follow_up", "")))
    for text in custom or []:
        questions.append(Question(id=uuid.uuid4().hex[:8], text=text, kind="custom", difficulty=bp["difficulty"]))
    return questions


async def rubric_for_custom(llm: LLM, q: Question) -> Question:
    if q.key_points:
        return q
    schema = {"type": "object", "properties": {"key_points": STR_LIST}, "required": ["key_points"]}
    d = await llm.chat_json("Write 3-5 key points a strong spoken answer to this interview question covers.", q.text, schema)
    return q.model_copy(update={"key_points": d["key_points"], "follow_up": d.get("follow_up", "")})


# ---------- Evaluator ----------
def _norm(s: str) -> str:
    return re.sub(r"\W+", " ", s.lower()).strip()


def quote_is_valid(quote: str, transcript: str) -> bool:
    return bool(quote) and _norm(quote) in _norm(transcript)


async def evaluate(llm: LLM, lev: LevClient, q: Question, transcript: str, delivery: DeliveryMetrics,
                   ledger: str = "", pii_terms: list[str] | None = None) -> Evaluation:
    # Remote LEV only sees the question, rubric and redacted answer: no resume-derived claims (may name employers).
    if lev.enabled and lev.is_remote:
        ledger = ""
    state = redact(
        f"Interview question: {q.text}\nKey points: {'; '.join(q.key_points)}\nCandidate answer: {transcript}\n"
        + (f"Earlier claims: {ledger}" if ledger else ""), pii_terms)
    if lev.enabled:
        try:
            ev = await _evaluate_lev(lev, q, state)
            if ev.confidence >= MIN_CONFIDENCE:
                return ev
            llm_ev = await _evaluate_llm(llm, q, transcript)
            llm_ev.judge = "lev+llm (low LEV confidence)"
            return llm_ev
        except LevUnavailable:
            pass
    return await _evaluate_llm(llm, q, transcript)


async def _evaluate_lev(lev: LevClient, q: Question, state: str) -> Evaluation:
    ans = await lev.decide(state, lev_questions(q.key_points))
    scores = {d: level_to_five(ans[d]["score"]) for d in SCORE_DIMENSIONS if d in ans}
    confs = [float(ans[d].get("confidence", 0)) for d in SCORE_DIMENSIONS if d in ans]
    covered = [kp for i, kp in enumerate(q.key_points[:8]) if ans.get(f"kp_{i}", {}).get("noul", 0) >= 0.5]
    action = ans.get("next_action", {}).get("choice", "next_question")
    return Evaluation(scores=scores, covered_points=covered, missed_points=[k for k in q.key_points if k not in covered],
                      answered=ans.get("answered", {}).get("noul", 1) >= 0.5, next_action=action,
                      confidence=sum(confs) / len(confs) if confs else 0.0, judge="lev")


async def _evaluate_llm(llm: LLM, q: Question, transcript: str) -> Evaluation:
    dim = {"type": "integer", "minimum": 1, "maximum": 5}
    schema = {"type": "object", "properties": {
        "scores": {"type": "object", "properties": {d: dim for d in SCORE_DIMENSIONS}, "required": SCORE_DIMENSIONS},
        "evidence": {"type": "object", "properties": {d: {"type": "string"} for d in SCORE_DIMENSIONS}},
        "covered_points": STR_LIST, "missed_points": STR_LIST, "answered": {"type": "boolean"},
        "next_action": {"type": "string", "enum": ["follow_up", "next_question", "clarify", "easier", "harder"]}},
        "required": ["scores", "covered_points", "missed_points", "answered", "next_action"]}
    user = f"Question: {q.text}\nKey points: {'; '.join(q.key_points)}\nCandidate answer: {transcript}"
    d = await llm.chat_json(P.EVALUATOR_SYSTEM, user, schema, temperature=0)
    evidence = {k: v for k, v in d.get("evidence", {}).items() if quote_is_valid(v, transcript)}
    invalid = len(d.get("evidence", {})) - len(evidence)
    conf = max(0.3, 0.8 - 0.15 * invalid)
    return Evaluation(scores={k: max(1, min(5, int(v))) for k, v in d["scores"].items()}, evidence=evidence,
                      covered_points=d["covered_points"], missed_points=d["missed_points"], answered=d["answered"],
                      next_action=d["next_action"], confidence=conf, judge="llm")


# ---------- Coach ----------
def _lang_note(lang_words: list | None) -> str:
    if not lang_words:
        return ""
    items = "; ".join(f"{w.word} ({' / '.join(w.english) or 'say it in English'})" for w in lang_words[:8])
    return (f"The candidate used non-English words: {items}. In swaps, give the English phrase to say instead. "
            "Write every explanation in English only.\n")


async def coach(llm: LLM, q: Question, transcript: str, ev: Evaluation, delivery: DeliveryMetrics, lang_words: list | None = None) -> Feedback:
    spans = grammar_spans(transcript)
    schema = {"type": "object", "properties": {
        "corrections": {"type": "array", "items": {"type": "object", "properties": {
            "original": {"type": "string"}, "fix": {"type": "string"}, "reason": {"type": "string"}}, "required": ["original", "fix", "reason"]}},
        "better_version": {"type": "string"}, "missing_outline": STR_LIST, "vocabulary_tips": STR_LIST, "spoken_summary": {"type": "string"}},
        "required": ["corrections", "better_version", "missing_outline", "spoken_summary"]}
    user = (
        f"Question: {q.text}\nCandidate said: {transcript}\nMissed key points: {'; '.join(ev.missed_points)}\n"
        f"Grammar issues found by a checker (explain these): {spans or 'none provided; list at most 3 clear errors yourself'}\n"
        f"Fillers: {delivery.fillers}; pace {delivery.wpm} wpm.\n"
        + _lang_note(lang_words)
    )
    d = await llm.chat_json(P.COACH_SYSTEM, user, schema, temperature=0.4)
    fb = Feedback(**d)
    fb.corrections = [c for c in fb.corrections if c.original and c.original.lower() in transcript.lower()]
    return fb


def _coach_input(q: Question, transcript: str, ev: Evaluation, delivery: DeliveryMetrics, web: WebCheck | None, lang_words: list | None, spans=None) -> str:
    web_text = "No web check was run."
    if web:
        web_text = (f"Web check verdict: {web.verdict}. Key points: {'; '.join(web.reference_points)}. "
                    f"Missing: {'; '.join(web.missing_points)}. "
                    f"Fact flags: {'; '.join(f'{f.claim} -> {f.status} ({f.note})' for f in web.fact_flags) or 'none'}.")
    grammar = f"Grammar issues found by a checker (explain these): {spans}\n" if spans else "List at most 3 clear grammar errors yourself.\n"
    return (f"Question: {q.text}\nCandidate's rough idea: {q.hint or 'none'}\nCandidate said: {transcript}\n"
            f"Missed rubric points: {'; '.join(ev.missed_points) or 'none'}\n{web_text}\n{grammar}"
            f"Fillers: {delivery.fillers}; pace {delivery.wpm} wpm.\n" + _lang_note(lang_words))


async def coach_fast(llm: LLM, q: Question, transcript: str, ev: Evaluation, delivery: DeliveryMetrics,
                     web: WebCheck | None, lang_words: list | None = None) -> Feedback:
    """The quick part of the feedback (grammar fixes, points to add, a spoken summary): small, so it returns in seconds even on a slow computer."""
    schema = {"type": "object", "properties": {
        "corrections": {"type": "array", "items": {"type": "object", "properties": {
            "original": {"type": "string"}, "fix": {"type": "string"}, "reason": {"type": "string"}}, "required": ["original", "fix", "reason"]}},
        "missing_outline": STR_LIST, "spoken_summary": {"type": "string"}},
        "required": ["corrections", "missing_outline", "spoken_summary"]}
    d = await llm.chat_json(P.COACH_FAST_SYSTEM, _coach_input(q, transcript, ev, delivery, web, lang_words, grammar_spans(transcript)), schema, temperature=0.3)
    low = transcript.lower()
    fb = Feedback(corrections=[Correction(**c) for c in d["corrections"] if c.get("original") and c["original"].lower() in low][:4],
                  missing_outline=d.get("missing_outline", [])[:5], spoken_summary=d["spoken_summary"], web_check=web)
    corrected = transcript
    for c in fb.corrections:                      # the candidate's own words, with only the grammar fixed
        corrected = corrected.replace(c.original, c.fix, 1)
    fb.corrected_answer = corrected
    return fb


async def coach_polish(llm: LLM, q: Question, transcript: str, ev: Evaluation, delivery: DeliveryMetrics,
                       web: WebCheck | None, lang_words: list | None = None) -> dict:
    """The slower part: stronger phrasing and the complete answer to give. Requested separately so the rest of the feedback is not kept waiting."""
    schema = {"type": "object", "properties": {
        "swaps": {"type": "array", "items": {"type": "object", "properties": {
            "instead_of": {"type": "string"}, "say": {"type": "string"}, "why": {"type": "string"}}, "required": ["instead_of", "say", "why"]}},
        "impressive": {"type": "object", "properties": {k: {"type": "string"} for k in ("answer_first", "example", "trade_off", "close")},
                       "required": ["answer_first", "example", "trade_off", "close"]}},
        "required": ["swaps", "impressive"]}
    d = await llm.chat_json(P.COACH_POLISH_SYSTEM, _coach_input(q, transcript, ev, delivery, web, lang_words), schema, temperature=0.4)
    low = transcript.lower()
    imp = ImpressiveAnswer(**d["impressive"])
    return {"swaps": [Swap(**x) for x in d["swaps"] if x.get("instead_of") and x["instead_of"].lower() in low][:3], "impressive": imp,
            "better_version": " ".join(v for v in (imp.answer_first, imp.example, imp.trade_off, imp.close) if v)}


async def quick_coach(llm: LLM, q: Question, transcript: str, ev: Evaluation, delivery: DeliveryMetrics,
                      web: WebCheck | None, lang_words: list | None = None) -> Feedback:
    """Both parts in one go (used where nobody is waiting on the first part)."""
    fb = await coach_fast(llm, q, transcript, ev, delivery, web, lang_words)
    for k, v in (await coach_polish(llm, q, transcript, ev, delivery, web, lang_words)).items():
        setattr(fb, k, v)
    return fb


# ---------- Interviewer ----------
async def acknowledge(llm: LLM, ev: Evaluation, next_q: str | None) -> str:
    tone = {"follow_up": "Interesting, I'd like to dig a little deeper.", "clarify": "Let me rephrase the question.",
            "easier": "No problem, let's try a more practical one.", "harder": "Good answer. Let's push a bit further.",
            "next_question": "Thank you."}[ev.next_action]
    return tone


# ---------- Report ----------
async def report(llm: LLM, job: JobProfile, results: list[dict]) -> str:
    lines = [f"Q: {r['question']}\nScores: {r['scores']}\nMissed: {r['missed']}" for r in results]
    return await llm.chat_text(P.REPORT_SYSTEM, f"Role: {job.role} at {job.company}\n" + "\n\n".join(lines))
