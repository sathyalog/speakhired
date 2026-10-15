<p align="center">
  <img src="assets/banner.svg" alt="SpeakHired banner: Speak well. Get hired." width="100%">
</p>

<h1 align="center">SpeakHired</h1>
<p align="center">
  <img alt="Status: Beta" src="https://img.shields.io/badge/status-beta-f59e0b">
  <a href="LICENSE"><img alt="License: Apache 2.0" src="https://img.shields.io/badge/license-Apache%202.0-2563eb"></a>
  <img alt="Offline and Online" src="https://img.shields.io/badge/mode-offline%20%7C%20online-16a34a">
</p>

**Beta.** A free, open-source voice coach for IT professionals who want to speak confident English and pass interviews. It runs on your computer in **Offline** mode, or with a cloud AI in **Online** mode. Your name, contact details and IDs are removed before any AI sees your text.

## Features
- **Interview practice:** paste a job description (or link) and upload your resume. Optionally, add the **interview pattern**: what the recruiter told you about the interview (its type, rounds and expectations). A UK-accented interviewer asks questions aloud over four rounds, from screening to system design. Each answer comes back corrected, with the points you missed and the answer to give the interviewer.
- **Hot Seat:** rehearse one to three real questions you were asked. An optional web check (needs `EXTERNAL_API_KEY` in `.env`, separate from the free keys below) sends only the question, unless you tick "Include my answer".
- **Clean Copy:** a grammar and spelling checker, in your browser, for cover letters and recruiter emails, with optional AI rewrites.
- **Resume Radar:** an ATS-readiness score for your resume, with prioritised fixes.
- **GitHub proof points (Online mode):** if one of your public repos already does what an interview question asks, a "Proof point" card appears under the answer.
- **Daily English for IT:** 15 IT terms, abbreviations and workplace phrases a day, at three levels (Foundation, Professional, Expert). Hear each one, say it back, then use it in a sentence. Works offline.
- **Built-in helpers:** technical words are spoken and heard correctly (ChatGPT, kubectl, PostgreSQL). Other languages are flagged, with an English alternative suggested.

## Choose a mode
Switch with the toggle at the top right of any page. The Home page shows which setup you are in.

| | **Offline** (default) | **Online** |
|---|---|---|
| Who writes the AI answers | Ollama on your computer (`qwen3:4b`) | Groq, Mistral or Google AI Studio, with your own free keys |
| Needs | Ollama and about 3 GB of disk; 16 GB of memory to feel quick | A key and internet access |
| Best for | Privacy, no internet, no usage limits | Computers with 8 GB of memory: answers in seconds. If one free service runs out, the app switches to the next key you added |
| Install with | `./scripts/setup.sh` | `./scripts/setup.sh --online` |

Not sure which to use? Run `uv run python -m speakhired.doctor` after installing. It checks your computer and suggests a mode.

## Where your data goes
The job description, the interview pattern and your resume are all treated the same way: personal details are removed before any AI reads them (see below).
Scoring (LEV) can run in three places. Together with the mode, that gives three setups, and the Home page names the one you are in:

| Setup | Mode | LEV runs | What leaves your computer |
|---|---|---|---|
| **Fully offline** | Offline | Inside the app, on `lev serve` on this computer, or off | Nothing |
| **Offline + your scoring server** | Offline | On your Modal app, or another computer on your network | Your answers, with personal details removed, to your own server |
| **Online** | Online | Anywhere, as above | Text with personal details removed, to the cloud AI that answers (Groq, Mistral or Google AI Studio, whichever has a key and is not paused), and to LEV if it is remote |

**Personal details are removed before any AI sees your text, in every setup.** Your name, emails, phone numbers, links, addresses, birth date, Aadhaar, PAN, passport, bank and card numbers, and personal fields such as marital status are replaced with placeholders such as `[NAME_1]`. You see the real text in the answer. Employers, colleges, cities and technologies are kept, because a review needs them.

Names are found from the first line of a resume, "Name:" fields, titles such as Mr or Dr, and phrases like "worked with Ravi Kumar". A name in the middle of a sentence with none of these signs can slip through. To see exactly what an AI would receive from your file, run this; it works entirely on your computer:
```bash
uv run python -m speakhired.redact_preview path/to/your-resume.pdf
```

