import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "./api";

/** Models sometimes wrap Markdown in a code fence or add stray spaces at line ends; tidy that before rendering. */
const tidy = (t: string) => t.trim().replace(/^```(?:markdown|md)?\s*\n/i, "").replace(/\n```\s*$/, "").replace(/[ \t]+$/gm, "");

export function Report({ id, onHome }: { id: string; onHome: () => void }) {
  const [r, setR] = useState<Awaited<ReturnType<typeof api.report>> | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => { api.report(id).then(setR).catch((e) => setErr(e.message)); }, [id]);

  if (err) return <div role="alert" className="alert alert-error alert-soft">{err}</div>;
  if (!r) return (
    <div className="flex flex-col gap-3">
      <div className="skeleton h-10 w-64" /><div className="skeleton h-40 w-full" />
      <p className="text-base-content/60"><span className="loading loading-dots loading-sm" /> Preparing your report</p>
    </div>
  );

  const entries = Object.entries(r.averages);
  const overall = entries.length ? entries.reduce((a, [, v]) => a + v, 0) / entries.length : 0;
  return (
    <div>
      <h1 className="text-3xl font-semibold md:text-4xl">Your interview report</h1>
      <p className="mt-1 text-base-content/70">{r.results.length} {r.results.length === 1 ? "answer" : "answers"} reviewed.</p>

      <div className="mt-6 grid gap-4 lg:grid-cols-5">
        <div className="card border border-base-300 bg-base-100 lg:col-span-2">
          <div className="card-body items-center text-center">
            <div className="radial-progress text-primary" style={{ "--value": (overall / 5) * 100, "--size": "9rem", "--thickness": "0.6rem" } as React.CSSProperties} role="img" aria-label={`Overall ${overall.toFixed(1)} out of 5`}>
              <span className="font-display text-3xl text-base-content">{overall.toFixed(1)}</span>
            </div>
            <div className="text-sm text-base-content/60">Overall score out of 5</div>
            <div className="mt-4 w-full space-y-3 text-left">
              {entries.map(([k, v]) => (
                <div key={k}>
                  <div className="mb-1 flex justify-between text-sm"><span className="capitalize">{k}</span><span className="text-base-content/60">{v}/5</span></div>
                  <progress className="progress progress-primary w-full" value={v} max={5} />
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="card border border-base-300 bg-base-100 lg:col-span-3">
          <div className="card-body">
            <h2 className="card-title">Summary and practice plan</h2>
            <div className="md"><ReactMarkdown remarkPlugins={[remarkGfm]}>{tidy(r.summary)}</ReactMarkdown></div>
            <div className="card-actions mt-2"><button className="btn btn-primary rounded-full" onClick={onHome}>Back to home</button></div>
          </div>
        </div>
      </div>
    </div>
  );
}
