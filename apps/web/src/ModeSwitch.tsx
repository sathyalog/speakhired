import { SETUPS, useMode } from "./mode";
import { ChipIcon, CloudIcon } from "./icons";

/** Sliding two-way switch in the top bar: Offline (Ollama on this computer) or Online (Grok, personal details removed first). */
export function ModeSwitch() {
  const { info, busy, choose } = useMode();
  if (!info) return null;
  const online = info.mode === "online";
  const keyMissing = online && !info.grok.configured;
  const setup = SETUPS[info.setup];
  const base = "relative z-10 flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors";
  return (
    <div className="flex items-center gap-2">
    <span className={`badge badge-soft badge-sm hidden whitespace-nowrap lg:inline-flex ${setup.tone}`} title={setup.detail}>{setup.label}</span>
    <div className="tooltip tooltip-bottom" data-tip={online ? `Online: ${info.grok.provider} (${info.grok.model}) writes the answers. Personal details are removed first.` : "Offline: Ollama on this computer writes the answers. Nothing leaves your machine."}>
      <div role="group" aria-label="AI mode" className="relative flex rounded-full border border-base-300 bg-base-200 p-0.5">
        <span aria-hidden className="absolute inset-y-0.5 left-0.5 w-[calc(50%-2px)] rounded-full bg-primary transition-transform duration-300 ease-out" style={{ transform: online ? "translateX(100%)" : "translateX(0)" }} />
        <button className={`${base} ${!online ? "text-primary-content" : "text-base-content/70"}`} aria-pressed={!online} disabled={busy} onClick={() => choose("offline")}>
          <ChipIcon /><span className="hidden sm:inline">Offline</span>
        </button>
        <button className={`${base} ${online ? "text-primary-content" : "text-base-content/70"}`} aria-pressed={online} disabled={busy} onClick={() => choose("online")}>
          <CloudIcon /><span className="hidden sm:inline">Online</span>
          {keyMissing && <span className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border border-base-100 bg-warning" aria-label="API key not configured" />}
        </button>
      </div>
    </div>
    </div>
  );
}
