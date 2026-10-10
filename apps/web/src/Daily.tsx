import { useEffect, useRef, useState } from "react";
import { api, DailyAttempt, DailyItem, DailyLevels, DailyToday, speak, stopSpeaking } from "./api";
import { ArrowIcon, MicIcon, ReplayIcon, StopIcon } from "./icons";

type Step = "hear" | "repeat" | "use" | "result";

/** Daily English for IT: each item is heard, said back, then used in a sentence. Everything is bundled, nothing is generated. */
export function Daily({ voice = "bm_george" }: { voice?: string }) {
  const [today, setToday] = useState<DailyToday | null>(null);
  const [index, setIndex] = useState(0);
  const [step, setStep] = useState<Step>("hear");
  const [heard, setHeard] = useState("");
  const [typed, setTyped] = useState("");
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState<DailyAttempt | null>(null);
  const [sayFeedback, setSayFeedback] = useState<DailyAttempt | null>(null);
  const [err, setErr] = useState("");
  const [finished, setFinished] = useState(0);
  const rec = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);

  const [levels, setLevels] = useState<DailyLevels | null>(null);

  useEffect(() => {
    api.dailyLevels().then(setLevels).catch(() => {});
    api.dailyToday().then(setToday).catch(() => setErr("Couldn't load today's set. Is the app's server running?"));
  }, []);

  async function chooseLevel(level: string) {
    if (levels?.current === level) return;
    stopSpeaking();
    setLevels(await api.setDailyLevel(level));
    setToday(null); setIndex(0); setStep("hear"); setResult(null); setSayFeedback(null); setHeard(""); setTyped(""); setFinished(0);
    setToday(await api.dailyToday());
  }
  useEffect(() => () => stopSpeaking(), []);

  const items: DailyItem[] = today?.items ?? [];
  const item = items[index];
  const total = items.length;

  async function hear() {
    if (!item) return;
    await speak(`${item.text}. ${item.example}`, voice);
  }

  async function toggleMic(forStep: "repeat" | "use") {
    setErr("");
    if (recording) { rec.current?.stop(); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      chunks.current = [];
      mr.ondataavailable = (e) => chunks.current.push(e.data);
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setRecording(false);
        setBusy("Listening back");
        try {
          const t = await api.transcribe(new Blob(chunks.current, { type: "audio/webm" }), "", item?.text ?? "");
          if (forStep === "repeat") setHeard(t.text); else setTyped(t.text);
        } catch (e: any) { setErr(e.message); } finally { setBusy(""); }
      };
      mr.start();
      rec.current = mr;
      setRecording(true);
    } catch { setErr("Couldn't use the microphone. Allow it in your browser, or type your answer."); }
  }

  async function submit(which: "repeat" | "use") {
    if (!item) return;
    const transcript = which === "repeat" ? heard : typed;
    setBusy("Checking");
    setErr("");
    try {
      const r = await api.dailyAttempt({ item_id: item.id, step: which, transcript });
      if (which === "repeat") { setSayFeedback(r); setStep("use"); return; }
      setResult(r);
      setStep("result");
      setFinished((n) => n + 1);
    } catch (e: any) { setErr(e.message); } finally { setBusy(""); }
  }

  function next() {
    stopSpeaking();
    setResult(null); setSayFeedback(null); setHeard(""); setTyped(""); setStep("hear");
    setIndex((i) => i + 1);
  }

  if (err && !today) return <div role="alert" className="alert alert-error alert-soft">{err}</div>;
  if (!today) return <p className="text-base-content/60"><span className="loading loading-dots loading-sm" /> Preparing today's set</p>;
  const levelLabel = levels?.levels.find((l) => l.id === today.level)?.label ?? "";

  const done = today.done_today.length + finished;
  if (!item || index >= total) {
    return (
      <div className="card border border-base-300 bg-base-100 mx-auto max-w-xl"><div className="card-body items-center text-center gap-3">
        <h1 className="text-3xl font-semibold">Today's set is done</h1>
        <p className="text-base-content/70">{finished} new {finished === 1 ? "item" : "items"} practised today. Streak: {today.streak} {today.streak === 1 ? "day" : "days"}.</p>
        <p className="text-sm text-base-content/60">Items you missed come back sooner. Come back tomorrow for the next set.</p>
      </div></div>
    );
  }

  return (
    <div>
      {levels && (
        <div className="mb-4 grid gap-2 sm:grid-cols-3" role="radiogroup" aria-label="Level">
          {levels.levels.map((lv) => (
            <button key={lv.id} role="radio" aria-checked={levels.current === lv.id} onClick={() => chooseLevel(lv.id)}
              className={"rounded-box border p-3 text-left transition " + (levels.current === lv.id ? "border-primary bg-primary/5" : "border-base-300 hover:border-primary/50")}>
              <div className="flex items-center justify-between"><span className="font-medium">{lv.label}</span><span className="text-xs text-base-content/60">{lv.learned}/{lv.total} learned</span></div>
              <span className="mt-1 block text-xs text-base-content/60">{lv.for}</span>
            </button>
          ))}
        </div>
      )}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div><h1 className="text-3xl font-semibold md:text-4xl">Daily English for IT</h1>
          <p className="text-sm text-base-content/60">{levelLabel} · Item {index + 1} of {total} · {today.streak} day streak</p></div>
        <progress className="progress progress-primary w-40 sm:w-64" value={index} max={total} />
      </div>

      <div className="card border border-base-300 bg-base-100"><div className="card-body gap-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="badge badge-soft badge-primary">{item.kind}</span>
          {step === "hear" && <span className="text-sm text-base-content/60">1. Hear it</span>}
          {step === "repeat" && <span className="text-sm text-base-content/60">2. Say it back</span>}
          {step === "use" && <span className="text-sm text-base-content/60">3. Use it in a sentence</span>}
        </div>
        <div className="font-display text-3xl font-semibold text-primary">{item.text}</div>
        <p className="text-base-content/80">{item.meaning}</p>
        {step !== "use" && step !== "result" && <p className="rounded-box bg-base-200 p-3 text-sm italic">“{item.example}”</p>}

        {step === "hear" && (
          <div className="flex flex-wrap gap-2">
            <button className="btn btn-outline btn-primary rounded-full" onClick={hear}><ReplayIcon /> Hear it</button>
            <button className="btn btn-primary rounded-full" onClick={() => { stopSpeaking(); setStep("repeat"); }}>Next: say it back <ArrowIcon /></button>
          </div>
        )}

        {step === "repeat" && (
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-3">
              <button className={"btn btn-circle btn-primary " + (recording ? "btn-error" : "")} onClick={() => toggleMic("repeat")} aria-label={recording ? "Stop" : "Say it"}>
                {recording ? <StopIcon size={22} /> : <MicIcon size={22} />}
              </button>
              <span className="text-sm text-base-content/60">{recording ? "Listening. Press again to finish." : busy || "Press the mic and say the word or phrase."}</span>
            </div>
            {heard && <p className="text-sm">I heard: <b>{heard}</b></p>}
            <div className="flex flex-wrap gap-2">
              <button className="btn btn-primary rounded-full" disabled={!heard || !!busy} onClick={() => submit("repeat")}>Check my saying</button>
              <button className="btn btn-ghost rounded-full" onClick={() => { stopSpeaking(); setStep("use"); }}>Skip</button>
            </div>
          </div>
        )}

        {step === "use" && (
          <div className="flex flex-col gap-3">
            {sayFeedback && <div className={"alert alert-soft text-sm " + (sayFeedback.grade === "good" ? "alert-success" : "alert-warning")}>{sayFeedback.feedback}</div>}
            <p className="font-medium">{item.prompt}</p>
            <textarea className="textarea h-24 w-full" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Type one sentence, or use the mic" />
            <div className="flex flex-wrap items-center gap-2">
              <button className={"btn btn-sm rounded-full " + (recording ? "btn-error" : "btn-outline")} onClick={() => toggleMic("use")}>
                {recording ? <><StopIcon size={16} /> Stop</> : <><MicIcon size={16} /> Speak it</>}
              </button>
              <button className="btn btn-primary rounded-full" disabled={!typed.trim() || !!busy} onClick={() => submit("use")}>
                {busy ? <span className="loading loading-dots loading-sm" /> : <>Check my sentence <ArrowIcon /></>}
              </button>
            </div>
          </div>
        )}

        {step === "result" && result && (
          <div className="flex flex-col gap-3">
            <div className={"alert alert-soft " + (result.grade === "good" ? "alert-success" : "alert-warning")}>{result.feedback}</div>
            {result.better && <div className="rounded-box border border-primary/40 bg-primary/5 p-3 text-sm"><div className="mb-1 font-medium text-primary">A stronger way to say it</div>{result.better}</div>}
            <p className="text-xs text-base-content/60">{result.next_review_days ? `You'll see this again in ${result.next_review_days} day${result.next_review_days === 1 ? "" : "s"}.` : ""}</p>
            <button className="btn btn-primary rounded-full self-start" onClick={next}>{index + 1 < total ? "Next item" : "Finish"} <ArrowIcon /></button>
          </div>
        )}

        {err && step !== "result" && <div role="alert" className="alert alert-error alert-soft text-sm">{err}</div>}
      </div></div>
    </div>
  );
}
