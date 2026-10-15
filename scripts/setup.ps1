# One-command setup.   .\scripts\setup.cmd            Offline mode: Ollama on this computer (default)
#                      .\scripts\setup.cmd -Online    Online mode: free keys (Groq, Mistral, Google AI Studio), no Ollama needed
# setup.cmd runs this file with the execution policy bypassed for that one run, so Windows does not block it.
param([switch]$Online)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

# Native commands (uv, npm, ollama) do not stop the script on failure, so check their exit code.
function Invoke-Checked {
  param([string]$Description, [scriptblock]$Command)
  Write-Host "-> $Description"
  & $Command
  if ($LASTEXITCODE -ne 0) { throw "$Description failed (exit code $LASTEXITCODE)" }
}

# Write JSON as UTF-8 without a byte order mark, which Python's json module reads reliably.
function Write-Utf8NoBom {
  param([string]$Path, [string]$Text)
  [System.IO.File]::WriteAllText((Join-Path (Get-Location) $Path), $Text, (New-Object System.Text.UTF8Encoding $false))
}

# Reload PATH from Windows, so tools installed after this window opened are found.
function Update-SessionPath {
  $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
  $user = [Environment]::GetEnvironmentVariable("Path", "User")
  $env:Path = (@($machine, $user, "$env:USERPROFILE\.local\bin") | Where-Object { $_ }) -join ";"
}

# winget package ids for the tools this script needs.
$wingetIds = @{ uv = "astral-sh.uv"; node = "OpenJS.NodeJS.LTS"; ollama = "Ollama.Ollama" }

$tools = @("uv", "node"); if (-not $Online) { $tools += "ollama" }
Update-SessionPath
foreach ($c in $tools) {
  if (Get-Command $c -ErrorAction SilentlyContinue) { continue }
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host "-> $c not found. Installing it with winget..."
    winget install --id $wingetIds[$c] -e --accept-package-agreements --accept-source-agreements
    Update-SessionPath
  }
  if (-not (Get-Command $c -ErrorAction SilentlyContinue)) {
    throw "Could not find or install $c. Install it by hand (README, step 1), then open a new PowerShell window so PATH is refreshed and run setup again. Offline mode needs Ollama; or run setup.cmd -Online."
  }
}

if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "Created .env from .env.example" }
Invoke-Checked "Installing Python packages (uv sync)" { uv sync --extra voice --extra dev }
Invoke-Checked "Installing web packages (npm install)" { Push-Location apps/web; try { npm install } finally { Pop-Location } }
New-Item -ItemType Directory -Force -Path data | Out-Null

if ($Online) {
  Write-Utf8NoBom "data/mode.json" '{"mode": "online"}'
  Invoke-Checked "Checking the setup (doctor)" { uv run python -m speakhired.doctor }
  if (-not (Select-String -Path .env -Pattern '^(GROQ|MISTRAL|GEMINI|XAI)_API_KEY=.+|^EXTERNAL_API_KEY=.+' -Quiet)) {
    Write-Host "`nOne more step for Online mode: add at least one free key to .env"
    Write-Host "  1. Get a free key: Groq (https://console.groq.com), Mistral (https://console.mistral.ai)"
    Write-Host "     or Google AI Studio (https://aistudio.google.com). The README has the steps."
    Write-Host "  2. Open .env (Notepad is fine) and set GROQ_API_KEY=your-key (or MISTRAL_API_KEY / GEMINI_API_KEY)"
  }
  Write-Host "Done (Online mode). Start with: .\scripts\run.cmd"
} else {
  Write-Utf8NoBom "data/mode.json" '{"mode": "offline"}'
  Invoke-Checked "Checking the setup (doctor)" { uv run python -m speakhired.doctor }
  Invoke-Checked "Downloading the Ollama model (qwen3:4b, about 2.5 GB, once)" { ollama pull qwen3:4b }
  Write-Host "Done (Offline mode). Start with: .\scripts\run.cmd"
}
