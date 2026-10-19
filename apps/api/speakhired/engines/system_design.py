"""System design whiteboard: turn an Excalidraw scene into a small graph, check each expected component,
then ask a judge (LEV, or the LLM as fallback) whether the drawn boxes really play that role, and ask the LLM for the rest of the review.

A keyword in a label is not enough for credit. A component counts only when a box with that name exists, is connected
to the design, does not list several components in one label, and the judge agrees that it does the job."""
import json
import re
from pathlib import Path
from typing import Any

from ..llm import LLM
from ..privacy import Redactor
from ..reasoning.lev import LevClient, LevUnavailable

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
MAX_ELEMENTS = 400
SHAPES = {"rectangle", "ellipse", "diamond"}
# Weights add up to 100. Components come from the judged checks; the LLM scores the other four dimensions.
WEIGHTS = {"requirements": 25, "components": 25, "connections": 20, "correctness": 20, "tradeoffs": 10}
MAX_LIST = 8
STUFFED_COMPONENTS = 3  # one label that matches this many expected components is a keyword list, not a component
STUFFED_WORDS = 12

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "scores": {"type": "object", "properties": {d: {"type": "number"} for d in ("requirements", "connections", "correctness", "tradeoffs")},
                   "required": ["requirements", "connections", "correctness", "tradeoffs"]},
        "missing_requirements": {"type": "array", "items": {"type": "object", "properties": {
            "requirement": {"type": "string"}, "why": {"type": "string"}}, "required": ["requirement", "why"]}},
        "misleading": {"type": "array", "items": {"type": "object", "properties": {
            "statement": {"type": "string"}, "why": {"type": "string"}}, "required": ["statement", "why"]}},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    },
    "required": ["scores", "missing_requirements", "misleading", "strengths", "summary"],
}

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"verdicts": {"type": "array", "items": {"type": "object", "properties": {
        "name": {"type": "string"}, "yes": {"type": "boolean"}}, "required": ["name", "yes"]}}},
    "required": ["verdicts"],
}

SYSTEM = """You are a senior engineer interviewing a candidate about a whiteboard system design.
You get the question with its requirements, the candidate's diagram as components and connections, and automatic checks.
Judge the diagram against the question. Name the component or connection each finding refers to.
Do not ask for components the requirements do not need. Check the arithmetic in the scale numbers.
Score each dimension from 0 to 10: requirements (are the stated requirements addressed), connections (are the data flows and directions sensible),
correctness (is anything wrong or misleading), tradeoffs (is scale, failure and caching reasoned about).
Keep every item short. Return only the JSON."""

JUDGE_SYSTEM = """You check a candidate's system design diagram. For each named role, answer yes only if the diagram has a box that
really does that job and is connected to the rest of the design. A box whose label just lists several technologies, or that is not connected, is a no.
Return only the JSON."""


def load_questions() -> list[dict]:
    """Every system_design*.json file in the data folder: one file per track, plus the original bank."""
    questions = []
    for path in sorted(DATA_DIR.glob("system_design*.json")):
        questions.extend(json.loads(path.read_text(encoding="utf-8")))
    return questions


TRACKS = ("regular", "ai")
LEVELS = {1: "Easy", 2: "Medium", 3: "Hard"}


def list_questions(track: str | None = None) -> list[dict]:
    """Questions for one track (or all), easiest first."""
    qs = [q for q in load_questions() if track is None or q["track"] == track]
    return sorted(qs, key=lambda q: q["level"])


def get_question(question_id: str) -> dict | None:
    return next((q for q in load_questions() if q["id"] == question_id), None)


def public_question(q: dict) -> dict:
    """What the browser may see: everything except the rubric and the pitfalls used for grading."""
    return {k: v for k, v in q.items() if k not in ("rubric", "pitfalls")} | {"level_label": LEVELS[q["level"]]}


def live_elements(elements: list[dict]) -> list[dict]:
    return [e for e in elements[:MAX_ELEMENTS] if isinstance(e, dict) and not e.get("isDeleted")]


def has_components(elements: list[dict]) -> bool:
    return any(e.get("type") in SHAPES for e in live_elements(elements))


