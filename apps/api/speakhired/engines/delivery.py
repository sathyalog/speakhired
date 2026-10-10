import re

from ..schemas import DeliveryMetrics

FILLERS = ["um", "uh", "erm", "like", "you know", "basically", "actually", "i mean", "sort of", "kind of"]


def delivery_metrics(transcript: str, duration_s: float, word_times: list[tuple[float, float]] | None = None) -> DeliveryMetrics:
    words = re.findall(r"[A-Za-z0-9'+#.-]+", transcript)
    low = transcript.lower()
    fillers = {f: len(re.findall(rf"\b{re.escape(f)}\b", low)) for f in FILLERS}
    fillers = {k: v for k, v in fillers.items() if v}
    long_pauses = 0
    if word_times:
        long_pauses = sum(1 for (_, e), (s, _) in zip(word_times, word_times[1:]) if s - e > 1.5)
    wpm = round(len(words) / (duration_s / 60), 1) if duration_s > 0 else 0.0
    return DeliveryMetrics(words=len(words), wpm=wpm, fillers=fillers, long_pauses=long_pauses)
