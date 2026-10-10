import { useEffect, useState } from "react";
import { api, Voice } from "./api";
import type { Active } from "./App";
import { ShieldIcon, SparkIcon } from "./icons";
import { useMode } from "./mode";

const ROUNDS = [
  { n: 1, t: "Round 1", d: "Screening: introduction, why this company, basics" },
  { n: 2, t: "Round 2", d: "Intermediate: projects, scenarios, debugging" },
  { n: 3, t: "Round 3", d: "Hard: edge cases, trade-offs, scale" },
  { n: 4, t: "Round 4", d: "System design and which method or syntax to use" },
];

export function Setup({ onStart }: { onStart: (a: Active) => void }) {
  const { info } = useMode();
  const online = info?.mode === "online";
  const [voices, setVoices] = useState<Voice[]>([]);
  const [round, setRound] = useState(1);
  const [voice, setVoice] = useState("bf_emma");
  const [jdText, setJdText] = useState("");
  const [jdUrl, setJdUrl] = useState("");
  const [resume, setResume] = useState<File | null>(null);
  const [qFile, setQFile] = useState<File | null>(null);
  const [githubUrl, setGithubUrl] = useState("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => { api.voices().then(setVoices).catch(() => {}); }, []);
  useEffect(() => { const v = voices.find((x) => x.round === round); if (v) setVoice(v.id); }, [round, voices]);

  const step = !jdText.trim() && !jdUrl.trim() ? 1 : !resume ? 2 : 3;

  async function start() {
    setErr("");
    if (!resume) return setErr("Upload your resume (PDF or Word).");
    if (!jdText.trim() && !jdUrl.trim()) return setErr("Paste the job description or add its link.");
    const fd = new FormData();
    fd.append("round_no", String(round)); fd.append("voice", voice);
    fd.append("jd_text", jdText); fd.append("jd_url", jdUrl); fd.append("external_consent", String(consent));
    fd.append("resume", resume); if (qFile) fd.append("questions_file", qFile); if (online) fd.append("github_url", githubUrl);
    setBusy(true);
    try {
      const r = await api.createSession(fd);
      onStart({ id: r.id, voice, total: r.total, first: r.question, role: r.job.role, company: r.job.company });
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <div>
      <h1 className="text-3xl font-semibold md:text-4xl">Set up your interview</h1>
      <p className="mt-1 text-base-content/70">Your voice stays on your computer, and personal details are removed before any AI reads your text.</p>
      <ul className="steps steps-horizontal mt-6 w-full">
        <li className={"step " + (step >= 1 ? "step-primary" : "")}>Job</li>
        <li className={"step " + (step >= 2 ? "step-primary" : "")}>Resume</li>
        <li className={"step " + (step >= 3 ? "step-primary" : "")}>Round and voice</li>
      </ul>

      <div className="mt-6 grid gap-4 lg:grid-cols-2 [&>*]:min-w-0">
        <div className="card border border-base-300 bg-base-100">
          <div className="card-body min-w-0 gap-1">
            <h2 className="card-title">Job and resume</h2>
            <fieldset className="fieldset min-w-0">
              <legend className="fieldset-legend">Link to the job post</legend>
              <input className="input w-full" placeholder="https://company.com/careers/backend-engineer" value={jdUrl} onChange={(e) => setJdUrl(e.target.value)} />
            </fieldset>
            <fieldset className="fieldset min-w-0">
              <legend className="fieldset-legend">Or paste the text</legend>
              <textarea className="textarea h-36 w-full" placeholder="Paste the full job description" value={jdText} onChange={(e) => setJdText(e.target.value)} />
            </fieldset>
            <fieldset className="fieldset min-w-0">
              <legend className="fieldset-legend">Your resume</legend>
              <input type="file" className="file-input w-full" accept=".pdf,.docx,.txt" onChange={(e) => setResume(e.target.files?.[0] ?? null)} />
              <p className="label flex items-start gap-1.5 whitespace-normal [&>svg]:mt-0.5 [&>svg]:shrink-0"><ShieldIcon /> PDF or Word. Your name, contact details, IDs and address are removed before any AI reads it.</p>
            </fieldset>
            <fieldset className="fieldset min-w-0">
              <legend className="fieldset-legend">Your own interview questions <span className="badge badge-ghost badge-sm">optional</span></legend>
              <input type="file" className="file-input w-full" accept=".pdf,.docx,.txt,.md" onChange={(e) => setQFile(e.target.files?.[0] ?? null)} />
            </fieldset>
            <fieldset className="fieldset min-w-0">
              <legend className="fieldset-legend">Your GitHub profile <span className="badge badge-ghost badge-sm">optional, Online mode</span></legend>
              {online ? (
                <>
                  <input className="input w-full" placeholder="github.com/your-username" value={githubUrl} onChange={(e) => setGithubUrl(e.target.value)} />
                  <p className="label flex items-start gap-1.5 whitespace-normal [&>svg]:mt-0.5 [&>svg]:shrink-0"><ShieldIcon /> Only your public repos are read, and only your username is sent to GitHub. Proof points show under answers that match a repo.</p>
                </>
              ) : (
                <p className="label whitespace-normal">GitHub proof points need Online mode, because they contact GitHub. In Offline mode nothing is sent to GitHub. Switch to Online at the top right to use this.</p>
              )}
            </fieldset>
          </div>
        </div>

        <div className="card border border-base-300 bg-base-100">
          <div className="card-body gap-2">
            <h2 className="card-title">Round</h2>
            <div className="grid gap-2">
              {ROUNDS.map((r) => (
                <label key={r.n} className={"flex cursor-pointer items-start gap-3 rounded-box border p-3 transition " + (round === r.n ? "border-primary bg-primary/5" : "border-base-300 hover:border-primary/50")}>
                  <input type="radio" name="round" className="radio radio-primary radio-sm mt-1" checked={round === r.n} onChange={() => setRound(r.n)} />
                  <span><span className="font-medium">{r.t}</span><span className="block text-sm text-base-content/60">{r.d}</span></span>
                </label>
              ))}
            </div>

            <h2 className="card-title mt-3">Interviewer voice <span className="badge badge-ghost badge-sm">UK English</span></h2>
            <div className="grid grid-cols-2 gap-2">
              {voices.map((v) => (
                <button key={v.id} type="button" onClick={() => setVoice(v.id)}
                  className={"rounded-box border p-3 text-left transition " + (voice === v.id ? "border-primary bg-primary/5" : "border-base-300 hover:border-primary/50")}>
                  <span className="font-medium">{v.name}</span><span className="block text-sm text-base-content/60">{v.persona}</span>
                </button>
              ))}
            </div>

            <div className="divider my-1" />
            <label className="flex cursor-pointer items-center justify-between gap-4">
              <span className="text-sm">Look up public company info online <span className="block text-xs text-base-content/60">Only the company name, role and tech names are sent. Never your resume.</span></span>
              <input type="checkbox" className="toggle toggle-primary toggle-sm" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            </label>

            {err && <div role="alert" className="alert alert-error alert-soft mt-2 text-sm">{err}</div>}
            <button className="btn btn-primary mt-3 rounded-full" onClick={start} disabled={busy}>
              {busy ? <><span className="loading loading-dots loading-sm" /> Preparing your interview</> : <><SparkIcon /> Begin interview</>}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
