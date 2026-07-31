@echo off
setlocal
REM Cierra todas las instancias del Renombrador PDF (puertos 8765-8799).
REM Verifica cada puerto con /api/health para no tocar otros programas.
echo Buscando instancias del Renombrador PDF en los puertos 8765-8799...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$found = $false;" ^
 "Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -ge 8765 -and $_.LocalPort -le 8799 } | Sort-Object LocalPort -Unique | ForEach-Object {" ^
 "  $port = $_.LocalPort; $ownerPid = $_.OwningProcess;" ^
 "  try { $h = Invoke-RestMethod ('http://127.0.0.1:' + $port + '/api/health') -TimeoutSec 2 } catch { return };" ^
 "  $esRenombrador = ($h.app_id -eq 'renombrador-pdf') -or ($h.ok -and $h.input_dir -and $h.ocr_languages);" ^
 "  if ($esRenombrador) { Stop-Process -Id $ownerPid -Force; Write-Host ('Cerrado: puerto ' + $port + ' (PID ' + $ownerPid + ') -> ' + $h.input_dir); $found = $true }" ^
 "};" ^
 "if (-not $found) { Write-Host 'No hay ninguna instancia del Renombrador PDF corriendo.' }"
echo.
if not "%~1"=="/nopause" pause
