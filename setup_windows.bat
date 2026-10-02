@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3.12 -m venv .venv 2>nul || py -3 -m venv .venv
) else (
  python -m venv .venv
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt -c constraints.txt

if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" (
  echo Tesseract encontrado.
) else (
  where tesseract >nul 2>nul
  if errorlevel 1 (
    echo.
    echo ADVERTENCIA: No se encontro Tesseract OCR.
    echo Instala Tesseract para Windows con el idioma espanol antes de usar OCR.
  )
)

echo.
echo Instalacion terminada. Copia los PDF a data\inbox y ejecuta run_windows.bat
pause
