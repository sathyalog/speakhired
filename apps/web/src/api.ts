import { notify, reportLlmProblem } from "./toast";

export type Question = { id: string; text: string; kind: string; topic: string; difficulty: number; key_points: string[]; hint?: string };
export type Voice = { id: string; name: string; gender: string; persona: string; round: number };
export type Correction = { original: string; fix: string; reason: string };
export type Swap = { instead_of: string; say: string; why: string };
export type WebCheck = { verdict: "sufficient" | "partial" | "insufficient"; reference_points: string[]; missing_points: string[];
  fact_flags: { claim: string; status: "supported" | "unclear" | "wrong"; note: string }[]; sources: { title: string; url: string }[]; verified: boolean; answer_included: boolean };
export type Impressive = { answer_first: string; example: string; trade_off: string; close: string };
export type Feedback = { proof_point?: ProofPoint | null; corrected_answer?: string; swaps?: Swap[]; impressive?: Impressive | null; web_check?: WebCheck | null; corrections: Correction[]; better_version: string; missing_outline: string[]; vocabulary_tips: string[]; spoken_summary: string };
export type Evaluation = { scores: Record<string, number>; evidence: Record<string, string>; covered_points: string[]; missed_points: string[]; judge: string; confidence: number };
export type Delivery = { words: number; wpm: number; fillers: Record<string, number>; long_pauses: number };
export type LangWord = { word: string; lang: string; english: string[] };
export type LangReport = { status: "english" | "mixed" | "non_english"; language: string; language_name: string; confidence: number; words: LangWord[]; ratio: number; source: "audio" | "text" };
export type LangAudio = { code: string; prob: number; non_english: boolean };
export type ProofPoint = { repo: string; url: string; claim: string; evidence: string; summary: string };
export type Polished = { swaps: Swap[]; impressive: Impressive; better_version: string; proof_point?: ProofPoint | null };
export type AnswerResult = { answer_index: number; polish_pending?: boolean; language: LangReport; evaluation: Evaluation; feedback: Feedback; delivery: Delivery; done: boolean; ack: string; next_question: Question | null };

async function j<T>(r: Response): Promise<T> {
  // The server flags any AI step that failed (even one it recovered from) so a notice can be shown.
  const aiProblem = r.headers.get("X-LLM-Error");
  if (aiProblem) reportLlmProblem(aiProblem, r.headers.get("X-LLM-Error-Message") ?? "");
  // The answer came from another online provider after the first one reached its limit.
  const switched = r.headers.get("X-LLM-Switch");
  if (switched) notify({ tone: "info", title: "Switched AI provider", body: switched, ttl: 8000 });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail ?? msg; } catch { /* ignore */ }
    throw new Error(msg);
  }
  return r.json();
}

export type Setup = "fully_offline" | "offline_hosted_scoring" | "online";
export type ProviderStatus = { provider: string; model: string; configured: boolean; paused_until: string | null };
export type ModeInfo = { mode: "offline" | "online"; setup: Setup; grok: { configured: boolean; model: string; provider: string; providers?: ProviderStatus[] }; lev: { mode: string; remote: boolean; location: "off" | "this_computer" | "network" | "internet" }; redaction: { names: string } };

export type SystemDesignQuestion = { id: string; title: string; track: "regular" | "ai"; level: number; level_label: string; source: string; prompt: string; functional: string[]; non_functional: string[]; scale: string[] };
export type SystemDesignReview = {
  score: number;
  dimensions: Record<string, number>;
  weights: Record<string, number>;
  judge: "lev" | "llm" | "none";
  checked_components: string[];
  component_checks: { name: string; drawn: boolean; connected: boolean; credited: boolean; note: string; labels: string[] }[];
  missing_components: { name: string; why: string }[];
  missing_requirements: { requirement: string; why: string }[];
  misleading: { statement: string; why: string }[];
  strengths: string[];
  summary: string;
  graph: { nodes: { ref: string; label: string; shape: string }[]; edges: { from: string; to: string; label: string; two_way: boolean }[]; dangling_arrows: number; unlabeled: string[]; isolated: string[] };
};

