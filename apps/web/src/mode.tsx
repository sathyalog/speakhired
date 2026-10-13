import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { api, ModeInfo, Setup } from "./api";
import { notify, setProvider } from "./toast";

type Ctx = { info: ModeInfo | null; busy: boolean; choose: (m: "offline" | "online") => Promise<void> };
const ModeContext = createContext<Ctx>({ info: null, busy: false, choose: async () => {} });
export const useMode = () => useContext(ModeContext);

/** The three ways the app can be set up, named for people: where the AI runs and where scoring runs decide what leaves the computer. */
export const SETUPS: Record<Setup, { label: string; tone: string; detail: string }> = {
  fully_offline: { label: "Fully offline", tone: "badge-success", detail: "The AI and the scoring both run on this computer. Nothing is sent anywhere." },
  offline_hosted_scoring: { label: "Offline + your scoring server", tone: "badge-info", detail: "The AI runs on this computer. Scoring runs on a server of your own, which receives your answers with personal details removed." },
  online: { label: "Online", tone: "badge-primary", detail: "A cloud AI writes the answers, with your name, contact details and IDs removed first." },
};

export function ModeProvider({ children }: { children: ReactNode }) {
  const [info, setInfo] = useState<ModeInfo | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.mode().then((m) => { setProvider(m.grok.provider); setInfo(m); }).catch(() => {}); }, []);

  const choose = useCallback(async (m: "offline" | "online") => {
    setBusy(true);
    try {
      const next = await api.setMode(m);
      setProvider(next.grok.provider);
      setInfo(next);
      if (m === "online" && !next.grok.configured) {
        notify({ tone: "warning", title: "No online key is set", body: "Online mode needs at least one free key (GROQ_API_KEY, MISTRAL_API_KEY or GEMINI_API_KEY) in the .env file. Restart the app after adding it, or switch back to Offline mode." });
      }
    } catch { notify({ tone: "error", title: "Couldn't switch mode", body: "Is the app's server running?" }); }
    finally { setBusy(false); }
  }, []);

  return <ModeContext.Provider value={{ info, busy, choose }}>{children}</ModeContext.Provider>;
}
