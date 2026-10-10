# One-command setup.   .\scripts\setup.ps1            Offline mode: Ollama on this computer (default)
#                      .\scripts\setup.ps1 -Online    Online mode: Groq or Grok with your own key, no Ollama needed
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
  if (-not (Select-String -Path .env -Pattern '^EXTERNAL_API_KEY=.+' -Quiet)) {
    Write-Host "`nOne more step for Online mode: add your key to .env"
    Write-Host "  1. Get a free key at https://console.groq.com (Groq), or https://console.x.ai (Grok)"
    Write-Host "  2. Open .env and set EXTERNAL_API_KEY=your-key"
  }
  Write-Host "Done (Online mode). Start with: .\scripts\run.ps1"
} else {
  '{"mode": "offline"}' | Set-Content data/mode.json
  uv run python -m speakhired.doctor
  ollama pull qwen3:4b
  Write-Host "Done (Offline mode). Start with: .\scripts\run.ps1"
}
