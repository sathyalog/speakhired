import { useEffect, useRef, useState } from "react";
import { api, speak, stopSpeaking, voiceSpeed, AnswerResult, LangAudio, LangReport, ProofPoint, Question } from "./api";
import type { Active } from "./App";
import { ArrowIcon, MicIcon, ReplayIcon, StopIcon } from "./icons";

const BARS = [6, 12, 20, 10, 24, 16, 8, 22, 14, 26, 10, 18, 7, 15, 21, 9];

export function Session({ active, onFinish }: { active: Active; onFinish: () => void }) {
  const [q, setQ] = useState<Question>(active.first);
  const [n, setN] = useState(1);
  const [recording, setRecording] = useState(false);
  const [talking, setTalking] = useState(false);
  const [transcript, setTranscript] = useState(active.first.hint ?? "");
  const [duration, setDuration] = useState(0);
  const [result, setResult] = useState<AnswerResult | null>(null);
  const [lang, setLang] = useState<LangReport | null>(null);
  const [polish, setPolish] = useState<"idle" | "loading" | "error">("idle");
  const [fixes, setFixes] = useState<{ heard: string; fixed: string }[]>([]);
  const [speed, setSpeed] = useState(voiceSpeed.get());
  const [audioLang, setAudioLang] = useState<LangAudio | null>(null);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const rec = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const started = useRef(0);
  const male = active.voice.includes("m_");

  const ask = async (text: string) => { setTalking(true); try { await speak(text, active.voice); } finally { setTalking(false); } };
  useEffect(() => { void ask(q.text); /* eslint-disable-next-line */ }, [q.id]);

  async function toggleMic() {
    setErr("");
    if (recording) { rec.current?.stop(); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      chunks.current = []; started.current = Date.now();
      mr.ondataavailable = (e) => chunks.current.push(e.data);
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop()); setRecording(false);
        setBusy("Transcribing");
        try {
          const t = await api.transcribe(new Blob(chunks.current, { type: "audio/webm" }), active.id);
          setFixes(t.corrections);
          setTranscript(t.text); setAudioLang(t.language); setLang(t.report); setDuration(t.duration || (Date.now() - started.current) / 1000);
        } catch (e: any) { setErr(e.message + " You can type your answer instead."); } finally { setBusy(""); }
      };
      mr.start(); rec.current = mr; setRecording(true);
    } catch { setErr("Couldn't access the microphone. Allow it in your browser, or type your answer."); }
  }

  async function submit() {
    if (!transcript.trim()) return setErr("Say or type an answer first.");
    setBusy("Evaluating"); setErr("");
    try {
      const r = await api.answer(active.id, transcript, duration || transcript.split(/\s+/).length / 2.2, audioLang);
      setResult(r); void ask(r.feedback.spoken_summary || r.ack);
      void fetchPolish(r.answer_index);
    } catch (e: any) { setErr(e.message); } finally { setBusy(""); }
  }

  // The stronger phrasing and the complete answer take longer to write, so they arrive after the quick feedback.
  function fetchPolish(index: number) {
    setPolish("loading");
    api.polish(active.id, index)
      .then((p) => { setResult((cur) => (cur && cur.answer_index === index ? { ...cur, feedback: { ...cur.feedback, ...p } } : cur)); setPolish("idle"); })
      .catch(() => setPolish("error"));
  }

  function next() {
    if (!result) return;
    if (result.done || !result.next_question) return onFinish();
    stopSpeaking(); setFixes([]); setPolish("idle"); setQ(result.next_question); setN(n + 1); setTranscript(result.next_question.hint ?? ""); setResult(null); setDuration(0); setLang(null); setAudioLang(null);
  }

  useEffect(() => {
    if (result) return;
    if (!transcript.trim()) { setLang(null); return; }
    const t = setTimeout(() => { api.checkLanguage(transcript, audioLang).then(setLang).catch(() => {}); }, 400);
    return () => clearTimeout(t);
  }, [transcript, audioLang, result]);

  function reRecord() { setTranscript(""); setAudioLang(null); setLang(null); setErr(""); void toggleMic(); }
  const blocked = lang?.status === "non_english";

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.code === "Space" && e.target === document.body && !result) { e.preventDefault(); void toggleMic(); } };
    window.addEventListener("keydown", h); return () => window.removeEventListener("keydown", h);
  });

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-sm text-base-content/60">{active.role || "Interview"}{active.company ? ` at ${active.company}` : ""}</div>
          <div className="flex items-center gap-2 text-sm font-medium">Question {n} of {active.total}<span className="badge badge-soft badge-primary badge-sm">English only</span></div>
        </div>
        <progress className="progress progress-primary w-40 sm:w-64" value={n - (result ? 0 : 1)} max={active.total} />
      </div>

      <div className="grid gap-4 lg:grid-cols-5">
        <div className="card border border-base-300 bg-base-100 lg:col-span-3">
          <div className="card-body gap-4">
            <div className="chat chat-start">
              <div className="chat-image avatar avatar-placeholder">
                <div className="w-10 rounded-full bg-primary text-primary-content"><span>{male ? "M" : "F"}</span></div>
              </div>
              <div className="chat-header text-xs text-base-content/60">Interviewer</div>
              <div className="chat-bubble chat-bubble-primary text-base leading-relaxed">{q.text}</div>
            </div>

            {result && transcript && (
              <div className="chat chat-end">
                <div className="chat-header text-xs text-base-content/60">You</div>
                <div className="chat-bubble bg-base-300 text-base-content">{markText(transcript, langItems(result.language.words))}</div>
              </div>
            )}

            {result && <AnswerToGive fb={result.feedback} voice={active.voice} polish={polish} onRetry={() => fetchPolish(result.answer_index)} />}
            {result && result.feedback.proof_point && <ProofCard pp={result.feedback.proof_point} />}

            {!result && (
              <>
                <div className="flex items-end justify-center gap-[3px]" style={{ height: 30 }} aria-hidden>
                  <div className="wave flex items-end gap-[3px]">{BARS.map((h, i) => <span key={i} style={{ height: talking || recording ? h : 4 }} />)}</div>
                </div>
                <div className="flex flex-col items-center gap-2">
                  <button className={"btn btn-circle btn-primary btn-xl " + (recording ? "btn-error mic-rec" : "")} onClick={toggleMic} aria-label={recording ? "Stop recording" : "Start answering"}>
                    {recording ? <StopIcon size={26} /> : <MicIcon size={28} />}
                  </button>
                  <span className="text-sm text-base-content/60">{recording ? "Listening. Press Space or the button to finish." : "Press Space or the button to answer"}</span>
                  <div className="flex flex-wrap items-center justify-center gap-2">
                    <button className="btn btn-ghost btn-sm gap-1" onClick={() => ask(q.text)}><ReplayIcon /> Repeat question</button>
                    <select className="select select-xs w-auto" aria-label="Voice speed" value={speed} onChange={(e) => { const v = Number(e.target.value); voiceSpeed.set(v); setSpeed(v); }}>
                      {[[0.8, "Slow"], [0.9, "Slower"], [0.95, "Clear"], [1.05, "Normal"], [1.2, "Fast"]].map(([v, l]) => <option key={v} value={v}>Voice: {l}</option>)}
                    </select>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>

        <div className="card border border-base-300 bg-base-100 lg:col-span-2">
          <div className="card-body gap-3">
            {!result ? (
              <>
                {lang && lang.status !== "english" && <LanguageAlert lang={lang} onRerecord={reRecord} />}
                <fieldset className="fieldset">
                  <legend className="fieldset-legend">Your answer</legend>
                  <textarea className="textarea h-44 w-full" value={transcript} onChange={(e) => { setTranscript(e.target.value); setAudioLang(null); }}
                    placeholder="Your words appear here after you speak. Fix anything misheard, or just type." />
                </fieldset>
                {fixes.length > 0 && <div role="status" className="alert alert-soft alert-info text-sm">Fixed technical terms: {fixes.map((f) => `${f.heard} → ${f.fixed}`).join(", ")}</div>}
                {err && <div role="alert" className="alert alert-error alert-soft text-sm">{err}</div>}
                <button className="btn btn-primary rounded-full" onClick={submit} disabled={!!busy || blocked} title={blocked ? "Please answer in English first" : undefined}>
                  {busy ? <><span className="loading loading-dots loading-sm" /> {busy}</> : <>Get feedback <ArrowIcon /></>}
                </button>
              </>
            ) : (
              <Feedback r={result} transcript={transcript} onNext={next} last={result.done} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

type Mark = { text: string; tip: string; cls: "fix" | "lang" };
const langItems = (words: { word: string; english: string[] }[]): Mark[] =>
  words.map((w) => ({ text: w.word, cls: "lang", tip: w.english.length ? `Say in English: ${w.english.join(" / ")}` : "Please say this in English" }));

function markText(text: string, items: Mark[]) {
  let parts: (string | JSX.Element)[] = [text];
  items.forEach((it, i) => {
    parts = parts.flatMap((part) => typeof part !== "string" ? [part] : part.split(it.text).flatMap((seg, k, a) =>
      k < a.length - 1 ? [seg, <span key={`${i}-${k}`} className="tooltip" data-tip={it.tip}><mark className={it.cls}>{it.text}</mark></span>] : [seg]));
  });
  return parts;
}

function LanguageAlert({ lang, onRerecord }: { lang: LangReport; onRerecord: () => void }) {
  const hard = lang.status === "non_english";
  return (
    <div role="alert" className={"alert border text-base-content " + (hard ? "border-warning bg-warning/15" : "border-info/50 bg-info/10")}>
      <div className="flex flex-col gap-2">
        <div className="font-medium">
          {hard ? `We heard ${lang.language_name}. This practice is English only, so please answer in English.` : "A few words were not English. Try saying them in English."}
        </div>
        {lang.words.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {lang.words.slice(0, 8).map((w, i) => (
              <span key={i} className="badge badge-warning" title={w.english.join(" / ")}>
                {w.word}{w.english.length ? ` → ${w.english[0]}` : ""}
              </span>
            ))}
          </div>
        )}
        {hard && <div><button className="btn btn-sm btn-warning rounded-full" onClick={onRerecord}>Re-record in English</button></div>}
      </div>
    </div>
  );
}

function Feedback({ r, transcript, onNext, last }: { r: AnswerResult; transcript: string; onNext: () => void; last: boolean }) {
  const fb = r.feedback;
  const marked = markText(transcript, [
    ...fb.corrections.map((c): Mark => ({ text: c.original, tip: c.reason, cls: "fix" })),
    ...langItems(r.language.words),
  ]);
  const corrected = fb.corrected_answer ?? "";
  const unchanged = !corrected || corrected.trim() === transcript.trim();

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-1.5">
        {Object.entries(r.evaluation.scores).map(([k, v]) => (
          <span key={k} className={"badge badge-soft " + (v >= 4 ? "badge-success" : v >= 3 ? "badge-primary" : "badge-warning")}>{k} {v}/5</span>
        ))}
        <span className="badge badge-ghost">{r.delivery.wpm} words/min</span>
        {Object.entries(r.delivery.fillers).map(([k, v]) => <span key={k} className="badge badge-ghost">“{k}” ×{v}</span>)}
      </div>

      <div className="collapse collapse-arrow border border-base-300 bg-base-200/50">
        <input type="checkbox" defaultChecked /><div className="collapse-title font-medium">What you said</div>
        <div className="collapse-content text-sm"><p>{marked}</p>
          {fb.corrections.map((c, i) => (
            <p key={i} className="mt-2 text-base-content/70"><b>{c.original}</b> → <span className="text-success font-medium">{c.fix}</span>. {c.reason}</p>
          ))}
        </div>
      </div>

      <div className="rounded-box border border-success/40 bg-success/5 p-4">
        <div className="mb-1 text-sm font-medium text-success">Your answer, corrected</div>
        <p className="text-sm leading-relaxed">{unchanged ? <span className="text-base-content/60">No grammar fixes needed. Your wording was fine.</span> : corrected}</p>
      </div>

      {fb.missing_outline.length > 0 && (
        <div className="rounded-box border border-warning/50 bg-warning/10 p-4">
          <div className="mb-1 text-sm font-medium">Important points to add</div>
          <ul className="list-disc space-y-0.5 pl-5 text-sm">{fb.missing_outline.map((m, i) => <li key={i}>{m}</li>)}</ul>
        </div>
      )}

      {fb.web_check && <WebVerdict w={fb.web_check} />}

      {fb.swaps && fb.swaps.length > 0 && (
        <div className="collapse collapse-arrow border border-base-300 bg-base-200/50">
          <input type="checkbox" /><div className="collapse-title font-medium">Instead of this, say this</div>
          <div className="collapse-content flex flex-col gap-2 text-sm">
            {fb.swaps.map((x, i) => (
              <div key={i} className="rounded-box border border-base-300 bg-base-100 p-3">
                <div className="text-base-content/50 line-through">{x.instead_of}</div>
                <div className="mt-1 font-medium text-primary">{x.say}</div>
                {x.why && <div className="mt-1 text-xs text-base-content/60">{x.why}</div>}
              </div>
            ))}
          </div>
        </div>
      )}

      {fb.vocabulary_tips.length > 0 && (
        <div className="collapse collapse-arrow border border-base-300 bg-base-200/50">
          <input type="checkbox" /><div className="collapse-title font-medium">Vocabulary to use</div>
          <div className="collapse-content text-sm"><ul className="list-disc pl-5">{fb.vocabulary_tips.map((m, i) => <li key={i}>{m}</li>)}</ul></div>
        </div>
      )}

      <div className="text-xs text-base-content/50">Scored by: {r.evaluation.judge}</div>
      <button className="btn btn-primary rounded-full" onClick={onNext}>{last ? "See my report" : "Next question"} <ArrowIcon /></button>
    </div>
  );
}

/** The full answer to give the interviewer: sits right under the candidate's own answer, and can be listened to. */
function AnswerToGive({ fb, voice, polish, onRetry }: { fb: AnswerResult["feedback"]; voice: string; polish: "idle" | "loading" | "error"; onRetry: () => void }) {
  const [state, setState] = useState<"idle" | "loading" | "playing">("idle");
  const parts = fb.impressive
    ? ([["Answer first", fb.impressive.answer_first], ["Example", fb.impressive.example], ["Trade-off", fb.impressive.trade_off], ["Close", fb.impressive.close]] as const).filter(([, t]) => t)
    : [];
  const model = fb.better_version || parts.map(([, t]) => t).join(" ");
  useEffect(() => () => stopSpeaking(), []);          // stop reading when this answer goes away
  if (!model) {
    if (polish === "loading") return (
      <div className="rounded-box border border-primary/30 bg-primary/5 p-4" aria-live="polite">
        <div className="mb-2 flex items-center gap-2 text-sm font-medium text-primary"><span className="loading loading-dots loading-sm" /> Writing the answer you can give</div>
        <div className="skeleton h-3 w-full" /><div className="skeleton mt-2 h-3 w-5/6" /><div className="skeleton mt-2 h-3 w-2/3" />
        <p className="mt-3 text-xs text-base-content/60">Your corrected answer and the points to add are ready now. This part takes a little longer on a small computer.</p>
      </div>
    );
    if (polish === "error") return (
      <div role="alert" className="alert alert-soft alert-warning text-sm"><span>Couldn't write the full answer this time.</span><button className="btn btn-sm rounded-full" onClick={onRetry}>Try again</button></div>
    );
    return null;
  }

  async function hear() {
    if (state !== "idle") { stopSpeaking(); setState("idle"); return; }
    setState("loading");
    try { await speak(model, voice, () => setState("playing")); } finally { setState("idle"); }
  }

  return (
    <div className="rounded-box border border-primary/40 bg-primary/5 p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-medium text-primary">The answer to give the interviewer</div>
        <button className="btn btn-outline btn-primary btn-xs min-w-24 rounded-full" onClick={hear} aria-live="polite">
          {state === "loading" ? <><span className="loading loading-dots loading-xs" /> Preparing</> : state === "playing" ? "Stop" : "Hear it"}
        </button>
      </div>
      <p className="text-sm leading-relaxed">{model}</p>
      {parts.length > 1 && (
        <div className="mt-3 flex flex-col gap-1.5 border-t border-primary/20 pt-3 text-xs text-base-content/70">
          {parts.map(([label, text]) => <div key={label}><span className="badge badge-primary badge-soft badge-sm mr-2">{label}</span>{text}</div>)}
        </div>
      )}
    </div>
  );
}

/** Shown only when one of the candidate's own public repos already does what the question asks. */
function ProofCard({ pp }: { pp: ProofPoint }) {
  return (
    <div className="rounded-box border border-success/40 bg-success/5 p-4">
      <div className="mb-1 text-sm font-medium text-success">Proof point</div>
      <p className="text-sm leading-relaxed">You already worked on this in <a className="link link-hover font-medium" href={pp.url} target="_blank" rel="noreferrer noopener">{pp.repo}</a>. {pp.claim}</p>
      {pp.summary && <p className="mt-2 text-xs text-base-content/70"><b>Repo summary:</b> {pp.summary}</p>}
    </div>
  );
}

function WebVerdict({ w }: { w: NonNullable<AnswerResult["feedback"]["web_check"]> }) {
  const tone = w.verdict === "sufficient" ? "badge-success" : w.verdict === "partial" ? "badge-warning" : "badge-error";
  const label = w.verdict === "sufficient" ? "Your answer covers it" : w.verdict === "partial" ? "Good start, add a little more" : "Needs more substance";
  return (
    <div className="collapse collapse-arrow border border-base-300 bg-base-200/50">
      <input type="checkbox" defaultChecked />
      <div className="collapse-title font-medium">Web check <span className={"badge badge-soft badge-sm ml-2 " + tone}>{label}</span></div>
      <div className="collapse-content flex flex-col gap-2 text-sm">
        {w.missing_points.length > 0 && <div><div className="font-medium">Important points to add</div><ul className="list-disc pl-5">{w.missing_points.map((m, i) => <li key={i}>{m}</li>)}</ul></div>}
        {w.fact_flags.filter((f) => f.status !== "supported").map((f, i) => (
          <div key={i} className="text-base-content/80"><span className={"badge badge-soft badge-sm mr-2 " + (f.status === "wrong" ? "badge-error" : "badge-warning")}>{f.status}</span>{f.claim}{f.note ? `. ${f.note}` : ""}</div>
        ))}
        {w.sources.length > 0 && (
          <div className="text-xs text-base-content/60">Sources (from the AI search tool, open with care):{" "}
            {w.sources.map((s, i) => <a key={i} className="link mr-2" href={s.url} target="_blank" rel="noreferrer noopener">{s.title || s.url}</a>)}
          </div>
        )}
        {!w.answer_included && <div className="text-xs text-base-content/50">Only the question was sent to the web checker, not your answer.</div>}
      </div>
    </div>
  );
}
