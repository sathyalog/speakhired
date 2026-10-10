import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Dialect, WorkerLinter } from "harper.js";
import type { Lint, Suggestion } from "harper.js";
import { binary } from "harper.js/binary";
import { api, LangReport, WriteIssue } from "./api";
import { ArrowIcon, SparkIcon } from "./icons";
import { useMode } from "./mode";

type Cat = "spelling" | "grammar" | "punctuation" | "style" | "ai";
type Option = { label: string; apply: () => Promise<string> | string };
type Issue = { id: string; cat: Cat; start: number; end: number; original: string; message: string; options: Option[]; lint?: Lint; ai?: WriteIssue };

const CAT_LABEL: Record<Cat, string> = { spelling: "Spelling", grammar: "Grammar", punctuation: "Punctuation", style: "Style", ai: "AI suggestions" };
const CAT_BADGE: Record<Cat, string> = { spelling: "badge-error", grammar: "badge-warning", punctuation: "badge-warning", style: "badge-info", ai: "badge-secondary" };
const CAT_WEIGHT: Record<Cat, number> = { spelling: 3, grammar: 3, punctuation: 2, style: 1, ai: 1 };
const DIALECTS: { id: string; label: string; value: Dialect }[] = [
  { id: "british", label: "British English", value: Dialect.British },
  { id: "indian", label: "Indian English", value: Dialect.Indian },
  { id: "american", label: "American English", value: Dialect.American },
];
const KINDS = [["general", "General message"], ["cover_letter", "Cover letter"], ["recruiter_email", "Email to a recruiter"], ["linkedin", "LinkedIn message"], ["resume_summary", "Resume summary"]];
const TONES = [["professional", "Professional"], ["friendly", "Friendly"], ["confident", "Confident"], ["concise", "Concise"]];
const SAMPLE = "Dear Hiring Manager,\n\nI am writing this email to you in order to express my intrest in the Backend Engineer position that was advertised in your website. I have been working with Python and Kafka since 3 years and I am having good knowlege of REST APIs.\n\nPlease find my resume attached. I look forward to hear from you.\n\nThanks and regards,\nPriya";

function category(kind: string): Cat {
  const k = kind.toLowerCase();
  if (k.includes("spell") || k.includes("typo")) return "spelling";
  if (k.includes("punct") || k.includes("capital") || k.includes("format")) return "punctuation";
  if (k.includes("grammar") || k.includes("agree") || k.includes("usage") || k.includes("eggcorn") || k.includes("malapropism") || k.includes("nonstandard")) return "grammar";
  return "style";
}

function suggestionLabel(s: Suggestion): string {
  const text = s.get_replacement_text();
  const kind = s.kind() as number; // 0 replace, 1 remove, 2 insert after
  return kind === 1 ? "Remove" : kind === 2 ? `Add “${text}”` : text || "Remove";
}

