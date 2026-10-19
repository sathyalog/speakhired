import { lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import "@excalidraw/excalidraw/index.css";
import { api, type SystemDesignQuestion, type SystemDesignReview } from "./api";
import { ArrowIcon } from "./icons";

// Excalidraw loads its fonts from this folder instead of a CDN, so the whiteboard works offline.
// scripts/copy-excalidraw-assets.mjs copies them here after npm install.
(window as unknown as { EXCALIDRAW_ASSET_PATH: string }).EXCALIDRAW_ASSET_PATH = "/excalidraw-assets/";

const Excalidraw = lazy(() => import("@excalidraw/excalidraw").then((m) => ({ default: m.Excalidraw })));
type SceneApi = { getSceneElements: () => readonly unknown[] };
type Track = "regular" | "ai";

const TRACKS: Record<Track, { title: string; cta: string; body: string }> = {
  ai: {
    title: "AI system design",
    cta: "Try AI system design",
    body: "Design systems built around LLMs: retrieval, assistants, review bots and model gateways. Costs, grounding and failover matter here.",
  },
  regular: {
    title: "Regular system design",
    cta: "Try regular system design",
    body: "Classic backend design: short links, rate limits, messaging. Scale, storage, caching and failure handling matter here.",
  },
};
const LEVEL_BADGE = ["", "badge-success", "badge-warning", "badge-error"];

const DIMENSION_LABEL: Record<string, string> = {
  requirements: "Requirements covered",
  components: "Right components",
  connections: "Connections and data flow",
  correctness: "Correctness",
  tradeoffs: "Trade-offs and scale",
};

// Step 1: pick a track. Step 2: pick a question from that track, easiest first. Step 3: draw and submit.
export function SystemDesign() {
  const [track, setTrack] = useState<Track | null>(null);
  const [active, setActive] = useState<SystemDesignQuestion | null>(null);

  if (!track) return <TrackChooser onPick={setTrack} />;
  if (!active) return <QuestionList track={track} onBack={() => setTrack(null)} onPick={setActive} />;
  return <Whiteboard key={active.id} question={active} onBack={() => setActive(null)} />;
}

function TrackChooser({ onPick }: { onPick: (t: Track) => void }) {
  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-3xl font-semibold">System design whiteboard</h1>
        <p className="text-base-content/70">Which kind of design do you want to practise?</p>
      </header>
      <section className="grid gap-4 md:grid-cols-2">
        {(["ai", "regular"] as Track[]).map((t) => (
          <div key={t} className="card border border-base-300 bg-base-100">
            <div className="card-body">
              <h2 className="card-title text-xl">{TRACKS[t].title}</h2>
              <p className="text-base-content/70">{TRACKS[t].body}</p>
              <div className="card-actions mt-2">
                <button className="btn btn-primary btn-outline rounded-full" onClick={() => onPick(t)}>{TRACKS[t].cta} <ArrowIcon /></button>
              </div>
            </div>
          </div>
        ))}
      </section>
    </div>
  );
}

function QuestionList({ track, onBack, onPick }: { track: Track; onBack: () => void; onPick: (q: SystemDesignQuestion) => void }) {
  const [questions, setQuestions] = useState<SystemDesignQuestion[] | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.systemDesignQuestions(track)
      .then(setQuestions)
      .catch((e) => setErr(e instanceof Error ? e.message : "Could not load the questions."));
  }, [track]);

  return (
    <div className="flex flex-col gap-6">
      <header>
        <button className="btn btn-ghost btn-sm -ml-2 mb-2" onClick={onBack}>Choose another kind</button>
        <h1 className="text-3xl font-semibold">{TRACKS[track].title}</h1>
        <p className="text-base-content/70">Start with the easier questions. Each one comes with clear requirements and scale numbers.</p>
      </header>
      {err && <p role="alert" className="text-error">{err}</p>}
      {!questions && !err && <p className="text-base-content/70">Loading questions...</p>}
      <section className="grid gap-4">
        {questions?.map((q) => (
          <div key={q.id} className="card border border-base-300 bg-base-100">
            <div className="card-body flex-row flex-wrap items-center justify-between gap-4">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`badge badge-soft ${LEVEL_BADGE[q.level]}`}>{q.level_label}</span>
                  <h2 className="font-semibold">{q.title}</h2>
                </div>
                <p className="mt-1 text-sm text-base-content/70">{q.prompt}</p>
                <p className="mt-1 text-xs text-base-content/50">{q.source}</p>
              </div>
              <button className="btn btn-primary btn-outline rounded-full" onClick={() => onPick(q)}>Open</button>
            </div>
          </div>
        ))}
      </section>
    </div>
  );
}

