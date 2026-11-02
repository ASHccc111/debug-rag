$ErrorActionPreference = 'Stop'
$projectRoot = (Get-Item -LiteralPath (Split-Path -Parent $PSScriptRoot)).FullName
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
Push-Location $projectRoot
try {
    $runtimePath = & $pythonPath -X utf8 -c "from debug_rag.settings import Settings; print(Settings().runtime_dir)" 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $runtimePath) { throw 'Invalid project configuration.' }
} finally { Pop-Location }
$recordPath = Join-Path ([string]$runtimePath) 'server-process.json'
if (-not (Test-Path -LiteralPath $recordPath)) { throw 'No server process record for this project.' }
$record = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
if ($record.project_root -ne $projectRoot -or $record.python -ne $pythonPath) {
    throw 'Process record belongs to another project; no process was stopped.'
}
$ownedProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($record.pid)"
if (-not $ownedProcess) { Write-Output 'Recorded API process is already stopped.'; return }
if ($ownedProcess.ExecutablePath -ne $pythonPath -or $ownedProcess.CommandLine -notlike '*uvicorn debug_rag.main:app*') {
    throw 'PID no longer matches this project API; no process was stopped.'
}
$actual = Get-Process -Id $record.pid
# ConvertFrom-Json may already return DateTime. Parsing its culture-formatted
# string again loses the UTC kind and shifts it by the local timezone twice.
$recordedStart = [datetimeoffset]$record.process_started_utc
if ([Math]::Abs(($actual.StartTime.ToUniversalTime() - $recordedStart.UtcDateTime).TotalSeconds) -gt 2) {
    throw 'PID was reused; no process was stopped.'
}
# Windows venv launcher can have a backing Python child. Never stop unrelated children.
Get-CimInstance Win32_Process -Filter "ParentProcessId = $($record.pid)" |
    Where-Object { $_.CommandLine -like '*uvicorn debug_rag.main:app*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }
Stop-Process -Id $record.pid -ErrorAction SilentlyContinue
Write-Output 'Project API stopped. Milvus data and Docker volume are preserved.'
