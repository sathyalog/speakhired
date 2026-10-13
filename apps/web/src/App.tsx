import { useEffect, useState } from "react";
import { Setup } from "./Setup";
import { Session } from "./Session";
import { Report } from "./Report";
import { HotSeat } from "./HotSeat";
import { CleanCopy } from "./CleanCopy";
import { Daily } from "./Daily";
import { ResumeRadar } from "./ResumeRadar";
import { ModeProvider } from "./mode";
import { ModeSwitch } from "./ModeSwitch";
import { Toasts } from "./Toasts";
import { ArrowIcon, BackIcon, ChipIcon, CloudIcon, MicIcon, MoonIcon, ShieldIcon, SunIcon } from "./icons";
import { SETUPS, useMode } from "./mode";
import { stopSpeaking, type Question } from "./api";

export type Active = { id: string; voice: string; total: number; first: Question; role: string; company: string };
type View = "home" | "setup" | "hotseat" | "daily" | "cleancopy" | "radar" | "session" | "report";

function initialTheme(): string {
  try {
    const saved = localStorage.getItem("theme");
    if (saved) return saved;
  } catch { /* storage unavailable */ }
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "speakhired-dark" : "speakhired";
}

export default function App() {
  return <ModeProvider><Shell /><Toasts /></ModeProvider>;
}

function Shell() {
  const [view, setView] = useState<View>("home");
  const [active, setActive] = useState<Active | null>(null);
  const [theme, setTheme] = useState(initialTheme);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("theme", theme); } catch { /* ignore */ }
  }, [theme]);
  const dark = theme === "speakhired-dark";
  function goHome() {
    // an interview in progress is lost when you leave, so ask first
    if (view === "session" && !window.confirm("Leave this interview? Your progress so far will be lost.")) return;
    stopSpeaking();
    setView("home");
  }
  // from the report, Back returns to the feedback you were just reading; everywhere else it goes home
  function goBack() { if (view === "report") setView("session"); else goHome(); }

  return (
    <div className="flex min-h-screen flex-col">
      <div className="navbar sticky top-0 z-20 border-b border-base-300 bg-base-100/90 px-4 backdrop-blur md:px-8">
        <div className="navbar-start">
          <button className="btn btn-ghost gap-2 px-2 text-lg" onClick={goHome} aria-label="SpeakHired home">
            <span className="grid h-8 w-8 place-items-center rounded-xl bg-primary text-primary-content"><MicIcon size={18} /></span>
            <span className="font-display font-semibold">SpeakHired</span>
          </button>
        </div>
        <div className="navbar-end gap-2">
          <ModeSwitch />
          <label className="swap swap-rotate btn btn-ghost btn-circle" aria-label="Toggle dark mode">
            <input type="checkbox" checked={dark} onChange={(e) => setTheme(e.target.checked ? "speakhired-dark" : "speakhired")} />
            <span className="swap-off"><SunIcon /></span>
            <span className="swap-on"><MoonIcon /></span>
          </label>
        </div>
      </div>

      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8 md:px-8">
        {view !== "home" && (
          <button className="btn btn-ghost btn-sm -ml-2 mb-4 gap-1.5 rounded-full text-base-content/70" onClick={goBack}><BackIcon /> {view === "report" ? "Back to feedback" : "Back to home"}</button>
        )}
        {view === "home" && <Home go={setView} />}
        {view === "daily" && <Daily />}
        {view === "cleancopy" && <CleanCopy />}
        {view === "radar" && <ResumeRadar />}
        {view === "hotseat" && <HotSeat onStart={(a) => { setActive(a); setView("session"); }} />}
        {view === "setup" && <Setup onStart={(a) => { setActive(a); setView("session"); }} />}
        {(view === "session" || view === "report") && active && (
          // stays mounted (just hidden) while the report is open, so Back brings the feedback back exactly as it was
          <div className={view === "session" ? "" : "hidden"}><Session key={active.id} active={active} onFinish={() => { stopSpeaking(); setView("report"); }} /></div>
        )}
        {view === "report" && active && <Report id={active.id} onHome={() => setView("home")} />}
      </main>

      <footer className="border-t border-base-300 py-6 text-center text-sm text-base-content/60">
        Designed by Sathya
      </footer>
    </div>
  );
}

