"""`uv run python -m speakhired.doctor` checks the machine and says which mode will suit it.
`uv run python -m speakhired.doctor --bench [model]` times Ollama on your computer."""
import json
import os
import platform
import shutil
import sys
import time
import urllib.request

from .sysinfo import ram_gb, swap_used_gb


def bench(model: str) -> None:
    """Times a small real request so you can see how fast your computer writes feedback with a given model."""
    url = (os.environ.get("OLLAMA_URL") or _env_file_value("OLLAMA_URL") or "http://localhost:11434").rstrip("/")
    body = {"model": model, "stream": False, "think": False, "keep_alive": "30m", "options": {"temperature": 0, "num_predict": 160},
            "messages": [{"role": "user", "content": "In about 100 words, explain what a Kafka consumer group is, in plain English."}]}
    print(f"Testing '{model}' on your computer (about 30 seconds)...")
    try:
        t = time.time()
        req = urllib.request.Request(url + "/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"})
        r = json.load(urllib.request.urlopen(req, timeout=600))
    except Exception as e:  # noqa: BLE001
        sys.exit(f"Could not run the test: {e}. Is Ollama running, and have you run 'ollama pull {model}'?")
    tokens, secs = r.get("eval_count", 0), r.get("eval_duration", 1) / 1e9
    speed = tokens / max(secs, 0.001)
    print(f"Speed: {speed:.0f} words-pieces (tokens) per second   |   total {time.time() - t:.0f}s   |   model load {r.get('load_duration', 0) / 1e9:.1f}s")
    swap = swap_used_gb()
    if swap is not None:
        print(f"Memory in use as slow swap: {swap:.1f} GB" + ("  <- high: close browser tabs and other apps, then test again" if swap > 3 else ""))
    # one piece of feedback is roughly 150 tokens, a full set of interview questions roughly 700
    print(f"Estimated waits: quick feedback about {150 / speed:.0f}s, the answer to give about {220 / speed:.0f}s, starting an interview about {900 / speed:.0f}s.")
    if speed < 10:
        print("That is slow. Options: a smaller model (ollama pull qwen3:1.7b, then OLLAMA_MODEL=qwen3:1.7b in .env), closing other apps, or Online mode.")
    elif speed < 20:
        print("Usable. A smaller model (qwen3:1.7b) would be roughly twice as fast, with simpler answers; Online mode is faster still.")
    else:
        print("Good speed for Offline mode.")


def main() -> None:
    if "--bench" in sys.argv:
        args = [a for a in sys.argv[1:] if not a.startswith("--")]
        return bench(args[0] if args else (os.environ.get("OLLAMA_MODEL") or _env_file_value("OLLAMA_MODEL") or "qwen3:4b"))
    ram = ram_gb()
    key = bool(os.environ.get("EXTERNAL_API_KEY") or _env_file_value("EXTERNAL_API_KEY"))
    print(f"RAM: {ram:.0f} GB   OS: {platform.system()} {platform.machine()}")
    print("Node:", "found" if shutil.which("node") else "MISSING (needed for the web UI)")
    print("Ollama (Offline mode):", "found" if shutil.which("ollama") else "not installed (only needed for Offline mode: https://ollama.com)")
    print("Online key (EXTERNAL_API_KEY):", "set" if key else "not set (only needed for Online mode: free key at https://console.groq.com)")
    print()
    if ram and ram < 12:
        print("Suggestion: your computer has little memory. Online mode is much faster here (AI runs in the cloud, personal details removed first).")
        print("            Offline mode works too with OLLAMA_MODEL=qwen3:4b but can take minutes per step.")
    elif ram < 24:
        print("Suggestion: Offline mode works well with OLLAMA_MODEL=qwen3:4b. Online mode is faster if you prefer.")
    else:
        print("Suggestion: Offline mode works well; you can try OLLAMA_MODEL=qwen3:8b for better answers.")
    print("You can switch modes any time with the toggle at the top right of the app.")
    lev_mode = os.environ.get("LEV_MODE") or _env_file_value("LEV_MODE") or "off"
    print("LEV (scoring):", lev_mode, "- see the README section 'LEV: the scoring model'.")
    if lev_mode == "local" and ram and ram < 12:
        print("  Warning: LEV_MODE=local needs about 16 GB of memory and will not load on this computer. Use LEV_MODE=http with a server elsewhere, or off.")


def _env_file_value(name: str) -> str:
    try:
        for line in open(".env"):
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


if __name__ == "__main__":
    main()
