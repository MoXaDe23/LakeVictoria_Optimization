param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectDir = $PSScriptRoot
$pythonExe = Join-Path $projectDir '.venv\Scripts\python.exe'
$appPath = Join-Path $projectDir 'dashboard\app.py'
$logDir = Join-Path $projectDir 'outputs\observatory'
$url = 'http://localhost:5006/app'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw 'The project environment is missing. Follow dashboard/README.md to install dependencies.'
}
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$ready = $false
try {
    $response = Invoke-WebRequest -Uri $url -TimeoutSec 30
    $ready = $response.StatusCode -eq 200 -and $response.Content.Contains('Lake Victoria')
} catch {}
if (-not $ready) {
    $listener = Get-NetTCPConnection -LocalPort 5006 -State Listen -ErrorAction SilentlyContinue
    if ($listener) { throw 'Port 5006 is already in use by another application. Nothing was stopped.' }
    $arguments = @('-m', 'panel', 'serve', ('"' + $appPath + '"'), '--address=127.0.0.1', '--port=5006', '--allow-websocket-origin=localhost:5006', '--allow-websocket-origin=127.0.0.1:5006')
    $process = Start-Process -FilePath $pythonExe -ArgumentList $arguments -WorkingDirectory $projectDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDir 'server.stdout.log') -RedirectStandardError (Join-Path $logDir 'server.stderr.log')
    $process.Id | Set-Content -LiteralPath (Join-Path $logDir 'server.pid')
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 500
        try {
            $response = Invoke-WebRequest -Uri $url -TimeoutSec 30
            if ($response.StatusCode -eq 200 -and $response.Content.Contains('Lake Victoria')) { $ready = $true; break }
        } catch {}
        if ($process.HasExited) { break }
    }
    if (-not $ready) { throw "The dashboard did not start. Read outputs/observatory/server.stderr.log." }
}
Write-Host "Lake Victoria Observatory is running: $url"
Write-Host 'This address works on this computer. Keep the background process running.'
if (-not $NoBrowser) { Start-Process $url }
