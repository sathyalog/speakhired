"""Optional LanguageTool (en-GB) grounding so the LLM only explains real grammar spans."""
from functools import lru_cache


@lru_cache(maxsize=1)
def _tool():
    try:
        import language_tool_python  # type: ignore
        return language_tool_python.LanguageTool("en-GB")
    except Exception:  # noqa: BLE001 - not installed or Java missing
        return None


def grammar_spans(text: str) -> list[dict]:
    tool = _tool()
    if tool is None:
        return []
    out = []
    for m in tool.check(text)[:12]:
        out.append({
            "original": text[m.offset : m.offset + m.errorLength],
            "suggestion": (m.replacements or [""])[0],
            "message": m.message,
        })
    return out
