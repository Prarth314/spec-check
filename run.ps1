param([int]$Port = 8001)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$projectPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $PSScriptRoot '.runtime'
    $env:UV_CACHE_DIR = Join-Path $PSScriptRoot '.uv-cache'
    uv sync --python 3.12
    if ($LASTEXITCODE -ne 0) { throw 'Dependency setup failed. Install uv or follow README.md.' }
}
Write-Host "Spec Check: http://127.0.0.1:$Port"
& $projectPython -m uvicorn spec_check.app:app --host 127.0.0.1 --port $Port
