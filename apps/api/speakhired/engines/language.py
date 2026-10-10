"""Detects when a candidate uses a language other than English, so the app can ask for English only.

Three layers: Whisper's language ID on the audio, script detection (Devanagari, Telugu...), and a
word list for Indian languages written in English letters ("mujhe", "kya", "ledu").
"""
import json
import re
from functools import lru_cache
from pathlib import Path

from ..schemas import LangWord, LangReport

LANG_NAMES = {
    "en": "English", "hi": "Hindi", "te": "Telugu", "ta": "Tamil", "kn": "Kannada", "ml": "Malayalam", "mr": "Marathi",
    "bn": "Bengali", "gu": "Gujarati", "pa": "Punjabi", "ur": "Urdu", "or": "Odia", "ne": "Nepali", "sa": "Sanskrit",
}

# (start, end, language code) Unicode blocks; Devanagari is reported as Hindi (also used by Marathi and Nepali).
SCRIPTS = [
    (0x0900, 0x097F, "hi"), (0x0980, 0x09FF, "bn"), (0x0A00, 0x0A7F, "pa"), (0x0A80, 0x0AFF, "gu"), (0x0B00, 0x0B7F, "or"),
    (0x0B80, 0x0BFF, "ta"), (0x0C00, 0x0C7F, "te"), (0x0C80, 0x0CFF, "kn"), (0x0D00, 0x0D7F, "ml"), (0x0600, 0x06FF, "ur"),
]
# \w misses combining vowel marks, which would split Indian-script words into pieces, so those blocks are listed explicitly.
_TOKEN = re.compile(r"[\w\u0600-\u06FF\u0900-\u0DFF]+(?:['’][\w\u0900-\u0DFF]+)*", re.UNICODE)

NON_ENGLISH_RATIO = 0.4      # share of flagged words that makes an answer "mostly non-English"
AUDIO_MIN_PROB = 0.7         # Whisper must be this sure of another language...
AUDIO_MAX_EN_PROB = 0.3      # ...and think English is unlikely, to avoid mislabelling accented English


@lru_cache(maxsize=1)
def _lexicon() -> dict[str, dict[str, list[str]]]:
    raw = json.loads((Path(__file__).resolve().parent.parent / "data" / "indic_words.json").read_text(encoding="utf-8"))
    return {lang: {w.lower(): alts for w, alts in words.items()} for lang, words in raw.items() if not lang.startswith("_")}


def _script_lang(word: str) -> str | None:
    for ch in word:
        cp = ord(ch)
        for lo, hi, lang in SCRIPTS:
            if lo <= cp <= hi:
                return lang
    return None


def decide_audio_language(probs: dict[str, float]) -> dict:
    """Whisper language probabilities -> {code, prob, non_english, ambiguous}."""
    if not probs:
        return {"code": "en", "prob": 0.0, "non_english": False, "ambiguous": False}
    top = max(probs, key=probs.get)
    p_top, p_en = probs[top], probs.get("en", 0.0)
    if top == "en":
        return {"code": "en", "prob": p_top, "non_english": False, "ambiguous": False}
    if p_top >= AUDIO_MIN_PROB and p_en < AUDIO_MAX_EN_PROB:
        return {"code": top, "prob": p_top, "non_english": True, "ambiguous": False}
    return {"code": top, "prob": p_top, "non_english": False, "ambiguous": True}  # likely accented English: retry as English


def analyze_text(text: str) -> tuple[list[LangWord], int]:
    """Returns (flagged words, total word count)."""
    tokens = _TOKEN.findall(text)
    lex = _lexicon()
    flagged: list[LangWord] = []
    for tok in tokens:
        lang = _script_lang(tok)
        if lang:
            flagged.append(LangWord(word=tok, lang=lang, english=[]))
            continue
        low = tok.lower()
        for code, words in lex.items():
            if low in words:
                flagged.append(LangWord(word=tok, lang=code, english=words[low]))
                break
    return flagged, len(tokens)


def build_report(text: str, audio: dict | None = None) -> LangReport:
    words, total = analyze_text(text)
    ratio = len(words) / total if total else 0.0
    mostly = ratio >= NON_ENGLISH_RATIO and len(words) >= 2
    audio_non_en = bool(audio and audio.get("non_english"))
    if audio_non_en or mostly:
        status = "non_english"
    elif words:
        status = "mixed"
    else:
        status = "english"
    langs = [w.lang for w in words]
    code = audio["code"] if audio_non_en else (max(set(langs), key=langs.count) if langs else "en")
    return LangReport(status=status, language=code, language_name=LANG_NAMES.get(code, code.upper()),
                      confidence=float(audio["prob"]) if audio_non_en else round(ratio, 2), words=words, ratio=round(ratio, 2),
                      source="audio" if audio_non_en else "text")