export const api = {
  mode: () => fetch("/api/mode").then(j<ModeInfo>),
  systemDesignQuestions: (track: "regular" | "ai") => fetch(`/api/system-design/questions?track=${track}`).then(j<SystemDesignQuestion[]>),
  reviewSystemDesign: (question_id: string, elements: readonly unknown[]) =>
    fetch("/api/system-design/review", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question_id, elements }) }).then(j<SystemDesignReview>),
  setMode: (mode: "offline" | "online") => fetch("/api/mode", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode }) }).then(j<ModeInfo>),
  voices: () => fetch("/api/voices").then(j<Voice[]>),
  health: () => fetch("/api/health").then(j<any>),
  createSession: (fd: FormData) => fetch("/api/sessions", { method: "POST", body: fd }).then(j<{ id: string; job: any; total: number; question: Question; brief: any; repos?: { name: string; url: string; description: string; language: string }[]; github_note?: string }>),
  quickPreview: (question: string, answer: string, include_answer: boolean) =>
    fetch("/api/quick/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question, answer, include_answer }) }).then(j<{ enabled: boolean; prompt: string }>),
  createQuick: (body: { questions: { text: string; hint: string }[]; voice: string; web_check: boolean; include_answer: boolean }) =>
    fetch("/api/quick/sessions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(j<{ id: string; job: any; total: number; question: Question; web_check: boolean }>),
  transcribe: (blob: Blob, sessionId = "", hint = "") => { const fd = new FormData(); fd.append("audio", blob, "answer.webm"); fd.append("session_id", sessionId); fd.append("hint", hint); return fetch("/api/transcribe", { method: "POST", body: fd }).then(j<{ text: string; heard: string; corrections: { heard: string; fixed: string }[]; duration: number; language: LangAudio; report: LangReport }>); },
  checkLanguage: (text: string, audio_language: LangAudio | null) =>
    fetch("/api/language/check", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, audio_language }) }).then(j<LangReport>),
  answer: (id: string, transcript: string, duration: number, audio_language: LangAudio | null = null) =>
    fetch(`/api/sessions/${id}/answer`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ transcript, duration, audio_language }) }).then(j<AnswerResult>),
  improveWriting: (text: string, kind: string, tone: string, rewrite: boolean) =>
    fetch("/api/write/improve", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, kind, tone, rewrite }) }).then(j<WriteResult>),
  analyzeResume: (file: File, jd_text: string, jd_url: string, use_lev: boolean, use_ai = true) => {
    const fd = new FormData(); fd.append("resume", file); fd.append("jd_text", jd_text); fd.append("jd_url", jd_url); fd.append("use_lev", String(use_lev)); fd.append("use_ai", String(use_ai));
    return fetch("/api/ats/analyze", { method: "POST", body: fd }).then(j<AtsReport>);
  },
  atsRewrites: (file: File) => {
    const fd = new FormData(); fd.append("resume", file);
    return fetch("/api/ats/rewrites", { method: "POST", body: fd }).then(j<{ suggestions: AtsReport["suggestions"] }>);
  },
  polish: (id: string, index: number) => fetch(`/api/sessions/${id}/polish/${index}`, { method: "POST" }).then(j<Polished>),
  dailyToday: () => fetch("/api/daily/today").then(j<DailyToday>),
  dailyLevels: () => fetch("/api/daily/levels").then(j<DailyLevels>),
  setDailyLevel: (level: string) => fetch("/api/daily/level", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ level }) }).then(j<DailyLevels>),
  dailyAttempt: (body: { item_id: string; step: "repeat" | "use"; transcript: string; audio_language?: LangAudio | null }) =>
    fetch("/api/daily/attempt", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(j<DailyAttempt>),
  report: (id: string) => fetch(`/api/sessions/${id}/report`).then(j<{ summary: string; averages: Record<string, number>; results: any[] }>),
};

export type WriteIssue = { original: string; replacement: string; category: string; message: string; start: number; end: number };
export type WriteResult = { issues: WriteIssue[]; rewrite: string | null; truncated: boolean };
export type AtsReport = {
  score: number; grade: string; judge: string; notes: string[]; words: number; pages: number;
  sections: { id: string; name: string; score: number; max: number }[];
  checks: { id: string; section: string; label: string; passed: boolean; credit: number; detail: string }[];
  keywords: { provided: boolean; matched: string[]; missing: string[] }; redactions: Record<string, number>;
  suggestions: { priority: "high" | "medium" | "low"; category: string; title: string; fix: string; before: string; after: string }[];
};

let current: HTMLAudioElement | null = null;

