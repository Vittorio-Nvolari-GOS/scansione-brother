@echo off
REM ============================================================
REM  Avvia_ScanApp.bat - avvia l'app grafica di scansione.
REM  Deve stare nella stessa cartella di scan_gui.py
REM ============================================================
cd /d "%~dp0"

set "PYEXE="
where py >nul 2>nul && set "PYEXE=py"
if not defined PYEXE (
    where python >nul 2>nul && set "PYEXE=python"
)
if defined PYEXE (
    %PYEXE% --version >nul 2>nul
    if errorlevel 1 set "PYEXE="
)
if not defined PYEXE (
    echo [ERRORE] Python non trovato. Esegui prima Avvia_Scansione.bat
    echo nella cartella superiore: installa Python automaticamente.
    pause
    exit /b 1
)

%PYEXE% scan_gui.py
if errorlevel 1 (
    echo.
    echo [ERRORE] L'app si e' chiusa con un errore. Vedi messaggi sopra.
    pause
)
