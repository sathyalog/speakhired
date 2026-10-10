"""Personal-information redaction. Nothing that identifies a person should reach any language model.

`Redactor` swaps sensitive text for numbered tokens like [NAME_1] and can restore them afterwards, so a model
can still reason about "[NAME_1] built the service" and the answer shown to the user has the real text back.
Technology names and employers are deliberately kept: they are what a resume review needs.
"""
import json
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

# ---------- patterns ----------
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_URL = re.compile(
    r"https?://\S+|www\.\S+|"
    r"(?:linkedin|github|gitlab|bitbucket|twitter|x|instagram|facebook|medium|leetcode|hackerrank|kaggle|stackoverflow|behance|dribbble)\.com/\S+|"
    r"\bwa\.me/\S+|\bt\.me/\S+", re.I)
_PHONE = re.compile(r"(?<![\w.])(\+?\d[\d\s().-]{8,}\d)(?!\w)")
_AADHAAR = re.compile(r"(?<![\d-])\d{4}[ -]?\d{4}[ -]?\d{4}(?![\d-])")
_PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
_PASSPORT = re.compile(r"\b[A-Z]\d{7}\b")
_IFSC = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
_CARD = re.compile(r"(?<![\d-])(?:\d[ -]?){13,19}(?![\d-])")
_ACCOUNT = re.compile(r"(?i)\b(?:a/c|acct|account)\b[^\n\d]{0,25}(\d{9,18})")
_PIN = re.compile(r"\b[1-9]\d{5}\b")
_STREET = re.compile(r"(?i)\b(?:road|rd\.?|street|st\.|nagar|colony|lane|apartment|apt\.?|flat|plot|sector|block|village|mandal|dist(?:rict)?\.?|near|opp\.?|house no|h\.?no)\b")
_LABEL_NAME = re.compile(r"(?im)^(\s*(?:full\s+)?name|\s*father'?s?\s+name|\s*mother'?s?\s+name|\s*husband'?s?\s+name|\s*spouse|\s*nominee|\s*referee|\s*reference|\s*references)\s*[:\-–]\s*(.+)$")
_LABEL_DOB = re.compile(r"(?im)^(\s*(?:dob|d\.o\.b\.?|date\s+of\s+birth|born(?:\s+on)?))\s*[:\-–]?\s*(.+)$")
_LABEL_ADDRESS = re.compile(r"(?im)^(\s*(?:permanent\s+|current\s+|present\s+|residential\s+)?address(?:\s+for\s+communication)?)\s*[:\-–]\s*(.+)$")
_LABEL_PERSONAL = re.compile(r"(?im)^(\s*(?:marital\s+status|religion|caste|community|passport(?:\s+no\.?)?|aadhaar(?:\s+no\.?)?|aadhar(?:\s+no\.?)?|pan(?:\s+no\.?)?|voter\s+id))\s*[:\-–]\s*(.+)$")
_HONORIFIC = re.compile(r"\b(?:Mr|Mrs|Ms|Miss|Dr|Shri|Smt|Prof)\.?\s+((?:[A-Z][a-z]+)(?:\s+[A-Z][a-z]+){0,2})")
_NOT_NAME_LINE = re.compile(r"(?i)^(resume|curriculum vitae|cv|profile|summary|objective|contact|about me|experience|education|skills|projects)\b")

_EXTRA_TECH = set("""kafka jenkins spring boot docker compose redis kubernetes react angular vue django flask terraform ansible airflow spark hadoop oracle
mysql postgres postgresql mongodb linux android apache azure aws google microsoft oauth jwt swagger postman jira confluence splunk grafana
prometheus kibana elastic elasticsearch maven gradle git github gitlab bitbucket salesforce sap tableau power bi snowflake databricks
kotlin swift flutter node nodejs express nest next nuxt svelte tailwind bootstrap graphql grpc rabbitmq nginx tomcat hibernate junit selenium
cypress jest mocha pytest numpy pandas tensorflow pytorch keras scikit sklearn opencv hugging face openai kubernetes helm istio vault consul
rest api orders service payments platform""".split())
_ACTION_START = {"mentored", "led", "built", "managed", "worked", "developed", "created", "designed", "trained", "supervised", "guided", "coached", "hired"}
_ORG_WORDS = set("""pay technologies technology solutions systems labs lab university college institute school bank services software consulting consultancy
infotech global group limited ltd pvt inc corp corporation company hospital academy analytics networks digital health finance capital industries
enterprises research center centre foundation association department""".split())
_PLACES = set("""hyderabad secunderabad bangalore bengaluru chennai mumbai pune delhi noida gurgaon gurugram kolkata ahmedabad kochi coimbatore visakhapatnam vizag
jaipur indore lucknow chandigarh trivandrum thiruvananthapuram mysore nagpur london new york san francisco singapore dubai india usa uk""".split())
_ROLE_WORDS = set("""junior senior team teams developers developer engineers engineer interns intern students members member colleagues managers manager
leads lead architects architect analysts analyst testers qa devops staff people cross functional""".split())
_NAME = r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}"
_PERSON_CONTEXT = re.compile(r"(?i:\b(?:worked with|reported to|reporting to|reports to|guided by|mentored by|managed by|supervised by|coached by|thanks to|referee|reference|manager|mentor)\b[:,]?\s+)(" + _NAME + r"(?:\s*(?:,|and|&)\s*" + _NAME + r")*)(?![\w])")
TOKEN_RE = re.compile(r"\[(NAME|EMAIL|PHONE|LINK|ID|DOB|ADDRESS|ACCOUNT|PERSONAL)_(\d+)\]")
_LABELS = {"NAME": "name", "EMAIL": "email", "PHONE": "phone number", "LINK": "link", "ID": "ID number", "DOB": "birth date",
           "ADDRESS": "address", "ACCOUNT": "bank or card number", "PERSONAL": "personal detail"}