def build_graph(elements: list[dict]) -> dict:
    """Excalidraw stores a label as a separate text element bound to its shape or arrow (containerId),
    and an arrow records the shapes it is attached to (startBinding, endBinding). Read those into a graph."""
    live = live_elements(elements)
    labels = {e["containerId"]: (e.get("text") or "").strip() for e in live if e.get("type") == "text" and e.get("containerId")}
    shapes = [e for e in live if e.get("type") in SHAPES]
    refs = {s["id"]: f"N{i}" for i, s in enumerate(shapes, start=1)}
    nodes = [{"ref": refs[s["id"]], "label": labels.get(s["id"], ""), "shape": s["type"]} for s in shapes]

    edges, dangling = [], 0
    for a in (e for e in live if e.get("type") == "arrow"):
        src = (a.get("startBinding") or {}).get("elementId")
        dst = (a.get("endBinding") or {}).get("elementId")
        if src not in refs or dst not in refs:
            dangling += 1  # an arrow not attached to two shapes
            continue
        edges.append({
            "from": refs[src], "to": refs[dst], "label": labels.get(a["id"], ""),
            "two_way": bool(a.get("startArrowhead") and a.get("endArrowhead")),
        })

    connected = {x for e in edges for x in (e["from"], e["to"])}
    return {
        "nodes": nodes,
        "edges": edges,
        "dangling_arrows": dangling,
        "unlabeled": [n["ref"] for n in nodes if not n["label"]],
        "isolated": [n["ref"] for n in nodes if n["ref"] not in connected],
    }


def component_evidence(graph: dict, rubric_components: list[dict]) -> list[dict]:
    """For each expected component: is there a box named for it, is that box connected, and is the label a plain name
    rather than a keyword list? Only a clean, connected box is a candidate for the judge."""
    patterns = {c["name"]: [re.compile(r"\b" + re.escape(a) + r"\b") for a in c["aliases"]] for c in rubric_components}
    connected = {x for e in graph["edges"] for x in (e["from"], e["to"])}

    def names_matched(label: str) -> int:
        return sum(any(p.search(label) for p in patterns[c["name"]]) for c in rubric_components)

    rows = []
    for c in rubric_components:
        matched = [n for n in graph["nodes"] if any(p.search(n["label"].lower()) for p in patterns[c["name"]])]
        drawn = bool(matched)
        is_connected = any(n["ref"] in connected for n in matched)
        stuffed = any(names_matched(n["label"].lower()) >= STUFFED_COMPONENTS or len(n["label"].split()) > STUFFED_WORDS for n in matched)
        if not drawn:
            note = "not drawn"
        elif stuffed:
            note = "one label lists several components; give each component its own box"
        elif not is_connected:
            note = "drawn but not connected to the design"
        else:
            note = "drawn and connected; checked for its role"
        rows.append({"name": c["name"], "why": c["why"], "drawn": drawn, "connected": is_connected,
                     "candidate": drawn and is_connected and not stuffed, "note": note,
                     "labels": [n["label"] for n in matched]})
    return rows


def _graph_text(graph: dict, question: dict) -> str:
    def node_line(n: dict) -> str:
        return f'{n["ref"]} [{n["shape"]}] "{n["label"] or "(no label)"}"'

    def edge_line(e: dict) -> str:
        arrow = "<->" if e["two_way"] else "->"
        return f'{e["from"]} {arrow} {e["to"]}' + (f' "{e["label"]}"' if e["label"] else "")

    comps = "\n".join(f"- {node_line(n)}" for n in graph["nodes"]) or "- (none)"
    conns = "\n".join(f"- {edge_line(e)}" for e in graph["edges"]) or "- (none)"
    return f"QUESTION: {question['title']}\n{question['prompt']}\n\nDIAGRAM COMPONENTS:\n{comps}\n\nDIAGRAM CONNECTIONS:\n{conns}"


def _review_prompt(graph: dict, question: dict, not_credited: list[str]) -> str:
    reqs = "\n".join(f"- {r}" for r in question["functional"] + question["non_functional"])
    scale = "\n".join(f"- {s}" for s in question["scale"])
    pitfalls = "\n".join(f"- {p}" for p in question["pitfalls"])
    checks = [
        f"- Expected components not credited: {', '.join(not_credited) or 'none'}",
        f"- Shapes with no label: {', '.join(graph['unlabeled']) or 'none'}",
        f"- Shapes with no connections: {', '.join(graph['isolated']) or 'none'}",
        f"- Arrows not attached to two shapes: {graph['dangling_arrows']}",
    ]
    return (
        f"{_graph_text(graph, question)}\n\n"
        f"REQUIREMENTS:\n{reqs}\n\nSCALE:\n{scale}\n\n"
        f"COMMON MISTAKES (for your review):\n{pitfalls}\n\n"
        "AUTOMATIC CHECKS:\n" + "\n".join(checks)
    )