export function CleanCopy() {
  const { info } = useMode();
  const online = info?.mode === "online";
  const [text, setText] = useState("");
  const [dialect, setDialect] = useState("british");
  const [kind, setKind] = useState("general");
  const [tone, setTone] = useState("professional");
  const [harper, setHarper] = useState<Issue[]>([]);
  const [ai, setAi] = useState<WriteIssue[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiErr, setAiErr] = useState("");
  const [rewrite, setRewrite] = useState<string | null>(null);
  const [lang, setLang] = useState<LangReport | null>(null);
  const [copied, setCopied] = useState(false);
  const [pop, setPop] = useState<{ top: number; left: number } | null>(null);
  const linter = useRef<WorkerLinter | null>(null);
  const lintRun = useRef(0);
  const ta = useRef<HTMLTextAreaElement>(null);
  const back = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const l = new WorkerLinter({ binary, dialect: Dialect.British });
    linter.current = l;
    l.setup().then(async () => {
      try { const saved: string[] = JSON.parse(localStorage.getItem("cc_words") ?? "[]"); if (saved.length) await l.importWords(saved); } catch { /* storage unavailable */ }
      setReady(true);
    }).catch(() => setReady(false));
    return () => { void l.dispose(); };
  }, []);

  useEffect(() => { void linter.current?.setDialect(DIALECTS.find((d) => d.id === dialect)!.value).then(() => setText((t) => t + "")); }, [dialect]);

  const runLint = useCallback(async (value: string) => {
    const l = linter.current;
    if (!l || !value.trim()) { setHarper([]); return; }
    const run = ++lintRun.current;
    const lints = await l.lint(value);
    if (run !== lintRun.current) return;
    const astral = /[\u{10000}-\u{10FFFF}]/u.test(value);
    const chars = astral ? Array.from(value) : null;
    const idx = (i: number) => (chars ? chars.slice(0, i).join("").length : i);
    const out: Issue[] = lints.map((lint, n) => {
      const span = lint.span();
      const start = idx(span.start), end = idx(span.end);
      return {
        id: `h${n}-${start}`, cat: category(lint.lint_kind()), start, end, original: value.slice(start, end), message: lint.message(), lint,
        options: lint.suggestions().slice(0, 4).map((s): Option => ({ label: suggestionLabel(s), apply: () => l.applySuggestion(value, lint, s) })),
      };
    }).sort((a, b) => a.start - b.start);
    const kept: Issue[] = [];
    for (const it of out) if (!kept.length || it.start >= kept[kept.length - 1].end) kept.push(it);
    setHarper(kept);
  }, []);

  useEffect(() => {
    const t = setTimeout(() => void runLint(text), 300);
    return () => clearTimeout(t);
  }, [text, runLint, ready]);

  useEffect(() => {
    if (text.trim().length < 12) { setLang(null); return; }
    const t = setTimeout(() => { api.checkLanguage(text, null).then(setLang).catch(() => {}); }, 800);
    return () => clearTimeout(t);
  }, [text]);

  // AI issues stay valid only while their quote is still in the draft and does not overlap a Harper issue.
  const aiIssues: Issue[] = useMemo(() => {
    const out: Issue[] = [];
    ai.forEach((a, n) => {
      let start = text.slice(a.start, a.end) === a.original ? a.start : text.indexOf(a.original);
      if (start < 0) return;
      const end = start + a.original.length;
      if (harper.some((h) => start < h.end && end > h.start)) return;
      out.push({ id: `a${n}`, cat: "ai", start, end, original: a.original, message: a.message || a.category, ai: a,
        options: [{ label: a.replacement, apply: () => text.slice(0, start) + a.replacement + text.slice(end) }] });
    });
    return out;
  }, [ai, harper, text]);

  const issues = useMemo(() => [...harper, ...aiIssues].sort((a, b) => a.start - b.start), [harper, aiIssues]);
  const current = issues.find((i) => i.id === active) ?? null;

  const segments = useMemo(() => {
    const nodes: (string | JSX.Element)[] = [];
    let pos = 0;
    for (const it of issues) {
      if (it.start < pos) continue;
      nodes.push(text.slice(pos, it.start));
      nodes.push(<mark key={it.id} data-iid={it.id} className={`cc-mark cc-${it.cat} ${it.id === active ? "cc-active" : ""}`}>{text.slice(it.start, it.end)}</mark>);
      pos = it.end;
    }
    nodes.push(text.slice(pos));
    return nodes;
  }, [issues, text, active]);

  useLayoutEffect(() => {
    if (!current || !box.current || !back.current) { setPop(null); return; }
    const el = back.current.querySelector(`[data-iid="${current.id}"]`) as HTMLElement | null;
    if (!el) { setPop(null); return; }
    const r = el.getBoundingClientRect(), c = box.current.getBoundingClientRect();
    setPop({ top: Math.min(r.bottom - c.top + 6, c.height - 40), left: Math.max(8, Math.min(r.left - c.left, c.width - 330)) });
  }, [current, text, issues]);

  async function accept(it: Issue, opt: Option) {
    const next = await opt.apply();
    setText(next);
    setActive(null);
    ta.current?.focus();
  }

  async function ignore(it: Issue) {
    setActive(null);
    if (it.lint && linter.current) { await linter.current.ignoreLint(text, it.lint); void runLint(text); }
    else if (it.ai) setAi((xs) => xs.filter((x) => x !== it.ai));
  }

  async function addToDictionary(it: Issue) {
    const word = it.original.trim();
    if (!word || !linter.current) return;
    await linter.current.importWords([word]);
    try { const saved: string[] = JSON.parse(localStorage.getItem("cc_words") ?? "[]"); localStorage.setItem("cc_words", JSON.stringify([...new Set([...saved, word])])); } catch { /* ignore */ }
    setActive(null);
    void runLint(text);
  }

  async function acceptAll() {
    const l = linter.current;
    if (!l) return;
    let next = text;
    for (const it of [...harper].reverse()) {  // from the end, so earlier positions stay valid
      if (it.cat === "style" || !it.lint) continue;
      if (it.cat === "spelling" && /^[A-Z]/.test(it.original)) continue;  // names and acronyms: do not guess
      const first = it.lint.suggestions()[0];
      if (first) next = await l.applySuggestion(next, it.lint, first);
    }
    setText(next);
    setActive(null);
  }

  function caretIssue() {
    const pos = ta.current?.selectionStart ?? -1;
    const hit = issues.find((i) => pos >= i.start && pos <= i.end);
    setActive(hit ? hit.id : null);
  }

  async function improve(withRewrite: boolean) {
    setAiBusy(true); setAiErr("");
    try {
      const r = await api.improveWriting(text, kind, tone, withRewrite);
      setAi(r.issues);
      if (withRewrite) setRewrite(r.rewrite);
      if (!r.issues.length && !r.rewrite) setAiErr("The AI found nothing more to improve.");
    } catch (e: any) { setAiErr(e.message || "The AI could not check this draft. Is Ollama running?"); } finally { setAiBusy(false); }
  }

  const words = (text.match(/\S+/g) ?? []).length;
  const penalty = issues.reduce((a, i) => a + CAT_WEIGHT[i.cat], 0);
  const score = words ? Math.round(100 * (1 - Math.min(1, penalty / Math.max(words * 0.5, 15)))) : 0;
  const counts = (Object.keys(CAT_LABEL) as Cat[]).map((c) => [c, issues.filter((i) => i.cat === c).length] as const);
  const fixable = harper.filter((i) => i.cat !== "style" && i.options.length && !(i.cat === "spelling" && /^[A-Z]/.test(i.original))).length;

  const shared: React.CSSProperties = {
    fontFamily: "var(--font-sans)", fontSize: 16, lineHeight: 1.75, padding: 16, whiteSpace: "pre-wrap", wordBreak: "break-word", overflowWrap: "anywhere",
    letterSpacing: "normal", border: "1px solid transparent", boxSizing: "border-box", margin: 0,
  };

  return (
    <div>
      <h1 className="text-3xl font-semibold md:text-4xl">Clean Copy</h1>
      <p className="mt-1 max-w-2xl text-base-content/70">Paste a cover letter or an email to a recruiter. Spelling and grammar are checked as you type, right on your device.</p>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <select className="select select-sm w-auto" value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Document type">{KINDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        <select className="select select-sm w-auto" value={tone} onChange={(e) => setTone(e.target.value)} aria-label="Tone">{TONES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        <select className="select select-sm w-auto" value={dialect} onChange={(e) => setDialect(e.target.value)} aria-label="English dialect">{DIALECTS.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}</select>
        {!ready && <span className="badge badge-ghost gap-1"><span className="loading loading-spinner loading-xs" /> Loading checker</span>}
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <div ref={box} className="relative rounded-box border border-base-300 bg-base-100">
            <div ref={back} aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden text-transparent" style={shared}>
              {segments}{"\n​"}
            </div>
            <textarea
              ref={ta} value={text} spellCheck={false} placeholder="Paste or type your draft here…"
              onChange={(e) => { setText(e.target.value); setActive(null); }}
              onScroll={(e) => { if (back.current) back.current.scrollTop = e.currentTarget.scrollTop; setActive(null); }}
              onClick={caretIssue} onKeyUp={(e) => { if (e.key.startsWith("Arrow")) caretIssue(); }}
              className="relative block h-96 w-full resize-y rounded-box bg-transparent outline-none focus:border-primary" style={{ ...shared, color: "var(--color-base-content)" }}
            />
            {current && pop && (
              <div className="absolute z-10 w-80 rounded-box border border-base-300 bg-base-100 p-3 shadow-lg" style={{ top: pop.top, left: pop.left }} role="dialog">
                <div className="mb-1 flex items-center gap-2"><span className={`badge badge-soft badge-sm ${CAT_BADGE[current.cat]}`}>{CAT_LABEL[current.cat]}</span><span className="truncate text-sm font-medium">{current.original}</span></div>
                <p className="mb-2 text-sm text-base-content/70">{current.message}</p>
                <div className="flex flex-wrap gap-1.5">
                  {current.options.map((o, k) => <button key={k} className="btn btn-primary btn-sm rounded-full" onClick={() => accept(current, o)}>{o.label}</button>)}
                  {current.cat === "spelling" && <button className="btn btn-ghost btn-sm rounded-full" onClick={() => addToDictionary(current)}>Add to dictionary</button>}
                  <button className="btn btn-ghost btn-sm rounded-full" onClick={() => ignore(current)}>Ignore</button>
                </div>
              </div>
            )}
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button className="btn btn-primary btn-sm rounded-full" disabled={!fixable} onClick={acceptAll}>Fix all {fixable ? `(${fixable})` : ""}</button>
            <button className="btn btn-sm rounded-full" disabled={!text.trim() || aiBusy} onClick={() => improve(false)}>
              {aiBusy ? <span className="loading loading-dots loading-xs" /> : <SparkIcon />} Improve with AI
            </button>
            <button className="btn btn-sm rounded-full" disabled={!text.trim() || aiBusy} onClick={() => improve(true)}>Rewrite my draft</button>
            <button className="btn btn-ghost btn-sm rounded-full" disabled={!text} onClick={async () => { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>{copied ? "Copied" : "Copy"}</button>
            <button className="btn btn-ghost btn-sm rounded-full" onClick={() => { setText(SAMPLE); setAi([]); setRewrite(null); }}>Try a sample</button>
            <button className="btn btn-ghost btn-sm rounded-full" disabled={!text} onClick={() => { setText(""); setAi([]); setRewrite(null); setActive(null); }}>Clear</button>
          </div>
          {aiBusy && <p className="mt-2 text-sm text-base-content/60">{online ? `${info?.grok.provider} is reading the draft.` : "Ollama is reading the draft. This can take a minute on a small computer."}</p>}
          {aiErr && <div role="alert" className="alert alert-soft alert-warning mt-2 text-sm">{aiErr}</div>}
          {lang && lang.status !== "english" && <div role="alert" className="alert alert-soft alert-info mt-2 text-sm">This draft contains {lang.language_name} words. Clean Copy checks English only.</div>}
          {rewrite && (
            <div className="card mt-3 border border-primary/40 bg-primary/5"><div className="card-body gap-2">
              <h2 className="card-title text-base">A cleaner version</h2>
              <p className="whitespace-pre-wrap text-sm">{rewrite}</p>
              <div className="card-actions"><button className="btn btn-primary btn-sm rounded-full" onClick={() => { setText(rewrite); setRewrite(null); setAi([]); }}>Use this version <ArrowIcon /></button>
                <button className="btn btn-ghost btn-sm rounded-full" onClick={() => setRewrite(null)}>Dismiss</button></div>
            </div></div>
          )}
          <p className="mt-3 text-xs text-base-content/50">Spelling and grammar run in your browser, nothing is uploaded. “Improve with AI” sends your text, with personal details removed, to {online ? info?.grok.provider : "Ollama on this computer"}.</p>
        </div>

        <div className="flex flex-col gap-3">
          <div className="card border border-base-300 bg-base-100"><div className="card-body gap-3">
            <div className="flex items-center gap-4">
              <div className="radial-progress text-primary" style={{ "--value": score, "--size": "4.5rem", "--thickness": "0.4rem" } as React.CSSProperties} role="img" aria-label={`Writing score ${score}`}>{words ? score : "–"}</div>
              <div className="text-sm"><div className="font-medium">Writing score</div><div className="text-base-content/60">{words} words · {Math.max(1, Math.round(words / 200))} min read</div></div>
            </div>
            <div className="flex flex-wrap gap-1.5">{counts.map(([c, n]) => <span key={c} className={`badge badge-soft ${CAT_BADGE[c]}`}>{CAT_LABEL[c]} {n}</span>)}</div>
          </div></div>
          <div className="card border border-base-300 bg-base-100"><div className="card-body gap-2 p-4">
            <h2 className="card-title text-base">Suggestions</h2>
            {!issues.length && <p className="text-sm text-base-content/60">{text.trim() ? "Nothing to fix. Nice work." : "Your suggestions will appear here."}</p>}
            <ul className="flex max-h-96 flex-col gap-1.5 overflow-y-auto">
              {issues.map((it) => (
                <li key={it.id}>
                  <button className={`w-full rounded-field border p-2 text-left text-sm transition ${it.id === active ? "border-primary bg-primary/5" : "border-base-300 hover:border-primary/50"}`}
                    onClick={() => { setActive(it.id); ta.current?.focus(); ta.current?.setSelectionRange(it.start, it.end); }}>
                    <span className={`badge badge-soft badge-xs mr-2 ${CAT_BADGE[it.cat]}`}>{CAT_LABEL[it.cat]}</span>
                    <span className="font-medium">{it.original}</span>
                    {it.options[0] && <span className="text-base-content/60"> → {it.options[0].label}</span>}
                  </button>
                </li>
              ))}
            </ul>
          </div></div>
        </div>
      </div>
    </div>
  );
}