@lru_cache(maxsize=1)
def _tech_words() -> frozenset[str]:
    words = set(_EXTRA_TECH)
    try:
        raw = json.loads((Path(__file__).resolve().parent / "data" / "skill_aliases.json").read_text(encoding="utf-8"))
        for canon, alts in raw.items():
            if canon.startswith("_"):
                continue
            for item in [canon, *alts]:
                words.update(re.findall(r"[a-z0-9+#.]+", item.lower()))
    except OSError:
        pass
    return frozenset(words)


def _commonish(word: str) -> bool:
    w = word.lower()
    return (w in _tech_words() or w in _ORG_WORDS or w in _PLACES or w in _ROLE_WORDS
            or w.endswith(("ers", "ors", "ists", "ing", "tion", "ment", "ness", "ity", "ics", "ogy", "ure")))


def _digits(s: str) -> int:
    return sum(c.isdigit() for c in s)


def _is_phone(m) -> bool:
    return _digits(m.group()) >= 10  # year ranges like "2017 - 2021" have only 8 digits


def has_phone(text: str) -> bool:
    return any(_is_phone(m) for m in _PHONE.finditer(text))


class Redactor:
    """Reversible redaction for one request. Create one per piece of text you are about to send to a model."""

    def __init__(self, extra_terms: list[str] | None = None):
        self.tokens: dict[str, str] = {}      # token -> original text
        self._by_text: dict[str, str] = {}    # original text -> token
        self.counts: Counter[str] = Counter()
        self.extra_terms = [t for t in (extra_terms or []) if t.strip()]
        self.known_names: set[str] = set()   # names found by reliable signals, hidden everywhere in later text too

    # ----- core -----
    def _token(self, kind: str, original: str, count: bool = True) -> str:
        key = f"{kind}:{original.strip().lower()}"
        if key in self._by_text:
            return self._by_text[key]
        n = sum(1 for k in self.tokens if k.startswith(f"[{kind}_")) + 1
        tok = f"[{kind}_{n}]"
        self.tokens[tok] = original.strip()
        self._by_text[key] = tok
        if count:
            self.counts[kind] += 1
        return tok

    def _sub(self, rx, kind: str, text: str, group: int = 0, check=None) -> str:
        def repl(m):
            if check and not check(m):
                return m.group()
            if group:
                whole, val = m.group(), m.group(group)
                return whole.replace(val, self._token(kind, val), 1)
            return self._token(kind, m.group())
        return rx.sub(repl, text)

    def _label_values(self, rx, kind: str, text: str) -> str:
        return rx.sub(lambda m: f"{m.group(1)}: {self._token(kind, m.group(2))}", text)

    def _names(self, text: str) -> str:
        # 1. the name line at the top of a resume
        lines = text.split("\n")
        first = next((i for i, ln in enumerate(lines) if ln.strip()), None)
        header = None
        if first is not None:
            cand = lines[first].strip()
            words = cand.split()
            if 1 < len(words) <= 4 and not re.search(r"[\d@:/|•]", cand) and not _NOT_NAME_LINE.match(cand) and all(w[:1].isupper() for w in words):
                if not any(_commonish(w.strip(".,")) for w in words):
                    header = cand
                    self.known_names.add(cand)
                    lines[first] = lines[first].replace(cand, self._token("NAME", cand))
        text = "\n".join(lines)
        if header:  # the same full name elsewhere (signature, summary)
            text = re.sub(re.escape(header), lambda m: self._token("NAME", header), text, flags=re.I)
        # 2. honorific + name
        text = self._sub(_HONORIFIC, "NAME", text, group=1)
        # 3a. "worked with Ravi Kumar", "mentored by Anita Rao": a capitalised name right after a people-word
        def _ctx(m):
            out = m.group()
            for name in re.split(r"\s*(?:,|and|&)\s*", m.group(1)):
                if name and not any(_commonish(w) for w in name.split()):
                    out = out.replace(name, self._token("NAME", name), 1)
            return out
        text = _PERSON_CONTEXT.sub(_ctx, text)
        # 3. the parts of the header name on their own ("Ramesh led the team"), but never a word that is also technology or a place
        if header:
            for part in header.split():
                part = part.strip(".,")
                if len(part) >= 3 and part[:1].isupper() and not _commonish(part):
                    text = re.sub(rf"\b{re.escape(part)}\b", lambda m: self._token("NAME", m.group(), count=False), text)  # same person: not counted twice
        # 4. names found earlier in this request (so a system prompt written before the resume is covered too)
        for name in sorted(self.known_names, key=len, reverse=True):
            text = re.sub(re.escape(name), lambda m: self._token("NAME", name, count=False), text, flags=re.I)
            for part in name.split():
                part = part.strip(".,")
                if len(part) >= 3 and part[:1].isupper() and not _commonish(part):
                    text = re.sub(rf"\b{re.escape(part)}\b", lambda m: self._token("NAME", m.group(), count=False), text)
        # 5. names the caller already knows (e.g. from earlier parsing)
        for term in sorted(self.extra_terms, key=len, reverse=True):
            text = re.sub(re.escape(term), lambda m: self._token("NAME", m.group()), text, flags=re.I)
        return text

    def _label_name(self, m) -> str:
        if not self._namey(m.group(1), m.group(2)):
            return m.group(0)
        self.known_names.add(m.group(2).strip())
        return f"{m.group(1)}: {self._token('NAME', m.group(2))}"

    @staticmethod
    def _namey(label: str, value: str) -> bool:
        if not re.match(r"(?i)\s*(reference|references|referee|nominee|spouse)", label):
            return True  # "Name:", "Father's name:" are always names
        return bool(re.match(r"(?:(?:Mr|Mrs|Ms|Dr|Shri|Smt|Prof)\.?\s+)?[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\b", value.strip())) and not any(_commonish(w) for w in value.split())

    def _addresses(self, text: str) -> str:
        text = self._label_values(_LABEL_ADDRESS, "ADDRESS", text)
        out = []
        for ln in text.split("\n"):
            if "[ADDRESS_" not in ln and ln.count(",") >= 2 and (_PIN.search(ln) or (_STREET.search(ln) and re.search(r"\d", ln))) and len(ln) < 200:
                ln = self._token("ADDRESS", ln.strip())
            out.append(ln)
        return "\n".join(out)

    def clean(self, text: str) -> str:
        if not text:
            return text
        t = text
        t = self._sub(_EMAIL, "EMAIL", t)
        t = self._sub(_URL, "LINK", t)
        t = self._label_values(_LABEL_PERSONAL, "PERSONAL", t)
        t = self._label_values(_LABEL_DOB, "DOB", t)
        t = _LABEL_NAME.sub(lambda m: self._label_name(m), t)
        t = self._sub(_ACCOUNT, "ACCOUNT", t, group=1)
        t = self._sub(_CARD, "ACCOUNT", t, check=lambda m: 13 <= _digits(m.group()) <= 19)
        t = self._sub(_AADHAAR, "ID", t)
        t = self._sub(_PAN, "ID", t)
        t = self._sub(_IFSC, "ID", t)
        t = self._sub(_PASSPORT, "ID", t)
        t = self._sub(_PHONE, "PHONE", t, check=_is_phone)
        t = self._addresses(t)
        t = self._names(t)
        return t

    def restore(self, text: str) -> str:
        if not self.tokens or not isinstance(text, str):
            return text
        return TOKEN_RE.sub(lambda m: self.tokens.get(m.group(), m.group()), text)

    def restore_json(self, obj):
        if isinstance(obj, str):
            return self.restore(obj)
        if isinstance(obj, list):
            return [self.restore_json(x) for x in obj]
        if isinstance(obj, dict):
            return {k: self.restore_json(v) for k, v in obj.items()}
        return obj

    def summary(self) -> dict[str, int]:
        """What was removed, by friendly category (never the values)."""
        return {_LABELS[k]: v for k, v in self.counts.items() if v}




def describe(summary: dict[str, int]) -> str:
    if not summary:
        return ""
    parts = [f"{n} {label}{'s' if n > 1 and not label.endswith('s') else ''}" for label, n in summary.items()]
    return ", ".join(parts)


# ---------- helpers used across the app ----------
def redact(text: str, extra_terms: list[str] | None = None) -> str:
    """One-way redaction (no restore). Used before text leaves for LEV or a web lookup."""
    return Redactor(extra_terms).clean(text)


def contains_pii(text: str) -> bool:
    return bool(_EMAIL.search(text) or has_phone(text) or _URL.search(text))
