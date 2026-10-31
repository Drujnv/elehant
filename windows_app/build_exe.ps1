# Сборка Elehant.exe (Windows x64).
# Запуск: powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = "py"

& $py -m venv "$here\.venv"
& "$here\.venv\Scripts\python.exe" -m pip install --upgrade pip
& "$here\.venv\Scripts\python.exe" -m pip install -r "$here\requirements.txt"

& "$here\.venv\Scripts\pyinstaller.exe" `
  --noconfirm --onefile --windowed `
  --name Elehant `
  --paths "$here" `
  --add-data "$here\..\windows;windows" `
  "$here\elehant_app.py"

Write-Host "Готово: $here\dist\Elehant.exe"