export const voiceSpeed = {
  get: (): number => { try { return Number(localStorage.getItem("voice_speed")) || 0.95; } catch { return 0.95; } },
  set: (v: number) => { try { localStorage.setItem("voice_speed", String(v)); } catch { /* ignore */ } },
};

function britishVoice(): SpeechSynthesisVoice | undefined {
  const voices = speechSynthesis.getVoices().filter((v) => v.lang.toLowerCase().startsWith("en-gb"));
  return voices.find((v) => /daniel|serena|kate|oliver|google uk/i.test(v.name)) ?? voices[0];
}

let playToken = 0;   // a newer request cancels an older one

/** Short pieces (about two sentences) so the first words start playing quickly, even for a long answer. */
export function splitForSpeech(text: string, limit = 220): string[] {
  const sentences = text.replace(/\s+/g, " ").trim().split(/(?<=[.!?])\s+/).filter(Boolean);
  const chunks: string[] = [];
  for (const s of sentences) {
    const last = chunks.length - 1;
    if (last >= 0 && chunks[last].length + s.length + 1 <= limit) chunks[last] += " " + s; else chunks.push(s);
  }
  return chunks.length ? chunks : [text];
}

async function fetchAudio(text: string, voice: string): Promise<Blob | null> {
  const fd = new FormData(); fd.append("text", text); fd.append("voice", voice); fd.append("speed", String(voiceSpeed.get()));
  try { const r = await fetch("/api/speak", { method: "POST", body: fd }); return r.ok ? await r.blob() : null; } catch { return null; }
}

function playBlob(blob: Blob, token: number): Promise<"done" | "blocked"> {
  return new Promise((resolve) => {
    const audio = new Audio(URL.createObjectURL(blob));
    current = audio;
    audio.onended = () => resolve("done");
    audio.onerror = () => resolve("done");
    audio.play().catch(() => resolve(token === playToken ? "blocked" : "done"));
  });
}

async function browserVoice(text: string, token: number): Promise<void> {
  let spoken = text;
  try { const f = new FormData(); f.append("text", text); spoken = (await fetch("/api/speech-text", { method: "POST", body: f }).then((r) => r.json())).text ?? text; } catch { /* use raw text */ }
  if (token !== playToken) return;
  return new Promise((res) => {
    const u = new SpeechSynthesisUtterance(spoken); u.lang = "en-GB"; u.rate = voiceSpeed.get(); const v = britishVoice(); if (v) u.voice = v;
    u.onend = () => res(); u.onerror = () => res();
    speechSynthesis.speak(u);
  });
}

/** Reads text aloud with the app's own voice, piece by piece; falls back to the browser's British voice. `onStart` fires when sound begins. */
export async function speak(text: string, voice: string, onStart?: () => void): Promise<void> {
  const token = ++playToken;
  current?.pause(); speechSynthesis.cancel();
  const chunks = splitForSpeech(text);
  let pending: Promise<Blob | null> = fetchAudio(chunks[0], voice);
  for (let i = 0; i < chunks.length; i++) {
    const blob = await pending;
    if (token !== playToken) return;                       // replaced by a newer request or stopped
    if (!blob) { onStart?.(); return browserVoice(chunks.slice(i).join(" "), token); }
    if (i + 1 < chunks.length) pending = fetchAudio(chunks[i + 1], voice);   // prepare the next piece while this one plays
    onStart?.(); onStart = undefined;
    if ((await playBlob(blob, token)) === "blocked") {
      notify({ tone: "warning", title: "Your browser blocked the sound", body: "Click anywhere on the page, then press Hear it or Repeat question again." });
      return;
    }
  }
}

export function stopSpeaking(): void { playToken++; current?.pause(); speechSynthesis.cancel(); }

export type DailyItem = { id: string; kind: string; text: string; meaning: string; example: string; prompt: string; aliases: string[]; say_not?: { instead_of: string; say: string } };
export type DailyToday = { items: DailyItem[]; level: string; progress: { level: string; total: number; started: number; learned: number; due_today: number }; streak: number; done_today: string[] };
export type DailyLevels = { current: string; levels: { id: string; label: string; for: string; total: number; started: number; learned: number }[] };
export type DailyAttempt = { grade: "again" | "hard" | "good" | "easy"; feedback: string; next?: string; better?: string; item_grade?: string; due?: string; next_review_days?: number; item: DailyItem };
