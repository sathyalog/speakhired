import asyncio
import uuid
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from .agents import core, resume as resume_agent, writing
from .config import get_settings
from .engines import stt, tts, vocab
from .engines import github, daily, system_design
from .engines.srs import Card, combined_grade, review
from .store.progress import ProgressStore
from .agents import proof
from .engines.delivery import delivery_metrics
from .engines.language import build_report
from .engines.egress import EgressBlocked, EgressGateway, ExternalQuery, WebCheckQuery
from .ingest.documents import extract_text, inspect_resume, split_questions
from .ingest.jd import fetch_jd_text
from .llm import CooldownStore, LLMUnavailable, ModeStore, OllamaLLM, ProviderPool, RoutingLLM, build_online_providers, llm_errors, llm_switches
from .privacy import Redactor, describe
from .reasoning.lev import LevClient
from .schemas import CandidateProfile, DeliveryMetrics, Evaluation, JobProfile, LangAudio, Question, WebCheck
from .store.db import SessionStore

app = FastAPI(title="SpeakHired")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"], expose_headers=["X-LLM-Error", "X-LLM-Error-Message", "X-LLM-Switch"])

ollama = OllamaLLM()
grok = ProviderPool(build_online_providers(get_settings()), store=CooldownStore())  # Groq, Mistral, Google AI Studio, Grok, or a custom service; moves on when one runs out
mode_store = ModeStore()
llm = RoutingLLM(mode_store, ollama, grok)  # picks Ollama or the online providers by mode and strips personal details from every prompt
lev = LevClient()
store = SessionStore()
progress = ProgressStore()
egress = EgressGateway()


@app.on_event("startup")
async def preload_lev() -> None:
    if lev.in_process:
        asyncio.create_task(asyncio.to_thread(lev.try_preload))


def _ascii(text: str) -> str:
    return text.encode("ascii", "ignore").decode()


@app.middleware("http")
async def tell_browser_about_ai_problems(request, call_next):
    """If any AI step failed during a request (even one the app recovered from), say so in a header so the UI can show a notice."""
    bucket: list = []
    switches: list = []
    token = llm_errors.set(bucket)
    switch_token = llm_switches.set(switches)
    try:
        response = await call_next(request)
    finally:
        llm_errors.reset(token)
        llm_switches.reset(switch_token)
    if bucket:
        response.headers["X-LLM-Error"] = bucket[0][0]
        response.headers["X-LLM-Error-Message"] = _ascii(bucket[0][1])
    if switches:
        response.headers["X-LLM-Switch"] = _ascii(switches[-1])
    return response


@app.exception_handler(LLMUnavailable)
async def llm_unavailable(request, exc: LLMUnavailable):
    return JSONResponse({"detail": exc.message, "code": exc.code}, status_code=503)


class ModeIn(BaseModel):
    mode: str


def _setup() -> str:
    """The three setups people can be in: fully offline, offline with scoring on a server of your own, or online."""
    if mode_store.mode == "online":
        return "online"
    return "offline_hosted_scoring" if lev.location in ("network", "internet") else "fully_offline"


def _mode_info() -> dict:
    return {"mode": mode_store.mode, "setup": _setup(), "grok": {"configured": grok.configured, "model": grok.s.external_model, "provider": grok.provider, "providers": grok.status()},
            "lev": {"mode": lev.s.lev_mode, "remote": lev.is_remote if lev.enabled else False, "location": lev.location},
            "redaction": {"names": "header, labels, honorifics and people-words"}}


@app.get("/api/mode")
def get_mode():
    return _mode_info()


@app.post("/api/mode")
def set_mode(body: ModeIn):
    try:
        mode_store.set(body.mode)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _mode_info()


@app.get("/api/health")
async def health():
    info = _mode_info()
    # LEV's own health (ok, status) and where it runs (location) are both needed, so merge them rather than letting one replace the other
    info["lev"] = {**info["lev"], **await lev.health()}
    return {"ollama": await ollama.health(), "external_lookup": egress.enabled, **info}


@app.get("/api/voices")
def voices():
    return tts.VOICES


@app.post("/api/speech-text")
def speech_text(text: str = Form(...)):
    """The same wording the voice uses ("Chat G P T"), for the browser's own voice when the main voice is unavailable."""
    return {"text": vocab.prepare_speech(text[:1500])}


