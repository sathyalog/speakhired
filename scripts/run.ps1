Set-Location (Join-Path $PSScriptRoot "..")
Get-Content .env -ErrorAction SilentlyContinue | ForEach-Object { if ($_ -match '^\s*([^#=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($Matches[1].Trim(), $Matches[2].Trim()) } }
# Ollama is only used in Offline mode
if (Get-Command ollama -ErrorAction SilentlyContinue) { Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden -ErrorAction SilentlyContinue }
Start-Process uv -ArgumentList "run","uvicorn","speakhired.main:app","--app-dir","apps/api","--port","8100"
Set-Location apps/web; npm run dev