function Whiteboard({ question: q, onBack }: { question: SystemDesignQuestion; onBack: () => void }) {
  const [scene, setScene] = useState<SceneApi | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [result, setResult] = useState<SystemDesignReview | null>(null);

  async function submit() {
    if (!scene) return;
    setBusy(true);
    setErr("");
    try {
      setResult(await api.reviewSystemDesign(q.id, scene.getSceneElements()));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "The review failed. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <header>
        <button className="btn btn-ghost btn-sm -ml-2 mb-2" onClick={onBack}>Back to {TRACKS[q.track].title} questions</button>
        <div className="flex flex-wrap items-center gap-2">
          <span className={`badge badge-soft ${LEVEL_BADGE[q.level]}`}>{q.level_label}</span>
          <span className="text-sm text-base-content/50">{TRACKS[q.track].title}</span>
        </div>
      </header>

      <section className="card border border-base-300 bg-base-100">
        <div className="card-body gap-3">
          <h2 className="card-title text-xl">{q.title}</h2>
          <p>{q.prompt}</p>
          <div className="grid gap-4 md:grid-cols-3">
            <div>
              <h3 className="mb-1 text-sm font-medium uppercase tracking-wide text-base-content/50">Functional</h3>
              <ul className="list-disc space-y-1 pl-5 text-sm">{q.functional.map((r) => <li key={r}>{r}</li>)}</ul>
            </div>
            <div>
              <h3 className="mb-1 text-sm font-medium uppercase tracking-wide text-base-content/50">Non-functional</h3>
              <ul className="list-disc space-y-1 pl-5 text-sm">{q.non_functional.map((r) => <li key={r}>{r}</li>)}</ul>
            </div>
            <div>
              <h3 className="mb-1 text-sm font-medium uppercase tracking-wide text-base-content/50">Scale</h3>
              <ul className="list-disc space-y-1 pl-5 text-sm">{q.scale.map((r) => <li key={r}>{r}</li>)}</ul>
            </div>
          </div>
        </div>
      </section>

      <div className="h-[70vh] min-h-[420px] overflow-hidden rounded-box border border-base-300 bg-base-100">
        <Suspense fallback={<p className="p-6 text-base-content/70">Opening the whiteboard...</p>}>
          <Excalidraw excalidrawAPI={(a) => setScene(a)} />
        </Suspense>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button className="btn btn-primary rounded-full px-8" onClick={submit} disabled={busy}>
          {busy ? <span className="loading loading-spinner loading-sm" /> : null}
          {busy ? "Reviewing your design..." : "Submit for review"}
        </button>
        {err && <p role="alert" className="text-error">{err}</p>}
      </div>

      {result && <Review r={result} />}
    </div>
  );
}

function Review({ r }: { r: SystemDesignReview }) {
  const { graph } = r;
  return (
    <section className="card border border-base-300 bg-base-100" aria-live="polite">
      <div className="card-body gap-5">
        <div className="flex flex-wrap items-end gap-4">
          <div>
            <p className="text-sm uppercase tracking-wide text-base-content/50">Score</p>
            <p className="text-5xl font-semibold text-primary">{r.score}<span className="text-2xl text-base-content/50">/100</span></p>
          </div>
          <p className="max-w-xl text-base-content/80">{r.summary}</p>
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          {Object.entries(r.dimensions).map(([key, value]) => (
            <div key={key}>
              <div className="flex justify-between text-sm"><span>{DIMENSION_LABEL[key] ?? key}</span><span>{value}/10</span></div>
              <progress className="progress progress-primary w-full" value={value} max={10} />
            </div>
          ))}
        </div>

        <Block title={`Component checks (judged by ${r.judge === "lev" ? "LEV" : r.judge === "llm" ? "the AI model" : "nobody, nothing to judge"})`} empty="">
          {r.component_checks.map((c) => (
            <Item key={c.name} head={`${c.credited ? "Credited" : "Not credited"}: ${c.name}`} body={c.labels.length ? `${c.note}. Your label: "${c.labels.join('", "')}"` : c.note} />
          ))}
        </Block>
        <Block title="Missing components" empty="None missing.">
          {r.missing_components.map((m) => <Item key={m.name} head={m.name} body={m.why} />)}
        </Block>
        <Block title="Missing requirements" empty="All stated requirements are addressed.">
          {r.missing_requirements.map((m) => <Item key={m.requirement} head={m.requirement} body={m.why} />)}
        </Block>
        <Block title="Possibly misleading" empty="Nothing misleading found.">
          {r.misleading.map((m) => <Item key={m.statement} head={m.statement} body={m.why} />)}
        </Block>
        <Block title="What works" empty="">
          {r.strengths.length > 0 && <ul className="list-disc space-y-1 pl-5">{r.strengths.map((s) => <li key={s}>{s}</li>)}</ul>}
        </Block>

        <p className="text-sm text-base-content/60">
          Checked {graph.nodes.length} shapes and {graph.edges.length} connections.
          {graph.dangling_arrows > 0 && ` ${graph.dangling_arrows} arrow(s) are not attached to two shapes.`}
          {graph.unlabeled.length > 0 && ` ${graph.unlabeled.length} shape(s) have no label.`}
        </p>
      </div>
    </section>
  );
}

function Block({ title, empty, children }: { title: string; empty: string; children: ReactNode }) {
  const has = Array.isArray(children) ? children.length > 0 : Boolean(children);
  return (
    <div>
      <h3 className="mb-2 font-semibold">{title}</h3>
      {has ? <div className="space-y-2">{children}</div> : <p className="text-sm text-base-content/60">{empty}</p>}
    </div>
  );
}

function Item({ head, body }: { head: string; body: string }) {
  return (
    <div className="rounded-box border border-base-300 p-3">
      <p className="font-medium">{head}</p>
      {body && <p className="text-sm text-base-content/70">{body}</p>}
    </div>
  );
}