async def _judge_with_lev(lev: LevClient, graph: dict, question: dict, candidates: list[dict]) -> dict[str, bool]:
    questions = {
        f"role_{i}": {"type": "noul", "instructions": f"Does the diagram have a box that does this job and is connected to the design: {c['name']} ({c['why']})?"}
        for i, c in enumerate(candidates)
    }
    state = Redactor().clean(_graph_text(graph, question))  # LEV is a model too: personal details stay out of it
    ans = await lev.decide(state, questions)
    return {c["name"]: float(ans.get(f"role_{i}", {}).get("noul", 0)) >= 0.5 for i, c in enumerate(candidates)}


async def _judge_with_llm(llm: LLM, graph: dict, question: dict, candidates: list[dict]) -> dict[str, bool]:
    roles = "\n".join(f"- {c['name']} ({c['why']})" for c in candidates)
    data = await llm.chat_json(JUDGE_SYSTEM, f"{_graph_text(graph, question)}\n\nROLES TO CHECK:\n{roles}", JUDGE_SCHEMA, temperature=0.1)
    yes = {v.get("name"): bool(v.get("yes")) for v in data.get("verdicts") or [] if isinstance(v, dict)}
    return {c["name"]: yes.get(c["name"], False) for c in candidates}


async def judge_components(llm: LLM, lev: LevClient | None, graph: dict, question: dict, candidates: list[dict]) -> tuple[dict[str, bool], str]:
    """LEV first when it is on, then the LLM if LEV is off or unavailable. Returns (verdict per component, which judge)."""
    if not candidates:
        return {}, "none"
    if lev is not None and lev.enabled:
        try:
            return await _judge_with_lev(lev, graph, question, candidates), "lev"
        except LevUnavailable:
            pass
    return await _judge_with_llm(llm, graph, question, candidates), "llm"


def _score(value: Any) -> float:
    try:
        return max(0.0, min(10.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _items(data: dict, key: str, fields: tuple[str, ...]) -> list[dict]:
    out = []
    for raw in (data.get(key) or [])[:MAX_LIST]:
        if isinstance(raw, dict):
            item = {f: str(raw.get(f, ""))[:240] for f in fields}
            if any(item.values()):
                out.append(item)
    return out


async def review(llm: LLM, question: dict, elements: list[dict], lev: LevClient | None = None) -> dict:
    graph = build_graph(elements)
    rows = component_evidence(graph, question["rubric"]["components"])
    verdicts, judge = await judge_components(llm, lev, graph, question, [r for r in rows if r["candidate"]])
    for r in rows:
        r["credited"] = r["candidate"] and verdicts.get(r["name"], False)
        if r["candidate"] and not r["credited"]:
            r["note"] = "drawn and connected, but the judge did not see this role"

    found = [r["name"] for r in rows if r["credited"]]
    missing = [{"name": r["name"], "why": r["why"] if not r["drawn"] else r["note"]} for r in rows if not r["credited"]]
    not_credited = [m["name"] for m in missing]

    data = await llm.chat_json(SYSTEM, _review_prompt(graph, question, not_credited), REVIEW_SCHEMA, temperature=0.2)
    raw = data.get("scores") or {}
    dims = {d: _score(raw.get(d)) for d in ("requirements", "connections", "correctness", "tradeoffs")}
    dims["components"] = 10 * len(found) / (len(rows) or 1)  # judged credit only, never the LLM's opinion of the keywords
    total = round(sum(dims[d] / 10 * w for d, w in WEIGHTS.items()))

    return {
        "score": total,
        "dimensions": {d: round(v, 1) for d, v in dims.items()},
        "weights": WEIGHTS,
        "judge": judge,
        "checked_components": found,
        "component_checks": [
            {"name": r["name"], "drawn": r["drawn"], "connected": r["connected"], "credited": r["credited"], "note": r["note"], "labels": r["labels"]}
            for r in rows
        ],
        "missing_components": missing[:MAX_LIST],
        "missing_requirements": _items(data, "missing_requirements", ("requirement", "why")),
        "misleading": _items(data, "misleading", ("statement", "why")),
        "strengths": [str(s)[:240] for s in (data.get("strengths") or [])[:MAX_LIST]],
        "summary": str(data.get("summary", ""))[:600],
        "graph": graph,
    }
