# One-command setup.   .\scripts\setup.ps1            Offline mode: Ollama on this computer (default)
#                      .\scripts\setup.ps1 -Online    Online mode: free keys (Groq, Mistral, Google AI Studio), no Ollama needed
param([switch]$Online)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$tools = @("uv", "node"); if (-not $Online) { $tools += "ollama" }
foreach ($c in $tools) { if (-not (Get-Command $c -ErrorAction SilentlyContinue)) { Write-Error "Install $c first (Offline mode needs Ollama; or run setup.ps1 -Online)"; exit 1 } }
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
uv sync --extra voice --extra dev
Push-Location apps/web; npm install; Pop-Location
New-Item -ItemType Directory -Force -Path data | Out-Null
if ($Online) {
  '{"mode": "online"}' | Set-Content data/mode.json
  uv run python -m speakhired.doctor
  if (-not (Select-String -Path .env -Pattern '^(GROQ|MISTRAL|GEMINI|XAI)_API_KEY=.+|^EXTERNAL_API_KEY=.+' -Quiet)) {
    Write-Host "`nOne more step for Online mode: add at least one free key to .env"
    Write-Host "  1. Get a free key: Groq (https://console.groq.com), Mistral (https://console.mistral.ai)"
    Write-Host "     or Google AI Studio (https://aistudio.google.com). The README has the steps."
    Write-Host "  2. Open .env and set GROQ_API_KEY=your-key (or MISTRAL_API_KEY / GEMINI_API_KEY)"
  }
  Write-Host "Done (Online mode). Start with: .\scripts\run.ps1"
} else {
  '{"mode": "offline"}' | Set-Content data/mode.json
  uv run python -m speakhired.doctor
  ollama pull qwen3:4b
  Write-Host "Done (Offline mode). Start with: .\scripts\run.ps1"
}
