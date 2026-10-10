import { useEffect, useState } from "react";
import { api, AtsReport } from "./api";
import { useMode } from "./mode";
import { ArrowIcon, ShieldIcon, SparkIcon } from "./icons";

const PRIORITY_BADGE = { high: "badge-error", medium: "badge-warning", low: "badge-info" } as const;
const SECTION_ORDER = ["format", "structure", "readability"];
const SECTION_NAME: Record<string, string> = { format: "Format and parseability", structure: "Contact and structure", readability: "Readability and length" };

export function ResumeRadar() {
  const { info } = useMode();
  const online = info?.mode === "online";
  const [file, setFile] = useState<File | null>(null);
  const [jdText, setJdText] = useState("");
  const [jdUrl, setJdUrl] = useState("");
  const [lev, setLev] = useState<{ available: boolean; remote: boolean }>({ available: false, remote: false });
  const [useLev, setUseLev] = useState(false);
  const [useAi, setUseAi] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [report, setReport] = useState<AtsReport | null>(null);
  const [extra, setExtra] = useState<{ state: "loading" | "done" | "error"; items: AtsReport["suggestions"] }>({ state: "done", items: [] });

  useEffect(() => {
    api.health().then((h) => {
      const available = ["http", "local"].includes(h.lev?.mode) && !!h.lev?.ok, remote = !!h.lev?.remote;
      setLev({ available, remote });
      setUseLev(available && !remote);  // remote LEV is opt-in; local LEV is on by default
    }).catch(() => {});
  }, []);

  async function analyse() {
    setErr("");
    if (!file) return setErr("Choose your resume first (PDF or Word).");
    setBusy(true);
    try {
      setReport(await api.analyzeResume(file, jdText, jdUrl, useLev, useAi)); window.scrollTo({ top: 0 });
      if (useAi) {  // the slower bullet rewrites arrive after the score
      setExtra({ state: "loading", items: [] });
      api.atsRewrites(file).then((r) => setExtra({ state: "done", items: r.suggestions })).catch(() => setExtra({ state: "error", items: [] }));
      } else setExtra({ state: "done", items: [] });
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  if (report) return <Result r={report} extra={extra} onAgain={() => setReport(null)} />;

  return (
    <div>
      <h1 className="text-3xl font-semibold md:text-4xl">Resume Radar</h1>
      <p className="mt-1 max-w-2xl text-base-content/70">Upload your resume and see how well an applicant tracking system (ATS) can read it, with clear fixes to raise your score.</p>
      <div className="mt-6 grid gap-4 lg:grid-cols-2 [&>*]:min-w-0">
        <div className="card min-w-0 border border-base-300 bg-base-100"><div className="card-body min-w-0 gap-1">
          <h2 className="card-title">Your resume</h2>
          <fieldset className="fieldset min-w-0">
            <legend className="fieldset-legend">PDF or Word file</legend>
            <input type="file" className="file-input w-full" accept=".pdf,.docx,.txt" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <p className="label flex items-start gap-1.5 whitespace-normal [&>svg]:mt-0.5 [&>svg]:shrink-0"><ShieldIcon /> Up to 5 MB. Not saved. Names, contact details, IDs and addresses are removed before any AI step.</p>
          </fieldset>
          <label className="mt-1 flex cursor-pointer items-start justify-between gap-4 rounded-box border border-base-300 p-3">
            <span className="text-sm">Use AI to review the content <span className="badge badge-soft badge-primary badge-sm ml-1">{online ? "Grok, online" : "Ollama, offline"}</span>
              <span className="block text-xs text-base-content/60">{online ? "Fast. Grok reads a version with personal details removed. LEV on your server is used as well." : "Slower on small computers (a few minutes) but gives a deeper review and stronger wording for weak bullets."} Off gives an instant score from clear rules.</span></span>
            <input type="checkbox" className="toggle toggle-primary toggle-sm mt-1" checked={useAi} onChange={(e) => setUseAi(e.target.checked)} />
          </label>
          {lev.available && useAi && !online && (
            <label className="mt-1 flex cursor-pointer items-start justify-between gap-4 rounded-box border border-base-300 p-3">
              <span className="text-sm">Use LEV for the content score
                <span className="block text-xs text-base-content/60">
                  {lev.remote ? "LEV runs on your remote server, so a redacted copy of the resume is sent there: no name, email, phone or links. Off means Ollama on this computer scores it." : "LEV runs on your own computer or network."}
                </span></span>
              <input type="checkbox" className="toggle toggle-primary toggle-sm mt-1" checked={useLev} onChange={(e) => setUseLev(e.target.checked)} />
            </label>
          )}
        </div></div>

        <div className="card min-w-0 border border-base-300 bg-base-100"><div className="card-body min-w-0 gap-1">
          <h2 className="card-title">Job description <span className="badge badge-ghost badge-sm">optional</span></h2>
          <p className="text-sm text-base-content/60">Add the job you are applying for to check keyword match.</p>
          <fieldset className="fieldset min-w-0">
            <legend className="fieldset-legend">Link to the job post</legend>
            <input className="input w-full" placeholder="https://company.com/careers/backend-engineer" value={jdUrl} onChange={(e) => setJdUrl(e.target.value)} />
          </fieldset>
          <fieldset className="fieldset min-w-0">
            <legend className="fieldset-legend">Or paste the text</legend>
            <textarea className="textarea h-32 w-full" value={jdText} onChange={(e) => setJdText(e.target.value)} placeholder="Paste the job description" />
          </fieldset>
        </div></div>
      </div>
      {err && <div role="alert" className="alert alert-error alert-soft mt-4 text-sm">{err}</div>}
      <button className="btn btn-primary mt-4 rounded-full px-8" onClick={analyse} disabled={busy}>
        {busy ? <><span className="loading loading-dots loading-sm" /> Analysing, this can take a minute</> : <><SparkIcon /> Check my resume</>}
      </button>
    </div>
  );
}

function Result({ r, extra, onAgain }: { r: AtsReport; extra: { state: "loading" | "done" | "error"; items: AtsReport["suggestions"] }; onAgain: () => void }) {
  const suggestions = [...r.suggestions, ...extra.items];
  const tone = r.score >= 85 ? "text-success" : r.score >= 70 ? "text-primary" : r.score >= 50 ? "text-warning" : "text-error";
  const failed = r.checks.filter((c) => c.credit < 1);
  const passed = r.checks.filter((c) => c.credit >= 1);
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-3xl font-semibold md:text-4xl">Your resume report</h1>
        <button className="btn btn-outline btn-sm rounded-full" onClick={onAgain}>Check another resume</button>
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-5">
        <div className="card border border-base-300 bg-base-100 lg:col-span-2"><div className="card-body items-center text-center">
          <div className={`radial-progress ${tone}`} style={{ "--value": r.score, "--size": "10rem", "--thickness": "0.7rem" } as React.CSSProperties} role="img" aria-label={`ATS score ${r.score} out of 100`}>
            <span className="font-display text-4xl text-base-content">{r.score}</span>
          </div>
          <div className="text-lg font-medium">{r.grade}</div>
          <div className="text-xs text-base-content/60">ATS readiness estimate out of 100</div>
          <div className="mt-2 flex flex-wrap justify-center gap-1.5">
            <span className="badge badge-soft badge-primary">Scored by {r.judge}</span>
            <span className="badge badge-ghost">{r.words} words · {r.pages} page{r.pages === 1 ? "" : "s"}</span>
          </div>
          <div className="mt-3 w-full space-y-3 text-left">
            {r.sections.map((s) => (
              <div key={s.id}>
                <div className="mb-1 flex justify-between text-sm"><span>{s.name}</span><span className="text-base-content/60">{s.score}/{s.max}</span></div>
                <progress className="progress progress-primary w-full" value={s.score} max={s.max} />
              </div>
            ))}
          </div>
        </div></div>

        <div className="flex flex-col gap-4 lg:col-span-3">
          {Object.keys(r.redactions ?? {}).length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5 rounded-box border border-success/40 bg-success/10 p-3 text-sm"><ShieldIcon /> <span className="font-medium">Removed before any AI step:</span>
              {Object.entries(r.redactions).map(([k, v]) => <span key={k} className="badge badge-success badge-soft">{v} {k}{v > 1 && !k.endsWith("s") ? "s" : ""}</span>)}</div>
          )}
          {r.notes.filter((n) => !n.startsWith("Personal details were removed")).map((n, i) => <div key={i} role="alert" className="alert alert-soft alert-info text-sm">{n}</div>)}

          <div className="card border border-base-300 bg-base-100"><div className="card-body gap-2">
            <h2 className="card-title">How to raise your score</h2>
            {!suggestions.length && extra.state !== "loading" && <p className="text-sm text-base-content/70">Nothing urgent to fix. Great work.</p>}
            <div className="flex flex-col gap-2">
              {suggestions.map((s, i) => (
                <div key={i} className="collapse collapse-arrow border border-base-300 bg-base-200/40">
                  <input type="checkbox" defaultChecked={i < 3} />
                  <div className="collapse-title font-medium"><span className={`badge badge-soft badge-sm mr-2 ${PRIORITY_BADGE[s.priority]}`}>{s.priority}</span>{s.title}</div>
                  <div className="collapse-content text-sm">
                    <p>{s.fix}</p>
                    {s.before && (
                      <div className="mt-2 grid gap-2">
                        <div className="rounded-field border border-base-300 bg-base-100 p-2"><div className="text-xs text-base-content/50">Before</div><div className="text-base-content/70 line-through">{s.before}</div></div>
                        <div className="rounded-field border border-primary/40 bg-primary/5 p-2"><div className="text-xs text-primary">After</div><div className="font-medium">{s.after}</div></div>
                      </div>
                    )}
                  </div>
                </div>
              ))}
              {extra.state === "loading" && <div className="flex items-center gap-2 rounded-box border border-dashed border-base-300 p-3 text-sm text-base-content/60"><span className="loading loading-dots loading-sm" /> Finding stronger wording for your weakest bullets. This can take a minute.</div>}
            </div>
          </div></div>

          {r.keywords.provided && (
            <div className="card border border-base-300 bg-base-100"><div className="card-body gap-2">
              <h2 className="card-title">Keywords from the job description</h2>
              <div className="flex flex-wrap gap-1.5">
                {r.keywords.matched.map((k) => <span key={k} className="badge badge-success badge-soft">{k}</span>)}
                {r.keywords.missing.map((k) => <span key={k} className="badge badge-error badge-soft">{k}</span>)}
              </div>
              <p className="text-xs text-base-content/60">Green: found in your resume. Red: missing. Add only the skills you truly have.</p>
            </div></div>
          )}

          <div className="card border border-base-300 bg-base-100"><div className="card-body gap-2">
            <h2 className="card-title">Checklist</h2>
            {[...SECTION_ORDER].map((sec) => (
              <div key={sec}>
                <div className="mb-1 text-sm font-medium text-base-content/70">{SECTION_NAME[sec]}</div>
                <ul className="space-y-1 text-sm">
                  {r.checks.filter((c) => c.section === sec).map((c) => (
                    <li key={c.id} className="flex items-start gap-2">
                      <span className={c.credit >= 1 ? "text-success" : c.credit > 0 ? "text-warning" : "text-error"} aria-label={c.credit >= 1 ? "passed" : "needs work"}>{c.credit >= 1 ? "✓" : c.credit > 0 ? "~" : "✕"}</span>
                      <span>{c.label}{c.detail && <span className="text-base-content/50"> · {c.detail}</span>}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
            <p className="text-xs text-base-content/50">{passed.length} passed, {failed.length} to improve.</p>
          </div></div>

          <p className="text-xs text-base-content/50">This is an estimate. Real applicant tracking systems do not publish how they score, so use it as a guide for clean formatting, clear sections and the right keywords. <ArrowIcon /></p>
        </div>
      </div>
    </div>
  );
}