function Home({ go }: { go: (v: View) => void }) {
  const { info } = useMode();
  // The promise on this page has to be true for the mode you are in, and for where LEV (the scoring model) runs.
  const where = info?.lev.location ?? "off";
  const privacyLine = !info ? "" : info.mode === "online"
    ? "Free and open source. Your voice stays on your computer, and your name and contact details are removed before any AI sees your text."
    : where === "internet"
      ? "Free and open source. The AI runs on your computer, and only your answers with your name and contact details removed go to your own scoring server."
      : where === "network"
        ? "Free and open source. The AI runs on your computer and scoring on another computer in your own network. Your name and contact details are removed first."
        : "Free and open source. All your details stay on your computer and are never exposed to any AI service.";
  return (
    <>
      <section className="hero py-10 md:py-16">
        <div className="hero-content flex-col text-center">
          <span className="badge badge-soft badge-primary">For IT professionals</span>
          <h1 className="max-w-2xl text-4xl font-semibold leading-tight md:text-6xl">Speak well. <span className="text-primary">Get hired.</span></h1>
          <p className="max-w-xl text-base-content/70 md:text-lg">
            Practise real interviews out loud with a UK-accented interviewer, then see exactly how to say each answer better. {privacyLine}
          </p>
          <button className="btn btn-primary btn-lg mt-2 rounded-full px-8" onClick={() => go("setup")}>Start an interview <ArrowIcon /></button>
        </div>
      </section>

      <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-base-content/50">Practise speaking</h2>
      <section className="grid gap-4 md:grid-cols-3">
        <Tile title="Interview practice" body="Add a job description and your resume. Four rounds, from friendly screening to system design, each with its own interviewer voice." cta="Set up an interview" onClick={() => go("setup")} />
        <Tile title="Hot Seat" body="Got a tough question from a real interview? Paste one or two, answer out loud, and get a web-checked answer you can say to impress." cta="Take the seat" onClick={() => go("hotseat")} />
        <Tile title="Daily English for IT" body="Fifteen IT terms, abbreviations and workplace phrases a day. Hear each one, say it back, then use it in a sentence. Your streak and due reviews are kept on this computer." cta="Start today's set" onClick={() => go("daily")} />
      </section>

      <h2 className="mb-3 mt-10 text-sm font-medium uppercase tracking-wide text-base-content/50">Prepare your documents</h2>
      <section className="grid gap-4 md:grid-cols-2">
        <Tile title="Clean Copy" body="Paste a cover letter or an email to a recruiter. Fix spelling and grammar as you type, then polish the wording with AI." cta="Check my writing" onClick={() => go("cleancopy")} />
        <Tile title="Resume Radar" body="Upload your resume to see how well an applicant tracking system can read it. Get a score and clear fixes to improve it." cta="Check my resume" onClick={() => go("radar")} />
      </section>

      <HowItRuns />

      <p className="mx-auto mt-10 max-w-2xl text-center text-sm leading-relaxed text-base-content/70">
        Made in India, with love, for Indians. Built to help people whose first language isn't English, from every part of the country, speak with confidence and clear their interviews. Free for everyone.
      </p>
    </>
  );
}

function Tile({ title, body, cta, onClick, badge }: { title: string; body: string; cta?: string; onClick?: () => void; badge?: string }) {
  return (
    <div className="card border border-base-300 bg-base-100">
      <div className="card-body">
        <div className="flex flex-wrap items-center gap-2"><h2 className="card-title text-xl">{title}</h2>{badge && <span className="badge badge-ghost">{badge}</span>}</div>
        <p className="text-base-content/70">{body}</p>
        <div className="card-actions mt-2">
          {onClick ? <button className="btn btn-primary btn-outline rounded-full" onClick={onClick}>{cta}</button> : <button className="btn btn-disabled rounded-full" aria-disabled>Not ready yet</button>}
        </div>
      </div>
    </div>
  );
}

