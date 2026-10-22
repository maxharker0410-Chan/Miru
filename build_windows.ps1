param([switch]$SkipDependencies)
$ErrorActionPreference = "Stop"
$TaskBuildRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
Set-Location -LiteralPath $TaskBuildRoot
$TaskPython = Join-Path $TaskBuildRoot ".venv-windows/Scripts/python.exe"
if (-not (Test-Path -LiteralPath $TaskPython)) {
    python -m venv (Join-Path $TaskBuildRoot ".venv-windows")
    if ($LASTEXITCODE -ne 0) { throw "Creating Python environment failed." }
}
if (-not $SkipDependencies) {
    & $TaskPython -m pip install -r requirements.txt "pyinstaller>=6.11,<7"
    if ($LASTEXITCODE -ne 0) { throw "Installing dependencies failed." }
}
& $TaskPython -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed." }
& $TaskPython -m PyInstaller schat_windows.spec --clean --noconfirm
if ($LASTEXITCODE -ne 0) { throw "Windows build failed." }
Write-Output "S.Chat Windows build: dist/S.Chat"
