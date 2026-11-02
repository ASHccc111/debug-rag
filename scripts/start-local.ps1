param([switch]$ApiOnly)

$ErrorActionPreference = 'Stop'
$projectRoot = (Get-Item -LiteralPath (Split-Path -Parent $PSScriptRoot)).FullName
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$baseUrl = 'http://127.0.0.1:8001'

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Project .venv is missing. Run uv sync as described in README first.'
}

Push-Location $projectRoot
try {
    $runtimePath = & $pythonPath -X utf8 -c "from debug_rag.settings import Settings; print(Settings().runtime_dir)" 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $runtimePath) { throw 'Invalid project configuration; inspect local .env without sharing secrets.' }
    $runtimePath = [string]$runtimePath
} finally { Pop-Location }

try {
    $health = Invoke-RestMethod -Uri "$baseUrl/health/live" -TimeoutSec 3
} catch { $health = $null }
if ($health -and $health.alive) {
    if ($health.project_root -ne $projectRoot) {
        throw 'Port 8001 belongs to a different project directory. Stop that project before starting this one.'
    }
}
if (-not ($health -and $health.alive)) {
    $portProbe = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 8001)
    try { $portProbe.Start() }
    catch { throw 'Port 8001 is occupied by another service; it was not stopped.' }
    finally { $portProbe.Stop() }
}

if (-not $ApiOnly) {
    Push-Location $projectRoot
    try {
        & docker compose -f infra/milvus/compose.yaml up -d --wait --wait-timeout 120
        if ($LASTEXITCODE -ne 0) {
            throw 'Milvus did not start. Start Docker Desktop, then run this script again.'
        }
    } finally {
        Pop-Location
    }
}

if ($health -and $health.alive) {
    Write-Output "Backend already running from this project: $baseUrl"
    return
}

New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$suffix = [guid]::NewGuid().ToString('N').Substring(0, 8)
$stdoutPath = Join-Path $runtimePath "server-$stamp-$suffix.stdout.log"
$stderrPath = Join-Path $runtimePath "server-$stamp-$suffix.stderr.log"
$serverProcess = Start-Process -FilePath $pythonPath -WorkingDirectory $projectRoot `
    -ArgumentList @('-X', 'utf8', '-m', 'uvicorn', 'debug_rag.main:app', '--host', '127.0.0.1', '--port', '8001', '--workers', '1') `
    -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru

$processRecord = [ordered]@{
    pid = $serverProcess.Id
    url = $baseUrl
    started_at = (Get-Date).ToString('o')
    process_started_utc = $serverProcess.StartTime.ToUniversalTime().ToString('o')
    project_root = $projectRoot
    python = $pythonPath
    stdout = $stdoutPath
    stderr = $stderrPath
}
$processRecord | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtimePath 'server-process.json') -Encoding utf8

for ($attempt = 0; $attempt -lt 25; $attempt++) {
    Start-Sleep -Milliseconds 500
    $serverProcess.Refresh()
    if ($serverProcess.HasExited) {
        throw "Backend exited. Check $stderrPath"
    }
    try {
        $health = Invoke-RestMethod -Uri "$baseUrl/health/live" -TimeoutSec 2
        if ($health.alive -and $health.project_root -eq $projectRoot) {
            Write-Output "Backend started: $baseUrl (PID $($serverProcess.Id))"
            Write-Output "Log: $stderrPath"
            return
        }
    } catch {
        # During startup only; real API errors are not hidden by the web application.
    }
}
throw "Backend did not become live. Check $stderrPath"
