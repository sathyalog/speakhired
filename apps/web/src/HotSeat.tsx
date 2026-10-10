import { useEffect, useState } from "react";
import { api, Voice } from "./api";
import type { Active } from "./App";
import { SparkIcon } from "./icons";

type Item = { text: string; hint: string };
const EMPTY: Item = { text: "", hint: "" };

export function HotSeat({ onStart }: { onStart: (a: Active) => void }) {
  const [voices, setVoices] = useState<Voice[]>([]);
  const [voice, setVoice] = useState("bm_george");
  const [items, setItems] = useState<Item[]>([{ ...EMPTY }]);
  const [web, setWeb] = useState(false);
  const [withAnswer, setWithAnswer] = useState(false);
  const [preview, setPreview] = useState("");
  const [webReady, setWebReady] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => { api.voices().then(setVoices).catch(() => {}); }, []);
  useEffect(() => { api.health().then((h) => setWebReady(!!h.external_lookup)).catch(() => setWebReady(false)); }, []);

  const set = (i: number, patch: Partial<Item>) => setItems((xs) => xs.map((x, k) => (k === i ? { ...x, ...patch } : x)));
  const first = items[0];

  useEffect(() => {
    if (!web || !first.text.trim()) { setPreview(""); return; }
    const t = setTimeout(() => {
      api.quickPreview(first.text, first.hint, withAnswer).then((r) => setPreview(r.prompt)).catch(() => setPreview(""));
    }, 400);
    return () => clearTimeout(t);
  }, [web, withAnswer, first.text, first.hint]);

  async function start() {
    setErr("");
    const qs = items.map((x) => ({ text: x.text.trim(), hint: x.hint.trim() })).filter((x) => x.text);
    if (!qs.length) return setErr("Paste at least one question.");
    setBusy(true);
    try {
      const r = await api.createQuick({ questions: qs, voice, web_check: web, include_answer: web && withAnswer });
      onStart({ id: r.id, voice, total: r.total, first: r.question, role: "Hot Seat", company: "" });
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <div>
      <h1 className="text-3xl font-semibold md:text-4xl">Hot Seat</h1>
      <p className="mt-1 max-w-2xl text-base-content/70">Paste one to three questions you were asked in an interview or found online. You answer out loud, then see how to say it better.</p>

      <div className="mt-6 grid gap-4 lg:grid-cols-5">
        <div className="card border border-base-300 bg-base-100 lg:col-span-3">
          <div className="card-body gap-3">
            <h2 className="card-title">Your questions</h2>
            {items.map((it, i) => (
              <div key={i} className="rounded-box border border-base-300 bg-base-200/40 p-3">
                <fieldset className="fieldset">
                  <legend className="fieldset-legend">Question {i + 1}</legend>
                  <textarea className="textarea h-20 w-full" maxLength={400} placeholder="For example: How would you handle duplicate messages in a Kafka consumer?"
                    value={it.text} onChange={(e) => set(i, { text: e.target.value })} />
                </fieldset>
                <fieldset className="fieldset">
                  <legend className="fieldset-legend">Your idea or rough answer <span className="badge badge-ghost badge-sm">optional</span></legend>
                  <textarea className="textarea h-16 w-full" placeholder="A few words are enough. It appears in your answer box and helps the coach understand your thinking."
                    value={it.hint} onChange={(e) => set(i, { hint: e.target.value })} />
                </fieldset>
                {items.length > 1 && <button className="btn btn-ghost btn-xs" onClick={() => setItems((xs) => xs.filter((_, k) => k !== i))}>Remove</button>}
              </div>
            ))}
            {items.length < 3 && <button className="btn btn-outline btn-sm self-start rounded-full" onClick={() => setItems((xs) => [...xs, { ...EMPTY }])}>Add another question</button>}
          </div>
        </div>

        <div className="card border border-base-300 bg-base-100 lg:col-span-2">
          <div className="card-body gap-2">
            <h2 className="card-title">Interviewer voice <span className="badge badge-ghost badge-sm">UK English</span></h2>
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
              <span className="text-sm">Check my answer on the web
                <span className="block text-xs text-base-content/60">Uses your own API key. Sends the question to the web checker.</span></span>
              <input type="checkbox" className="toggle toggle-primary toggle-sm" checked={web} onChange={(e) => setWeb(e.target.checked)} disabled={webReady === false} />
            </label>
            {webReady === false && <div className="alert alert-soft text-xs">No API key found. Add <code>EXTERNAL_API_KEY</code> to <code>.env</code> to turn this on. Everything else works without it.</div>}
            {web && (
              <>
                <label className="flex cursor-pointer items-center justify-between gap-4">
                  <span className="text-sm">Include my answer in the web check
                    <span className="block text-xs text-base-content/60">Better advice, but your answer text is sent too. Emails, phone numbers and links are removed first. Never your resume.</span></span>
                  <input type="checkbox" className="toggle toggle-primary toggle-sm" checked={withAnswer} onChange={(e) => setWithAnswer(e.target.checked)} />
                </label>
                {preview && (
                  <div className="collapse collapse-arrow border border-base-300 bg-base-200/50">
                    <input type="checkbox" /><div className="collapse-title text-sm font-medium">What will be sent</div>
                    <div className="collapse-content"><pre className="whitespace-pre-wrap text-xs">{preview}</pre></div>
                  </div>
                )}
              </>
            )}

            {err && <div role="alert" className="alert alert-error alert-soft mt-2 text-sm">{err}</div>}
            <button className="btn btn-primary mt-3 rounded-full" onClick={start} disabled={busy}>
              {busy ? <><span className="loading loading-dots loading-sm" /> Getting ready</> : <><SparkIcon /> Take the hot seat</>}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
