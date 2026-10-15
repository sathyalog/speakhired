# Starts the API and the web app. Press Ctrl+C to stop both.
# run.cmd runs this file with the execution policy bypassed for that one run.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

# Load .env into this session (skips comments and blank lines, removes surrounding quotes).
Get-Content .env -ErrorAction SilentlyContinue | ForEach-Object {
  if ($_ -match '^\s*([^#=\s][^=]*)=(.*)$') {
    $value = $Matches[2].Trim().Trim('"').Trim("'")
    [Environment]::SetEnvironmentVariable($Matches[1].Trim(), $value)
  }
}

# Ollama is only used in Offline mode. Start its server if it is installed and not already running.
if (Get-Command ollama -ErrorAction SilentlyContinue) {
  ollama list *> $null
  if ($LASTEXITCODE -ne 0) { Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden }
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "uv is not installed. Run setup.cmd first, or install uv from https://docs.astral.sh/uv/" }

# The API runs in the background. uv starts uvicorn as a child process, so stop the whole tree at the end.
$api = Start-Process uv -ArgumentList "run","uvicorn","speakhired.main:app","--app-dir","apps/api","--host","127.0.0.1","--port","8100" -NoNewWindow -PassThru
try {
  Push-Location apps/web
  try { npm run dev -- --host 127.0.0.1 } finally { Pop-Location }
} finally {
  if (-not $api.HasExited) { taskkill /T /F /PID $api.Id *> $null }
  Write-Host "Stopped the API."
}