@app.post("/api/speak")
async def speak(text: str = Form(...), voice: str = Form(...), speed: float = Form(tts.DEFAULT_SPEED)):
    try:
        wav = await asyncio.to_thread(tts.synthesize, text, voice, speed)
    except stt.VoiceNotInstalled as e:
        raise HTTPException(501, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return Response(wav, media_type="audio/wav")


def _interview_terms(session_id: str) -> list[str]:
    """Technical words this interview is likely to contain: from the current question and the job's stack."""
    data = store.get(session_id) if session_id else None
    if not data or data["index"] >= len(data["questions"]):
        return []
    q = data["questions"][data["index"]]
    return vocab.context_terms(q["text"], *q.get("key_points", []), extra=[*data["job"].get("tech_stack", []), *data["candidate"].get("skills", [])])


@app.post("/api/transcribe")
async def transcribe(audio: UploadFile = File(...), session_id: str = Form(""), hint: str = Form("")):
    terms = _interview_terms(session_id) + [t for t in vocab.context_terms(hint) if t not in _interview_terms(session_id)] if hint else _interview_terms(session_id)
    try:
        result = await asyncio.to_thread(stt.transcribe, await audio.read(), terms)
    except stt.VoiceNotInstalled as e:
        raise HTTPException(501, str(e))
    heard = result["text"]
    result["text"], changes = vocab.correct_transcript(heard, terms)   # "chat gpt" -> ChatGPT, "post gress" -> PostgreSQL
    result["heard"] = heard
    result["corrections"] = [{"heard": a, "fixed": b} for a, b in changes]
    result["report"] = build_report(result["text"], result["language"]).model_dump()
    return result


class LangCheckIn(BaseModel):
    text: str
    audio_language: LangAudio | None = None


@app.post("/api/language/check")
def language_check(body: LangCheckIn):
    """Instant, offline check used while the candidate edits or types an answer."""
    return build_report(body.text, body.audio_language.model_dump() if body.audio_language else None)


@app.post("/api/sessions")
async def create_session(
    round_no: int = Form(...), voice: str = Form("bm_george"),
    jd_text: str = Form(""), jd_url: str = Form(""), external_consent: bool = Form(False),
    resume: UploadFile = File(...), questions_file: UploadFile | None = File(None), github_url: str = Form(""),
    interview_pattern: str = Form(""),
):
    if round_no not in (1, 2, 3, 4):
        raise HTTPException(400, "round_no must be 1-4")
    # Optional: the candidate's public GitHub repos, used for proof points. A bad or unreachable address never blocks the interview.
    # GitHub is contacted only in Online mode, so Offline mode never sends anything to GitHub.
    repos, github_note = [], ""
    if github_url.strip() and mode_store.mode != "online":
        github_note = "GitHub proof points are only used in Online mode. Switch to Online to include your repos."
    elif github_url.strip():
        try:
            repos = await github.fetch_repos(github.parse_profile(github_url))
        except github.GithubError as e:
            github_note = str(e)
    try:
        jd = jd_text.strip() or (await fetch_jd_text(jd_url) if jd_url else "")
        if not jd:
            raise ValueError("Provide a job description URL or paste the text.")
        resume_text = extract_text(resume.filename or "resume.pdf", await resume.read())
        custom = []
        if questions_file is not None and questions_file.filename:
            custom = split_questions(extract_text(questions_file.filename, await questions_file.read()))[:15]
    except ValueError as e:
        raise HTTPException(400, str(e))

    job, cand = await core.intake(llm, jd, resume_text)
    brief = None
    if external_consent and egress.enabled and job.company:
        try:
            brief = await egress.lookup(ExternalQuery(company_name=job.company, role_title=job.role, tech_tags=job.tech_stack[:10]), True)
        except (EgressBlocked, ValueError, Exception):  # noqa: BLE001 - external info is optional
            brief = None
    pattern = interview_pattern.strip()[: core.MAX_PATTERN_CHARS]  # optional: what the recruiter says the interview is
    questions = await core.generate_questions(llm, job, cand, round_no, custom=custom, pattern=pattern)
    questions = [await core.rubric_for_custom(llm, q) if q.kind == "custom" else q for q in questions]
    red = Redactor()
    red.clean(resume_text)
    data = {"job": job.model_dump(), "candidate": cand.model_dump(), "round": round_no, "voice": voice,
            "brief": brief, "questions": [q.model_dump() for q in questions], "index": 0, "results": [],
            "pii_terms": [], "resume_text_chars": len(resume_text), "repos": [r.__dict__ for r in repos], "pattern": pattern}
    sid = store.create(data)
    return {"id": sid, "job": job, "brief": brief, "total": len(questions), "question": questions[0], "redactions": red.summary(),
            "repos": [{"name": r.name, "url": r.url, "description": r.description, "language": r.language} for r in repos], "github_note": github_note,
            "pattern_used": bool(pattern)}


def _ledger(data: dict) -> str:
    return "; ".join(data["candidate"].get("claims", [])[:8])


def _check_query(question: str, hint: str, transcript: str, include_answer: bool) -> WebCheckQuery:
    answer = ""
    if include_answer:
        answer = transcript.strip()
        if hint.strip() and hint.strip().lower() not in answer.lower():
            answer = f"{answer}\nCandidate's notes: {hint.strip()}".strip()
    return WebCheckQuery(question=question, answer=answer)


async def _quick_web_check(data: dict, q: Question, transcript: str) -> WebCheck | None:
    """Web check is opt-in per session; any failure falls back to a local-only result."""
    if not data.get("web_check") or not egress.enabled:
        return None
    try:
        query = _check_query(q.text, q.hint, transcript, data.get("include_answer", False))
        return await egress.web_check(query, True, llm)
    except Exception:  # noqa: BLE001 - network, schema or consent problems must not break the session
        return None


class QuickQuestion(BaseModel):
    text: str
    hint: str = ""


class QuickIn(BaseModel):
    questions: list[QuickQuestion]
    voice: str = "bm_george"
    web_check: bool = False
    include_answer: bool = False


class PreviewIn(BaseModel):
    question: str
    answer: str = ""
    include_answer: bool = False


@app.post("/api/quick/preview")
async def quick_preview(body: PreviewIn):
    """Shows exactly what a web check would send. Makes no network call."""
    try:
        q = _check_query(body.question, "", body.answer, body.include_answer)
        return {"enabled": egress.enabled, "prompt": egress.build_check_prompt(q)}
    except (ValueError, EgressBlocked) as e:
        raise HTTPException(400, str(e))


@app.post("/api/quick/sessions")
async def create_quick(body: QuickIn):
    items = [(x.text.strip(), x.hint.strip()[:1500]) for x in body.questions if x.text.strip()][:3]
    if not items:
        raise HTTPException(400, "Add at least one question.")
    if any(len(t) > 400 for t, _ in items):
        raise HTTPException(400, "Each question must be 400 characters or fewer.")
    if body.voice not in tts.VOICE_IDS:
        raise HTTPException(400, "unknown voice")
    questions = []
    for text, hint in items:
        q = Question(id=uuid.uuid4().hex[:8], text=text, kind="custom", difficulty=2, hint=hint)
        questions.append(await core.rubric_for_custom(llm, q))
    data = {"kind": "quick", "job": JobProfile(role="Hot Seat").model_dump(), "candidate": CandidateProfile().model_dump(),
            "round": 0, "voice": body.voice, "web_check": body.web_check and egress.enabled,
            "include_answer": body.include_answer, "questions": [q.model_dump() for q in questions], "index": 0,
            "results": [], "pii_terms": []}
    sid = store.create(data)
    return {"id": sid, "job": data["job"], "total": len(questions), "question": questions[0], "web_check": data["web_check"]}


class AnswerIn(BaseModel):
    transcript: str
    duration: float = 0.0
    audio_language: LangAudio | None = None  # only sent while the text is still what Whisper heard


@app.post("/api/sessions/{sid}/answer")
async def answer(sid: str, body: AnswerIn):
    data = store.get(sid)
    if not data:
        raise HTTPException(404, "session not found")
    if data["index"] >= len(data["questions"]):
        raise HTTPException(409, "interview already finished")
    q = Question(**data["questions"][data["index"]])
    lang = build_report(body.transcript, body.audio_language.model_dump() if body.audio_language else None)
    if lang.status == "non_english":
        raise HTTPException(422, f"Please answer in English. We heard {lang.language_name}.")
    delivery = delivery_metrics(body.transcript, body.duration)
    if data.get("kind") == "quick":
        web = await _quick_web_check(data, q, body.transcript)
        if web and web.reference_points:  # web-verified key points sharpen the rubric LEV scores against
            q = q.model_copy(update={"key_points": list(dict.fromkeys(q.key_points + web.reference_points))[:8]})
        ev = await core.evaluate(llm, lev, q, body.transcript, delivery, "", data.get("pii_terms"))
        fb = await core.coach_fast(llm, q, body.transcript, ev, delivery, web, lang.words)
    else:
        ev = await core.evaluate(llm, lev, q, body.transcript, delivery, _ledger(data), data.get("pii_terms"))
        fb = await core.coach_fast(llm, q, body.transcript, ev, delivery, None, lang.words)
    data["results"].append({"question": q.text, "answer": body.transcript, "scores": ev.scores, "missed": ev.missed_points,
                            "evaluation": ev.model_dump(), "feedback": fb.model_dump(), "delivery": delivery.model_dump(), "language": lang.model_dump(),
                            "lang_words": [w.model_dump() for w in lang.words]})
    data["index"] += 1
    done = data["index"] >= len(data["questions"])
    store.save(sid, data)
    return {"evaluation": ev, "feedback": fb, "delivery": delivery, "language": lang, "done": done, "answer_index": data["index"] - 1, "polish_pending": True,
            "ack": await core.acknowledge(llm, ev, None),
            "next_question": None if done else data["questions"][data["index"]]}


@app.post("/api/sessions/{sid}/polish/{index}")
async def polish(sid: str, index: int):
    """Stronger phrasing and the complete answer to give for an answer already scored. Slow on small computers, so it comes separately."""
    data = store.get(sid)
    if not data or not 0 <= index < len(data["results"]):
        raise HTTPException(404, "answer not found")
    r = data["results"][index]
    q = Question(**data["questions"][index])
    if r["feedback"].get("proof_point") is None and r["feedback"].get("proof_checked") is None and data.get("repos"):
        repos = [github.RepoSummary(**x) for x in data["repos"]]
        pp = await proof.find_proof(llm, q.text, r["feedback"].get("better_version") or r["answer"], repos)
        r["feedback"]["proof_point"] = pp.model_dump() if pp else None
        r["feedback"]["proof_checked"] = True
    if r["feedback"].get("impressive"):                       # already done (for example the page was reloaded)
        store.save(sid, data)
        return {k: r["feedback"].get(k) for k in ("swaps", "impressive", "better_version", "proof_point")}
    from .schemas import LangWord
    result = await core.coach_polish(llm, q, r["answer"], Evaluation(**r["evaluation"]), DeliveryMetrics(**r["delivery"]),
                                     WebCheck(**r["feedback"]["web_check"]) if r["feedback"].get("web_check") else None, [LangWord(**w) for w in r.get("lang_words", [])])
    r["feedback"].update({k: (v.model_dump() if hasattr(v, "model_dump") else [x.model_dump() for x in v] if isinstance(v, list) else v) for k, v in result.items()})
    store.save(sid, data)
    return {k: r["feedback"].get(k) for k in ("swaps", "impressive", "better_version", "proof_point")}


@app.get("/api/sessions/{sid}/report")
async def get_report(sid: str):
    data = store.get(sid)
    if not data:
        raise HTTPException(404, "session not found")
    summary = await core.report(llm, JobProfile(**data["job"]), data["results"])
    dims = {}
    for r in data["results"]:
        for k, v in r["scores"].items():
            dims.setdefault(k, []).append(v)
    return {"summary": summary, "averages": {k: round(sum(v) / len(v), 1) for k, v in dims.items()}, "results": data["results"]}



# ---------- Clean Copy (AI writing suggestions) ----------
class ImproveIn(BaseModel):
    text: str
    kind: str = "general"
    tone: str = "professional"
    rewrite: bool = False


@app.post("/api/write/improve")
async def write_improve(body: ImproveIn):
    if not body.text.strip():
        raise HTTPException(400, "Paste some text first.")
    return await writing.improve(llm, body.text, body.kind, body.tone, body.rewrite)


# ---------- System design whiteboard ----------
class SystemDesignReviewIn(BaseModel):
    question_id: str
    elements: list[dict] = []  # the Excalidraw scene, as exported by the browser


@app.get("/api/system-design/questions")
def system_design_questions(track: str | None = None):
    if track is not None and track not in system_design.TRACKS:
        raise HTTPException(400, "Track must be 'regular' or 'ai'.")
    return [system_design.public_question(q) for q in system_design.list_questions(track)]


@app.post("/api/system-design/review")
async def system_design_review(body: SystemDesignReviewIn):
    question = system_design.get_question(body.question_id)
    if not question:
        raise HTTPException(404, "Question not found.")
    if not system_design.has_components(body.elements):
        raise HTTPException(400, "Draw at least one component first.")
    return await system_design.review(llm, question, body.elements, lev)


# ---------- Resume Radar (ATS readiness) ----------
MAX_RESUME_BYTES = 5 * 1024 * 1024


@app.post("/api/ats/analyze")
async def ats_analyze(resume: UploadFile = File(...), jd_text: str = Form(""), jd_url: str = Form(""), use_lev: bool = Form(False), use_ai: bool = Form(True)):
    data = await resume.read()
    if len(data) > MAX_RESUME_BYTES:
        raise HTTPException(413, "That file is larger than 5 MB.")
    try:
        facts = await asyncio.to_thread(inspect_resume, resume.filename or "resume.pdf", data)
        jd = jd_text.strip() or (await fetch_jd_text(jd_url) if jd_url.strip() else "")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception:  # noqa: BLE001 - unreadable or corrupt file
        raise HTTPException(400, "We couldn't read that file. Try exporting it as a PDF or Word document again.")
    # Online mode means the user chose to use their remote services, so LEV on their own server is allowed too.
    return await resume_agent.analyze(llm, lev, facts, jd, use_lev or mode_store.mode == "online", use_ai=use_ai, online=mode_store.mode == "online", model_name=grok.provider)


@app.post("/api/ats/rewrites")
async def ats_rewrites(resume: UploadFile = File(...)):
    """Slow AI step, requested separately so the score appears first: stronger wording for the weakest bullets."""
    data = await resume.read()
    if len(data) > MAX_RESUME_BYTES:
        raise HTTPException(413, "That file is larger than 5 MB.")
    try:
        facts = await asyncio.to_thread(inspect_resume, resume.filename or "resume.pdf", data)
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "We couldn't read that file.")
    return {"suggestions": await resume_agent.bullet_rewrites(llm, facts.text) if facts.extractable else []}