const SCORING: Record<string, string> = {
  off: "Scoring: the AI model scores your answers itself (LEV is switched off).",
  this_computer: "Scoring (LEV): on this computer, so nothing leaves it.",
  network: "Scoring (LEV): on another computer in your own network.",
  internet: "Scoring (LEV): on your own remote server. Answers with personal details removed are sent there.",
};

function HowItRuns() {
  const { info, choose, busy } = useMode();
  const online = info?.mode === "online";
  const provider = info?.grok.provider ?? "A free online AI service";
  const card = (active: boolean) => `card border bg-base-100 ${active ? "border-primary ring-1 ring-primary/30" : "border-base-300"}`;
  return (
    <section className="mt-10" aria-labelledby="how-it-runs">
      <h2 id="how-it-runs" className="mb-1 text-sm font-medium uppercase tracking-wide text-base-content/50">How it runs: Offline or Online</h2>
      {info && <p className="mb-2 text-sm"><span className={`badge badge-soft mr-2 ${SETUPS[info.setup].tone}`}>Your setup: {SETUPS[info.setup].label}</span><span className="text-base-content/70">{SETUPS[info.setup].detail}</span></p>}
      <p className="mb-3 max-w-3xl text-sm text-base-content/70">Switch any time with the toggle at the top right. In both modes your voice and the grammar checker stay on this computer, and your name, contact details, IDs and address are removed before any AI sees your text.</p>
      <div className="grid gap-4 md:grid-cols-2">
        <div className={card(!online)}>
          <div className="card-body gap-2">
            <div className="flex items-center gap-2"><span className="text-primary"><ChipIcon /></span><h3 className="card-title text-lg">Offline</h3>{!online && <span className="badge badge-primary badge-soft badge-sm">Current</span>}</div>
            <p className="text-sm text-base-content/70">Ollama on this computer writes the answers, and LEV does the scoring. Nothing is sent to a cloud AI. Needs about 16 GB of memory to feel quick.</p>
            <p className="text-xs text-base-content/60"><b>Set up:</b> install Ollama, run <code>ollama pull qwen3:4b</code>.</p>
            <p className="text-xs text-base-content/60">{SCORING[info?.lev.location ?? "off"]}{info?.lev.location === "internet" ? " For a fully private setup, run LEV on this computer (see the README)." : ""}</p>
            {online && <div className="card-actions"><button className="btn btn-outline btn-sm rounded-full" disabled={busy} onClick={() => choose("offline")}>Use Offline</button></div>}
          </div>
        </div>
        <div className={card(online)}>
          <div className="card-body gap-2">
            <div className="flex items-center gap-2"><span className="text-primary"><CloudIcon /></span><h3 className="card-title text-lg">Online</h3>{online && <span className="badge badge-primary badge-soft badge-sm">Current</span>}</div>
            <p className="text-sm text-base-content/70">{provider} writes the answers (in seconds), with LEV on your own server for scoring. If one service reaches its free limit, the app switches to the next one you have a key for. Best for small computers, and nothing heavy runs locally.</p>
            <p className="text-xs text-base-content/60">{SCORING[info?.lev.location ?? "off"]}</p>
            <p className="text-xs text-base-content/60"><b>Set up:</b> get one or more free keys (Groq, Mistral or Google AI Studio), add them to <code>.env</code>, then restart. The README has the steps.{info && !info.grok.configured ? " No key found yet." : ""}</p>
            {!online && <div className="card-actions"><button className="btn btn-outline btn-sm rounded-full" disabled={busy} onClick={() => choose("online")}>Use Online</button></div>}
          </div>
        </div>
      </div>
      <p className="mt-3 flex items-center gap-1.5 text-xs text-base-content/60"><ShieldIcon /> Removed before any AI step: names, emails, phone numbers, links, addresses, birth dates, Aadhaar, PAN, passport and bank or card numbers.</p>
    </section>
  );
}
