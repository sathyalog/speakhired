import { useSyncExternalStore } from "react";

export type Toast = { id: number; title: string; body: string; tone: "warning" | "error" | "info"; ttl: number };
let toasts: Toast[] = [];
let nextId = 1;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

/** Shows a floating tile for `ttl` milliseconds (10 seconds by default). The same message is not stacked twice. */
export function notify(t: Omit<Toast, "id" | "ttl"> & { ttl?: number }): void {
  if (toasts.some((x) => x.title === t.title && x.body === t.body)) return;
  const toast: Toast = { id: nextId++, ttl: 10000, ...t };
  toasts = [...toasts, toast];
  emit();
  setTimeout(() => dismiss(toast.id), toast.ttl);
}

export function dismiss(id: number): void {
  toasts = toasts.filter((t) => t.id !== id);
  emit();
}

export function useToasts(): Toast[] {
  return useSyncExternalStore((cb) => { listeners.add(cb); return () => listeners.delete(cb); }, () => toasts);
}

let provider = "Online AI";
export function setProvider(name: string): void { provider = name; }

const messages = (): Record<string, { title: string; body: string; tone: Toast["tone"] }> => ({
  grok_not_configured: { title: `${provider} key is not configured`, body: "Add a free key to the .env file (GROQ_API_KEY, MISTRAL_API_KEY or GEMINI_API_KEY) and restart the app, or switch to Offline mode.", tone: "warning" },
  grok_wrong_service: { title: "Key and service don't match", body: "Your key belongs to a different service than EXTERNAL_API_BASE points to. Check the .env file.", tone: "error" },
  grok_auth: { title: `${provider} did not accept your key`, body: "Check that service's key in your .env file, or switch to Offline mode.", tone: "error" },
  grok_model: { title: "Unknown model name", body: "Check the model name for that service in your .env file.", tone: "error" },
  grok_rate: { title: "Usage limit reached", body: "Every online AI service has run out for now. Wait a little and try again, or switch to Offline mode.", tone: "warning" },
  grok_unreachable: { title: `Can't reach ${provider}`, body: "Check your internet connection, or switch to Offline mode.", tone: "error" },
  grok_error: { title: `${provider} returned an error`, body: "Try again, or switch to Offline mode.", tone: "error" },
  ollama_unavailable: { title: "Ollama is not running", body: "Start Ollama on this computer, or switch to Online mode.", tone: "warning" },
  ollama_error: { title: "Ollama could not answer", body: "Try again, or switch to Online mode.", tone: "error" },
});

export function reportLlmProblem(code: string, message = ""): void {
  const m = messages()[code];
  // the server's own message is more specific (it names the exact setting to change), so prefer it when there is one
  notify(m ? { ...m, body: message || m.body } : { title: "The AI step failed", body: message || "Try again in a moment.", tone: "error" });
}