## Models
| Job | Model | Runs on |
|---|---|---|
| Questions and feedback, Offline | `qwen3:4b` via Ollama (`OLLAMA_MODEL`) | Your computer |
| Questions and feedback, Online | `openai/gpt-oss-120b` on Groq (`GROQ_MODEL`), `ministral-8b-2512` on Mistral (`MISTRAL_MODEL`), `gemini-3.5-flash` on Google AI Studio (`GEMINI_MODEL`) | The service's cloud |
| Scoring and decisions | LEV (based on Qwen3.5-4B) | Where you run LEV (see below) |
| Listening | Whisper `small` (`WHISPER_MODEL`) | Your computer |
| Speaking (interviewer voice) | Kokoro, British voices | Your computer |
| Grammar check (Clean Copy) | Harper | Your browser |

## Setup

### 1. Install the tools (once)
| Tool | macOS | Windows | Linux | Needed for |
|---|---|---|---|---|
| [uv](https://docs.astral.sh/uv/) (Python) | `brew install uv` | `winget install astral-sh.uv` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | Both |
| [Node.js 20+](https://nodejs.org) | `brew install node` | `winget install OpenJS.NodeJS.LTS` | your package manager | Both |
| espeak-ng (Kokoro voice) | `brew install espeak-ng` | [installer](https://github.com/espeak-ng/espeak-ng/releases) | `sudo apt install espeak-ng` | Both |
| [Ollama](https://ollama.com/download) | `brew install ollama` or the app | installer from ollama.com | `curl -fsSL https://ollama.com/install.sh \| sh` | Offline only |

On Windows, `scripts\setup.cmd` tries to install missing uv, Node.js and Ollama for you with `winget` (built into Windows 11). It does not install espeak-ng, so install that yourself. If a tool still cannot be found afterwards (for example, winget is missing or blocked by your organisation), install it by hand from the table, then open a **new** PowerShell window and run setup again. A window that was open during the install keeps its old PATH.

### 2. Get the code and settings
```bash
git clone <this repo> && cd speakhired
cp .env.example .env
```
Windows (Command Prompt or PowerShell): `copy .env.example .env`

### 3A. Offline setup (Ollama)
The Ollama desktop app and the Windows installer start the server for you. With the Homebrew or Linux install, run `ollama serve` in a terminal and leave it open. Then:
```bash
./scripts/setup.sh          # Windows: scripts\setup.cmd
```
This also downloads the model (about 2.5 GB, once). "Address already in use" from `ollama serve` means Ollama is already running.

### 3B. Online setup (free keys, no Ollama needed)
1. Get one or more free keys. The steps are in [Free API keys](#free-api-keys) below. Groq, Mistral and Google AI Studio are recommended.
2. Run `./scripts/setup.sh --online` (Windows: `scripts\setup.cmd -Online`).
3. In `.env`, paste each key into its own line, for example `GROQ_API_KEY=your-key`. Leave the lines for services you did not sign up for empty.

You do not need all three. The app uses the keys in the order set by `LLM_PROVIDER_ORDER` (default: Groq, Mistral, then Google AI Studio). When one service reaches its limit, the app switches to the next one and shows a short notice. The interview carries on without a restart. A service that ran out for the day is skipped until its reset time (midnight UTC), even after a restart.

Without any key the app still starts, and choosing Online shows a "key is not configured" notice for 10 seconds.

### Free API keys

Each service has its own limits, and free limits change. Check the limits page on each dashboard. Keys are secret: never paste them into a chat, a commit or a screenshot.

| Service | Key goes in `.env` as | Steps to get it | Free limits (at the time of writing) | Your prompts |
|---|---|---|---|---|
| **Groq** | `GROQ_API_KEY` | 1. Open [console.groq.com](https://console.groq.com) and sign up. 2. Open **API Keys**, choose **Create API Key**, and copy it (starts `gsk_`). | Free tier, no card needed. Per-minute and per-day caps. | Groq's terms apply. |
| **Mistral AI** | `MISTRAL_API_KEY` | 1. Open [console.mistral.ai](https://console.mistral.ai) and sign up. 2. Choose the **Experiment** plan (free, no card). 3. Open **API Keys**, create a key, and copy it. | About 1 request per second and a monthly token cap. Lower priority at busy times. | Check Mistral's data settings in the console. |
| **Google AI Studio** | `GEMINI_API_KEY` | 1. Open [aistudio.google.com](https://aistudio.google.com) and sign in with a Google account. 2. Choose **Get API key**, then **Create API key**, and copy it. | Free tier with a daily request cap per model. | **Google may use prompts sent on the free tier to improve its products.** Only use this key if you are happy with that. Your name and contact details are removed first either way. |
| Cerebras (optional) | not used by the app | Not included. Cerebras no longer has a free tier: it gives a one-time $5 credit that expires after 30 days, and needs a payment method. | — | — |

Your name, email, phone, address and ID numbers are removed from every prompt before it leaves your computer, whichever service answers. The job description and your answers are still sent, so use the free keys only for practice.

### 4. Choose how LEV runs
LEV is optional but recommended. Set one option in `.env`:

| Option | Setup | Memory | How |
|---|---|---|---|
| **A1. Inside the app** | Fully offline | About 16 GB recommended; the app refuses to load it below 12 GB | `uv sync --extra voice --extra dev --extra lev`, then `LEV_MODE=local` |
| **A2. Separate server on this computer** | Fully offline | About 16 GB recommended | Run `lev serve` (below), then `LEV_MODE=http` and `LEV_URL=http://127.0.0.1:8000` |
| **A2 on another computer** (home or college network) | Offline + your scoring server | Depends on that computer | Run `lev serve --host 0.0.0.0` there, then `LEV_URL=http://<its-ip>:8000` |
| **B. Your Modal app** | Offline + your scoring server | Runs in the cloud | See [Modal](#modal-setup) below |
| **C. No LEV** | Fully offline | None | `LEV_MODE=off`; the AI model scores answers itself, which is less consistent |

The app labels the setup from the address: `127.0.0.1` or `LEV_MODE=local` is **Fully offline**. Another computer on your network or a Modal address is **Offline + your scoring server**.

**A2 setup, once:**
```bash
uv tool install "lev[serve] @ git+https://github.com/InterfazeAI/lev#subdirectory=packages/lev"
lev serve --checkpoint interfaze-ai/lev --host 127.0.0.1 --port 8000
```
Keep this running in its own terminal. The first start downloads about 8 GB of weights; `HF_HUB_OFFLINE=1` makes later starts work without internet.

**A1 details:** LEV loads in the background when the app starts, so the first answer doesn't wait for it. `/api/health` shows `loading`, then `ok`. `LEV_CACHE_DIR` changes where the weights are kept. On a computer with less than 12 GB the app won't load LEV, to avoid freezing it, and says why. Set `LEV_LOCAL_FORCE=true` only to try anyway. A1 was not tested on a 16 GB machine by the developer; it is covered by tests with a stand-in LEV.

<a id="modal-setup"></a>
**B details:** deploy LEV once under your own Modal account, then create a Proxy Auth Token in the Modal dashboard:
```bash
pip install modal && modal setup
modal deploy deploy/modal_lev.py
```
In `.env`:
```
LEV_MODE=http
LEV_URL=https://<your-workspace>--lev-server-serve.modal.run
MODAL_KEY=wk-...
MODAL_SECRET=ws-...
LEV_ALLOW_REMOTE=true
```
Your redacted answers go to your Modal app. The first request after idle can take about a minute while it wakes up. Check Modal's current pricing before you deploy. Never commit `.env`.

### 5. Start the app
```bash
./scripts/run.sh            # Windows: scripts\run.cmd
```
On Windows, use `scripts\run.cmd` from Command Prompt or PowerShell, or double-click `scripts\run.cmd` in File Explorer. Press Ctrl+C in that window to stop the app.
Open **http://127.0.0.1:5173**. The app remembers your last mode.

## Using it
- Press **Space** or the mic to start answering, and again to finish. Check the transcript, fix anything misheard, then press **Get feedback**.
- Waits you may see the first time: the Whisper model downloads once (about 500 MB), preparing an interview takes about a minute, and the first LEV score on Modal can take a minute while it wakes.
- Stop the app with Ctrl+C.
- **Quick try without speech models:** run `uv sync --extra dev` instead of the setup script. Questions use your browser's UK voice, and you type your answers.

### Setting up the interview

On the setup page, the **Job** card asks for four things:

1. **Job description**, as a link or pasted text. Required.
2. **Interview pattern** (optional, under the job description). Write what the recruiter told you, for example: "Two parts: a 45-minute Python coding test, then a system design of a rate limiter. The interviewer is a staff engineer and expects trade-offs and numbers." The text is limited to 1,500 characters. The question generator reads it as a description of the interview, not as instructions, and personal details are removed before the AI sees it.
3. **Your resume.** Required.
4. **Your own interview questions** and the GitHub profile (both optional).

What the pattern changes: the question writer uses the interview types it names and the expectations it lists, and it names the topic in each question. It does not change how many questions there are. A round always has the same number of questions (round 1 has 9, round 2 has 8, and so on), so the pattern steers which questions are asked, not how many.

How we checked it: one job description, a resume and round 2, with two runs each way, using the Groq model. Without the pattern the seven technical questions were all about Kafka, PostgreSQL and FastAPI. With the pattern, the questions included a Python coding task and a rate-limiter design (coding keyword hits went from 1 to 3 per run). This is a small check, not a measured improvement. The next step is the evaluation below.

To check it works, open http://127.0.0.1:8100/api/health. You want `ollama.ok`, `model_ready` and `lev.ok` to be `true`. The `setup` field shows which setup is active.

## Troubleshooting
| Problem | Fix |
|---|---|
| `no such file or directory: ./scripts/setup.sh` | Run `cd` into the `speakhired` folder first. Quote paths that contain spaces. |
| Windows: `cp` is not recognized, or `.env.example` is not copied | Use `copy .env.example .env` in Command Prompt or PowerShell. `cp` only works on macOS and Linux. |
| Windows: `setup.sh` or `setup.ps1` opens in Notepad, or "running scripts is disabled" | Do not run `.sh` on Windows. Use `scripts\setup.cmd` and `scripts\run.cmd`. They bypass the PowerShell script block for that run only. |
| Windows: `'uv' is not recognized`, `'npm' is not recognized`, or setup says "Could not find or install uv" | Run `winget install astral-sh.uv` and `winget install OpenJS.NodeJS.LTS` (or install them from the table above), then close the terminal, open a new PowerShell window and run `scripts\setup.cmd` again. If `uv` is still not found, add `%USERPROFILE%\.local\bin` to your PATH. |
| `uv sync` fails with "doesn't have a source distribution or wheel for the current platform" (`ctranslate2`, CPython 3.15) | uv picked a Python that is too new for the voice packages. The repo pins Python 3.13 in `.python-version`. Keep that file, then run setup again. |
| Windows: Ollama install says "You cancelled the installation" | The Ollama installer opens a window that must be accepted. Run it again and click through, or install from ollama.com/download. Online mode does not need Ollama. |
| Windows: setup says `.env.example` is missing | Run `git checkout -- .env.example`, or create an empty `.env` file. |
| Windows: port 8100 or 5173 "already in use" | An earlier run did not stop. Close the old `scripts\run.cmd` window, or run `netstat -ano \| findstr :8100` and stop that process in Task Manager. |
| `could not connect to ollama server` | Run `ollama serve`, or open the Ollama app. |
| `ollama: command not found` | Install Ollama, then open a new terminal. |
| `ollama.ok: false` or `model_ready: false` | Start Ollama and check `OLLAMA_URL`. Run `ollama pull qwen3:4b`, or set `OLLAMA_MODEL` to a model from `ollama list`. |
| `No module named 'faster_whisper'`, `'kokoro'` or `'soundfile'` | Run `uv sync --extra voice --extra dev`, then restart. |
| `metadata_errors` error when you speak | Your `av` package is too new. The voice install pins it below 19; run the sync command again. |
| Interviewer uses a robotic browser voice | Kokoro isn't installed. Install the voice extras (above). |
| Couldn't access the microphone | Allow it for the page in your browser, or type your answer. |
| `lev.ok: false` | Check `LEV_URL`, `MODAL_KEY`, `MODAL_SECRET` and `LEV_ALLOW_REMOTE`. Wait a minute if Modal is waking up, or set `LEV_MODE=off`. |
| "Key is not configured" tile | You are in Online mode without a key. Add a key such as `GROQ_API_KEY` to `.env` and restart, or switch to Offline. |
| "Every online AI service has reached its usage limit" | Each key you added has run out for now. Wait until the time shown, add another key, or switch to Offline. |
| "did not accept the key" | That service's key is wrong or was revoked. Copy it again into its own line in `.env`. |
| "Your key starts with gsk_…" | A Groq key is on another service's line. Move it to `GROQ_API_KEY`. |
| Port 5173 or 8100 already in use | Stop the old run with Ctrl+C, or `pkill -f uvicorn` and `pkill -f vite`. |
| Changed `.env` but nothing changed | Stop and restart `./scripts/run.sh` (Windows: `scripts\run.cmd`). |

## If Offline mode feels slow
Offline speed depends mostly on memory. On an 8 GB machine, a browser and an editor can push the model into slow swap memory.
1. Close other apps and browser tabs. Then run `uv run python -m speakhired.doctor --bench` (about 30 seconds) to see your speed.
2. Try a smaller model: `ollama pull qwen3:1.7b`, set `OLLAMA_MODEL=qwen3:1.7b`, and restart. It is roughly twice as fast, with simpler answers.
3. Switch to Online mode for answers in seconds.
4. In Resume Radar, untick "Use AI to review the content" for an instant score.

The app already turns off the model's hidden "thinking", keeps the model loaded for 30 minutes (`OLLAMA_KEEP_ALIVE`), caps runaway answers (`OLLAMA_MAX_TOKENS`), and shows the corrected answer before the answer to give.

## Daily English for IT
- **Levels:** *Foundation* (everyday workplace words), *Professional* (working with a team and clients; the usual interview level) and *Expert* (10+ years: architecture, reliability and leadership). Pick one at the top of the page. Each level has its own 15-item daily set and progress.
- **Each item:** hear it, say it back (spelling and spacing don't matter), then use it in a sentence. You get a grade and a stronger way to say it.
- **Spaced repetition:** items you miss come back the next day; items you know come back after longer gaps.
- **Content:** `apps/api/speakhired/data/daily.json` (181 items: 60 Foundation, 60 Professional, 61 Expert). The set comes from this file, so nothing is generated each day. To add an item, use the same fields, including `level`. `uv run --extra voice --extra dev pytest` checks each example uses its term.

## Technical words and English-only checks
- **Technical words** are kept in `apps/api/speakhired/data/termbank.json`. When the interviewer speaks, terms are said properly ("ChatGPT" as "Chat G P T"). When you speak, the recogniser is told which words to expect, and mishearings ("chat gpt", "post gress") are corrected. Add a word with its correct spelling, how it is said (`say`), and common mishearings (`heard`).
- **English-only:** the app checks the language Whisper hears, Indian scripts in your text, and a list of Indian-language words written in English letters (`apps/api/speakhired/data/indic_words.json`). A few stray words get a note with the English alternative. A mostly non-English answer must be re-recorded. Only add words that are not also English.

## Status
**Beta.** The interview pattern field is new in this version; it has tests and one small check with a real model (see *Setting up the interview*). Features and settings may change between versions.

Not yet built: automatic end-of-speech detection (you press Space to finish), sound-level pronunciation scoring (currently word-level), and an installer (setup uses the scripts).

Tested with stand-ins, so please report problems: LEV inside the app (A1) on a 16 GB machine, and the Daily English microphone and voice steps on a real Mac.

## Tests
```bash
uv run --extra voice --extra dev pytest
```
The `voice` extra is needed because one test file imports the speech packages. Without it, pytest stops at that file. The suite has 207 tests across 15 files. They cover privacy redaction, the AI provider routing and failover, the interview flow and the interview pattern, the LEV contract, speech and term correction, ATS scoring, Daily English, and the GitHub lookup. They need no Ollama, Groq, LEV or microphone.

## Evaluation: how to add an eval harness
SpeakHired has tests, but no measure of quality yet. The tests use fake models, so they cannot say whether a question is good, whether feedback helps, or whether the pattern changes the questions in the intended way. This is how to add that, in the order I would build it. **Nothing in this section is built yet** except the tests and the grounding check.

1. **Pick what to measure.** Four measures cover the product:
   - *Pattern adherence:* when a pattern is given, do the questions use the types and topics it names? This can be checked by rule for coding and design keywords, then by a judge for topic.
   - *Question relevance:* is each question about the job description and the candidate's resume, and at the right difficulty for the round?
   - *Feedback correctness and usefulness:* does the feedback name the points the answer really missed, and is the stronger answer correct? This needs a human rubric.
   - *Privacy:* does a sample resume or pattern with known names come out with none of them in any prompt? Recall on a labelled set.
2. **Write the dataset** as JSON Lines in `eval/dataset.jsonl`, one case per line:
   ```json
   {"id": "pat-001", "round": 2, "jd": "...", "resume": "...", "pattern": "...",
    "expect": {"types": ["coding", "design"], "must_mention": ["rate limit"]}}
   ```
   Start with 20 to 30 cases: some with a pattern, some without, and at least one per round. Write the expected types and topics by hand, not from the model's output.
3. **Write the graders** in `eval/graders.py`. The first two are rules and cost nothing: a keyword or regex check for the pattern's types, and a check that the expected topics appear in the questions. The third is a judge model with a written rubric for relevance and feedback quality. Calibrate the judge against a few human labels, and report how often they agree.
4. **Write the runner** in `eval/run_eval.py`. It calls `core.intake` and `core.generate_questions` the same way the route does, so the eval tests the real code path, and it writes `eval/report.json` with the score for each measure and each case.
5. **Set a gate.** For example, fail the check if pattern adherence drops below a threshold you chose from the first run. Pin the model name in the report, because hosted models change.
6. **Run the rule-based part in CI** with the fake models, so every change is checked. Run the judge-based part by hand, with a real provider, before a release, because it costs money.

Command names and file names above are the plan. Use them as the starting point, and change them when you build it.

## Tests

## Licence
SpeakHired is licensed under the [Apache License 2.0](LICENSE). You can use, modify and share it, including commercially, as long as you keep the licence and notices. It comes with no warranty.
