@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM  Avvia_Scansione.bat
REM  Doppio click per lanciare la scansione Brother + OCR + LLM.
REM  Deve trovarsi nella stessa cartella di scan_brother_ai.py
REM
REM  BOOTSTRAP: se Python non e' presente, prova a installarlo
REM  automaticamente via winget (Windows 10/11).
REM ============================================================

REM Vai nella cartella dello script (anche se lanciato da altrove)
cd /d "%~dp0"

echo ============================================
echo   Scansione Brother -^> OCR -^> nome via LLM
echo ============================================
echo.

REM ------------------------------------------------------------
REM 1) Individua un interprete Python REALMENTE funzionante.
REM    NB: su Windows esiste un "alias" (WindowsApps\python.exe)
REM    che risponde a "where python" ma NON e' Python: apre lo
REM    Store e fallisce. Per questo ogni candidato viene VALIDATO
REM    eseguendolo davvero (--version) nella subroutine :try_py.
REM ------------------------------------------------------------
call :find_python
if defined PYEXE goto :run

REM ------------------------------------------------------------
REM 2) Python non trovato: prova a installarlo via winget
REM ------------------------------------------------------------
echo [INFO] Python non trovato. Provo a installarlo con winget...
where winget >nul 2>nul
if errorlevel 1 (
    echo.
    echo [ERRORE] winget non e' disponibile e Python non e' installato.
    echo   - Aggiorna "App Installer" dal Microsoft Store per avere winget,
    echo     oppure installa Python manualmente da https://www.python.org/
    echo     ^(spunta "Add python.exe to PATH" durante l'installazione^).
    echo.
    pause
    exit /b 1
)

winget install --id Python.Python.3.12 -e --silent ^
    --accept-package-agreements --accept-source-agreements

echo.
echo [INFO] Installazione Python completata.

REM Ritenta la ricerca (validata) dopo l'installazione
call :find_python
if defined PYEXE goto :run

REM ------------------------------------------------------------
REM 3) Ancora non visibile in questa sessione: rilancia UNA volta
REM    il .bat in una nuova finestra (eredita il PATH aggiornato).
REM    La guardia SCAN_BOOTSTRAP evita loop infiniti.
REM ------------------------------------------------------------
if not defined SCAN_BOOTSTRAP (
    echo.
    echo [INFO] Rilancio automatico per aggiornare il PATH...
    set "SCAN_BOOTSTRAP=1"
    start "" /wait cmd /c "%~f0" %*
    exit /b 0
)

echo.
echo [ATTENZIONE] Python e' stato installato ma non e' ancora visibile
echo nemmeno dopo il rilancio automatico. CHIUDI questa finestra e fai di
echo nuovo doppio click su Avvia_Scansione.bat.
echo.
pause
exit /b 0

REM ============================================================
REM  ESECUZIONE
REM ============================================================
:run
echo [INFO] Uso Python: %PYEXE%
echo.

REM Avvia lo script (che auto-installa moduli Python, Tesseract,
REM Ollama e il modello LLM). Gli argomenti del .bat sono inoltrati.
%PYEXE% scan_brother_ai.py %*
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo [ERRORE] Lo script si e' chiuso con codice %RC%.
    echo Controlla i messaggi qui sopra e il file di log in:
    echo   %USERPROFILE%\Scansioni\log\scan_brother_ai.log
    echo.
    pause
)

endlocal
exit /b 0

REM ============================================================
REM  SUBROUTINE: trova un Python valido e lo mette in PYEXE.
REM  Ordine di priorita' (l'alias dello Store viene evitato
REM  perche' NON supera la validazione --version):
REM   1) launcher "py"
REM   2) percorsi tipici di installazione
REM   3) "python" nel PATH (validato)
REM ============================================================
:find_python
set "PYEXE="

REM 1) Python launcher
call :try_py "py"
if defined PYEXE exit /b 0

REM 2) Percorsi tipici (per-utente e per-macchina)
for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%ProgramFiles%\Python313\python.exe"
    "%ProgramFiles%\Python312\python.exe"
    "%ProgramFiles%\Python311\python.exe"
) do (
    if exist "%%~P" (
        call :try_py "%%~P"
        if defined PYEXE exit /b 0
    )
)

REM 3) "python" nel PATH (validato per escludere l'alias dello Store)
call :try_py "python"
if defined PYEXE exit /b 0

exit /b 0

REM ------------------------------------------------------------
REM  SUBROUTINE: valida un candidato eseguendo "<cand> --version".
REM  Se funziona, imposta PYEXE. Sopprime l'output dell'alias Store.
REM ------------------------------------------------------------
:try_py
"%~1" --version >nul 2>nul
if not errorlevel 1 set "PYEXE=%~1"
exit /b 0
