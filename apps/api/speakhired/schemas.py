from typing import Literal
from pydantic import BaseModel, Field

RoundNo = Literal[1, 2, 3, 4]


class JobProfile(BaseModel):
    company: str = ""
    role: str = ""
    seniority: str = ""
    tech_stack: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    must_have: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)


class CandidateProfile(BaseModel):
    skills: list[str] = Field(default_factory=list)
    years_experience: float | None = None
    projects: list[str] = Field(default_factory=list)
    claims: list[str] = Field(default_factory=list)


class Question(BaseModel):
    id: str
    text: str
    kind: Literal["general", "role", "behavioural", "technical", "design", "custom"] = "technical"
    topic: str = ""
    difficulty: int = 1
    key_points: list[str] = Field(default_factory=list)
    follow_up: str = ""
    hint: str = ""  # optional rough idea typed by the candidate (Hot Seat)


class Correction(BaseModel):
    original: str
    fix: str
    reason: str


class Evaluation(BaseModel):
    scores: dict[str, int]  # relevance, correctness, depth, structure, specificity: 1-5
    evidence: dict[str, str] = Field(default_factory=dict)
    covered_points: list[str] = Field(default_factory=list)
    missed_points: list[str] = Field(default_factory=list)
    answered: bool = True
    next_action: Literal["follow_up", "next_question", "clarify", "easier", "harder"] = "next_question"
    confidence: float = 0.0
    judge: str = "llm"


class Swap(BaseModel):
    instead_of: str
    say: str
    why: str = ""


class FactFlag(BaseModel):
    claim: str
    status: Literal["supported", "unclear", "wrong"] = "unclear"
    note: str = ""


class Source(BaseModel):
    title: str = ""
    url: str


class WebCheck(BaseModel):
    verdict: Literal["sufficient", "partial", "insufficient"] = "partial"
    reference_points: list[str] = Field(default_factory=list)
    missing_points: list[str] = Field(default_factory=list)
    fact_flags: list[FactFlag] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    verified: bool = True
    answer_included: bool = False


class ImpressiveAnswer(BaseModel):
    answer_first: str = ""
    example: str = ""
    trade_off: str = ""
    close: str = ""


class Feedback(BaseModel):
    swaps: list[Swap] = Field(default_factory=list)
    impressive: ImpressiveAnswer | None = None
    web_check: WebCheck | None = None
    corrections: list[Correction] = Field(default_factory=list)
    corrected_answer: str = ""   # the candidate's own answer with the grammar fixes applied
    better_version: str = ""
    missing_outline: list[str] = Field(default_factory=list)
    vocabulary_tips: list[str] = Field(default_factory=list)
    spoken_summary: str = ""


class LangWord(BaseModel):
    word: str
    lang: str
    english: list[str] = Field(default_factory=list)


class LangReport(BaseModel):
    status: Literal["english", "mixed", "non_english"] = "english"
    language: str = "en"
    language_name: str = "English"
    confidence: float = 0.0
    words: list[LangWord] = Field(default_factory=list)
    ratio: float = 0.0
    source: Literal["audio", "text"] = "text"


class LangAudio(BaseModel):
    code: str = "en"
    prob: float = 0.0
    non_english: bool = False


class DeliveryMetrics(BaseModel):
    words: int = 0
    wpm: float = 0.0
    fillers: dict[str, int] = Field(default_factory=dict)
    long_pauses: int = 0


# ---------- Resume Radar (ATS readiness) ----------
class AtsCheck(BaseModel):
    id: str
    section: str
    label: str
    passed: bool
    credit: float = 0.0  # 0..1 share of the check's weight earned
    detail: str = ""


class AtsSection(BaseModel):
    id: str
    name: str
    score: float
    max: float


class AtsKeywords(BaseModel):
    provided: bool = False
    matched: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


class AtsSuggestion(BaseModel):
    priority: Literal["high", "medium", "low"]
    category: str
    title: str
    fix: str
    before: str = ""
    after: str = ""


class AtsReport(BaseModel):
    score: int
    grade: str
    sections: list[AtsSection]
    checks: list[AtsCheck]
    keywords: AtsKeywords
    suggestions: list[AtsSuggestion]
    judge: str = "deterministic"
    notes: list[str] = Field(default_factory=list)
    words: int = 0
    pages: int = 1
    redactions: dict[str, int] = Field(default_factory=dict)


# ---------- Clean Copy (AI writing suggestions) ----------
class WriteIssue(BaseModel):
    original: str
    replacement: str
    category: Literal["clarity", "concise", "tone", "word choice", "structure"] = "clarity"
    message: str = ""
    start: int = 0
    end: int = 0


class WriteResult(BaseModel):
    issues: list[WriteIssue] = Field(default_factory=list)
    rewrite: str | None = None
    truncated: bool = False


class ProofPoint(BaseModel):
    repo: str
    url: str
    claim: str = ""
    evidence: str = ""
    summary: str = ""
