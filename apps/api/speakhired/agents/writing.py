"""Clean Copy: AI suggestions on clarity and tone. Spelling and grammar are handled instantly in the browser (Harper)."""
from ..llm import LLM
from ..schemas import WriteIssue, WriteResult
from . import prompts as P

MAX_CHARS = 6000
CHUNK = 1200
CATEGORIES = ["clarity", "concise", "tone", "word choice", "structure"]


def chunks_of(text: str) -> list[tuple[int, int]]:
    """Paragraph-aligned (start, end) windows of about CHUNK characters."""
    spans, start, i = [], 0, 0
    n = len(text)
    while start < n:
        end = min(start + CHUNK, n)
        if end < n:
            cut = text.rfind("\n\n", start, end)
            if cut <= start:
                cut = max(text.rfind(". ", start, end), text.rfind("\n", start, end))
            end = cut + 1 if cut > start else end
        spans.append((start, end))
        start = end
    return spans


async def improve(llm: LLM, text: str, kind: str, tone: str, rewrite: bool = False) -> WriteResult:
    truncated = len(text) > MAX_CHARS
    text = text[:MAX_CHARS]
    kind_s, tone_s = P.WRITING_KINDS.get(kind, P.WRITING_KINDS["general"]), P.WRITING_TONES.get(tone, P.WRITING_TONES["professional"])
    schema = {"type": "object", "properties": {"issues": {"type": "array", "items": {"type": "object", "properties": {
        "original": {"type": "string"}, "replacement": {"type": "string"}, "category": {"type": "string", "enum": CATEGORIES},
        "message": {"type": "string"}}, "required": ["original", "replacement", "category", "message"]}}}, "required": ["issues"]}
    issues: list[WriteIssue] = []
    for start, end in chunks_of(text):
        piece = text[start:end]
        if len(piece.split()) < 6:
            continue
        try:
            d = await llm.chat_json(P.WRITING_SYSTEM.format(kind=kind_s, tone=tone_s), piece, schema, temperature=0.3)
        except Exception:  # noqa: BLE001 - one slow or failed chunk must not lose the others
            continue
        for it in d["issues"][:8]:
            orig, rep = it["original"].strip(), it["replacement"].strip()
            idx = text.find(orig, start, end) if orig else -1
            if idx < 0 or not rep or rep == orig:
                continue  # the quote must exist in the draft
            if any(idx < x.end and idx + len(orig) > x.start for x in issues):
                continue  # drop overlaps
            issues.append(WriteIssue(original=orig, replacement=rep, category=it["category"], message=it["message"][:160], start=idx, end=idx + len(orig)))
    issues.sort(key=lambda x: x.start)
    result = WriteResult(issues=issues, truncated=truncated)
    if rewrite:
        try:
            result.rewrite = await llm.chat_text(P.REWRITE_SYSTEM.format(kind=kind_s, tone=tone_s), text, temperature=0.4)
        except Exception:  # noqa: BLE001
            result.rewrite = None
    return result
