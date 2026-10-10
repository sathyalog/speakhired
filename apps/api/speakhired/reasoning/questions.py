"""Typed decision questions. Every judgement in the app is phrased as one of these."""

SCORE_DIMENSIONS = ["relevance", "correctness", "depth", "structure", "specificity"]

# LEV score questions take an ordered LIST of level descriptions; level i is criteria[i], so answers run from 0 to 4.
LEVELS = ["very poor", "weak", "acceptable", "good", "excellent"]


# LEV confidence is the concentration of its answer (0 = undecided, 1 = certain). Spreading over 5 levels, 0.1 to 0.3 is normal.
MIN_CONFIDENCE = 0.1


def level_to_unit(score: float) -> float:
    """LEV score (expected level, 0..4) -> 0..1."""
    return max(0.0, min(1.0, float(score) / (len(LEVELS) - 1)))


def level_to_five(score: float) -> int:
    """LEV score (expected level, 0..4) -> the 1..5 scale shown to people."""
    return max(1, min(5, round(float(score)) + 1))

DIMENSION_CRITERIA = {
    "relevance": "Does the answer address what the interviewer asked?",
    "correctness": "Is the technical content accurate with respect to the key points?",
    "depth": "Does it go beyond definitions into how/why/trade-offs?",
    "structure": "Is it organised (answer first, then reasoning, then example)?",
    "specificity": "Does it include concrete examples, numbers or tools?",
}


def lev_questions(key_points: list[str]) -> dict:
    qs: dict = {
        "answered": {"type": "noul", "instructions": "Did the candidate actually answer the question asked?"},
        "next_action": {
            "type": "choice",
            "instructions": "What should the interviewer do next?",
            "criteria": {
                "follow_up": "Answer was shallow or interesting; probe deeper",
                "next_question": "Answer was adequate; move on",
                "clarify": "Answer was off-topic or unclear; restate the question",
                "easier": "Candidate is struggling; ask something easier",
                "harder": "Candidate answered very well; ask something harder",
            },
        },
    }
    for dim, crit in DIMENSION_CRITERIA.items():
        qs[dim] = {"type": "score", "instructions": crit, "criteria": LEVELS}
    for i, kp in enumerate(key_points[:8]):
        qs[f"kp_{i}"] = {"type": "noul", "instructions": f"Does the answer cover this key point: {kp}"}
    return qs


def resume_questions() -> dict:
    """Typed LEV questions about resume content quality (scores are 1 to 5)."""
    legend = LEVELS
    return {
        "has_summary": {"type": "noul", "instructions": "Does the resume open with a short professional summary or profile?"},
        "action_verbs": {"type": "score", "instructions": "Do the experience bullets start with strong action verbs (led, built, reduced) rather than duties ('responsible for')?", "criteria": legend},
        "quantified": {"type": "score", "instructions": "Do the bullets show measurable impact with numbers, percentages or scale?", "criteria": legend},
        "clarity": {"type": "score", "instructions": "Is the writing clear, concise and free of filler, buzzwords and vague claims?", "criteria": legend},
        "specific_tech": {"type": "score", "instructions": "Does it name concrete technologies, tools and methods in context, not only in a skills list?", "criteria": legend},
    }
