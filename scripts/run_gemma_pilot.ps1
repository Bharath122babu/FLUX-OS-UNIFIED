param([string]$OutputDirectory, [string]$PythonExecutable)
$ErrorActionPreference='Stop'
$projectDirectory=Split-Path -Parent $PSScriptRoot
if (-not $PythonExecutable) {
    $localPython=Join-Path $projectDirectory '.venv\Scripts\python.exe'
    $PythonExecutable=if (Test-Path -LiteralPath $localPython) {$localPython} else {'python'}
}
if (-not $OutputDirectory) {
    $OutputDirectory=Join-Path $projectDirectory ('.fluxos-benchmarks\pilot-'+(Get-Date -Format 'yyyyMMdd-HHmmss'))
}
if (Test-Path -LiteralPath $OutputDirectory) {throw 'Choose a new output directory; previous experiment records must be preserved.'}
$dockerCommand=Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerCommand) {
    foreach ($dockerBinDirectory in @(
        (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin'),
        (Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin')
    )) {
        if (Test-Path -LiteralPath (Join-Path $dockerBinDirectory 'docker.exe')) {
            $env:PATH=$dockerBinDirectory+';'+$env:PATH
            $dockerCommand=Get-Command docker -ErrorAction Stop
            break
        }
    }
}
if (-not $dockerCommand) {throw 'Open Docker Desktop, then open a new terminal so docker is on PATH.'}
& $dockerCommand.Source info *> $null
if ($LASTEXITCODE -ne 0) {throw 'Docker engine is not ready. Finish Docker Desktop/WSL setup first.'}
foreach ($image in @('python:3.12-alpine','node:22-alpine')) {
    & $dockerCommand.Source image inspect $image *> $null
    if ($LASTEXITCODE -ne 0) {
        & $dockerCommand.Source pull $image
        if ($LASTEXITCODE -ne 0) {throw "Could not prepare $image"}
    }
}
& $PythonExecutable (Join-Path $PSScriptRoot 'evaluation_docker_smoke.py')
if ($LASTEXITCODE -ne 0) {throw 'Docker acceptance smoke failed; no paid calls were made.'}
$previousKey=$env:GEMINI_API_KEY
$secretPointer=[IntPtr]::Zero
try {
    if (-not $env:GEMINI_API_KEY) {
        $secretInput=Read-Host 'Google AI Studio API key (hidden; used only by this process)' -AsSecureString
        $secretPointer=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secretInput)
        $env:GEMINI_API_KEY=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($secretPointer)
    }
    Write-Host 'Running the approved four-task B0/F0 pilot: eight attempted tasks at most.'
    & $PythonExecutable -m fluxos.evaluation run --output $OutputDirectory --execute
    $pilotExitCode=$LASTEXITCODE
    Write-Host "Evidence: $OutputDirectory\results.json (exit $pilotExitCode)"
} finally {
    if ($secretPointer -ne [IntPtr]::Zero) {[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secretPointer)}
    $env:GEMINI_API_KEY=$previousKey
}
exit $pilotExitCode