# ---------- Daily English for IT ----------
class DailyAttemptIn(BaseModel):
    item_id: str
    step: str                      # "repeat" or "use"
    transcript: str = ""
    audio_language: LangAudio | None = None


def _level() -> str:
    level = progress.get_setting("daily_level", daily.DEFAULT_LEVEL)
    return level if level in daily.LEVEL_IDS else daily.DEFAULT_LEVEL


class LevelIn(BaseModel):
    level: str


@app.get("/api/daily/levels")
def daily_levels():
    return {"current": _level(), "levels": daily.level_summary(progress.cards())}


@app.post("/api/daily/level")
def set_daily_level(body: LevelIn):
    if body.level not in daily.LEVEL_IDS:
        raise HTTPException(400, "level must be foundation, professional or expert")
    progress.set_setting("daily_level", body.level)
    return daily_levels()


@app.get("/api/daily/today")
def daily_today():
    today = date.today()
    level = _level()
    cards = progress.cards()
    picked = daily.choose_today(cards, today, level)
    return {"items": picked, "level": level, "progress": daily.progress_summary(cards, today, level), "streak": progress.streak(today),
            "done_today": progress.done_today(today)}


@app.post("/api/daily/attempt")
def daily_attempt(body: DailyAttemptIn):
    it = daily.item(body.item_id)
    if not it:
        raise HTTPException(404, "item not found")
    if body.step not in ("repeat", "use"):
        raise HTTPException(400, "step must be 'repeat' or 'use'")
    lang = build_report(body.transcript, body.audio_language.model_dump() if body.audio_language else None)
    if lang.status == "non_english":
        raise HTTPException(422, f"Please answer in English. We heard {lang.language_name}.")
    today = date.today()
    if body.step == "repeat":
        grade, feedback = daily.score_repeat(it, body.transcript)
        progress.record(today, it["id"], "repeat", grade)
        return {"grade": grade, "feedback": feedback, "next": "use", "item": it}
    grade, feedback, better = daily.score_use(it, body.transcript)
    progress.record(today, it["id"], "use", grade)
    steps = progress.grades_today(today, it["id"])
    item_grade = combined_grade(*[g for k, g in steps.items()])
    card = progress.cards().get(it["id"]) or Card(item_id=it["id"])
    # the schedule moves once per day, the first time the 'use' step is finished
    uses_today = progress.db.execute("SELECT COUNT(*) FROM daily_attempts WHERE day=? AND item_id=? AND step='use'",
                                     (today.isoformat(), it["id"])).fetchone()[0]
    if uses_today == 1:
        card = review(card, item_grade, today)
        progress.save_card(card)
    return {"grade": grade, "feedback": feedback, "better": better, "item_grade": item_grade, "item": it,
            "due": card.due, "next_review_days": card.interval}


@app.get("/api/daily/progress")
def daily_progress():
    today = date.today()
    return {**daily.progress_summary(progress.cards(), today, _level()), "streak": progress.streak(today)}
