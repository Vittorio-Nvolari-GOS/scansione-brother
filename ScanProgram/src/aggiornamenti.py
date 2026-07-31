# -*- coding: utf-8 -*-
"""
============================================================================
 aggiornamenti.py - Controllo e installazione aggiornamenti da GitHub Releases
----------------------------------------------------------------------------
 All'avvio l'app chiede a GitHub qual e' l'ultima versione pubblicata. Se e'
 piu' recente di quella in esecuzione, propone di scaricarla e installarla.

 Funzionamento dell'installazione (eseguibile singolo):
   1) scarica il nuovo .exe in una cartella temporanea
   2) scrive uno script .bat che attende la chiusura dell'app, sostituisce il
      vecchio .exe con quello nuovo e riavvia il programma
   3) chiude l'app e lascia lavorare lo script
 Serve questo giro perche' un programma in esecuzione non puo' sovrascriversi.
============================================================================
"""

import os
import sys
import json
import tempfile
import subprocess
import urllib.request

# Versione dell'applicazione: va aumentata a ogni rilascio.
VERSIONE = "1.0.2"

# Repository GitHub da cui scaricare gli aggiornamenti (owner/nome).
# Viene sostituito automaticamente in fase di pubblicazione.
REPO = "Vittorio-Nvolari-GOS/scansione-brother"

API_ULTIMA = "https://api.github.com/repos/{repo}/releases/latest"
NOME_ASSET = "ScansioneBrother.exe"
TIMEOUT = 10


def _versione_tupla(v):
    """'1.2.3' -> (1, 2, 3). Ignora una eventuale 'v' iniziale."""
    v = (v or "").strip().lstrip("vV")
    numeri = []
    for pezzo in v.split("."):
        cifre = "".join(c for c in pezzo if c.isdigit())
        numeri.append(int(cifre) if cifre else 0)
    while len(numeri) < 3:
        numeri.append(0)
    return tuple(numeri[:3])


def piu_recente(remota, locale=None):
    """True se 'remota' e' una versione successiva a quella locale.
    NB: la versione locale si legge al momento della chiamata (non come valore
    predefinito), cosi' resta corretta anche se VERSIONE viene modificata."""
    return _versione_tupla(remota) > _versione_tupla(
        locale if locale is not None else VERSIONE)


def controlla(repo=None, log=None):
    """Interroga GitHub. Ritorna un dizionario con i dati dell'aggiornamento
    disponibile, oppure None se non ce n'e' (o se la rete non risponde).

    Il controllo non deve MAI bloccare l'avvio: ogni errore viene ignorato."""
    repo = repo or REPO
    if "OWNER/" in repo:                       # repository non ancora configurato
        return None
    try:
        richiesta = urllib.request.Request(
            API_ULTIMA.format(repo=repo),
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": "ScansioneBrother"})
        with urllib.request.urlopen(richiesta, timeout=TIMEOUT) as r:
            dati = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        if log:
            log.debug("Controllo aggiornamenti non riuscito: %s", e)
        return None

    tag = dati.get("tag_name") or ""
    if not piu_recente(tag):
        if log:
            log.info("Nessun aggiornamento: sei alla versione piu' recente (%s).",
                     VERSIONE)
        return None

    url = None
    for asset in dati.get("assets", []):
        if asset.get("name") == NOME_ASSET:
            url = asset.get("browser_download_url")
            break
    if not url:
        if log:
            log.warning("Release %s trovata ma senza il file %s.", tag, NOME_ASSET)
        return None

    if log:
        log.info("Aggiornamento disponibile: %s (in uso: %s)", tag, VERSIONE)
    return {"versione": tag,
            "url": url,
            "note": (dati.get("body") or "").strip(),
            "pubblicata": dati.get("published_at", "")}


def scarica(url, destinazione, progresso=None):
    """Scarica il file mostrando l'avanzamento tramite la callback
    progresso(scaricati, totale)."""
    richiesta = urllib.request.Request(
        url, headers={"User-Agent": "ScansioneBrother"})
    with urllib.request.urlopen(richiesta, timeout=60) as r:
        totale = int(r.headers.get("Content-Length", 0))
        scaricati = 0
        with open(destinazione, "wb") as f:
            while True:
                blocco = r.read(128 * 1024)
                if not blocco:
                    break
                f.write(blocco)
                scaricati += len(blocco)
                if progresso:
                    progresso(scaricati, totale)
    return destinazione


def installa(nuovo_exe, log=None):
    """Sostituisce l'eseguibile in uso con quello nuovo e riavvia l'app.

    Un programma in esecuzione non puo' sovrascrivere se stesso: si delega a
    uno script .bat che aspetta la chiusura, scambia i file e riavvia."""
    if not getattr(sys, "frozen", False):
        raise RuntimeError("L'aggiornamento automatico funziona solo "
                           "sull'eseguibile compilato.")

    corrente = sys.executable
    pid = os.getpid()
    bat = os.path.join(tempfile.gettempdir(), "aggiorna_scansione.bat")

    contenuto = f"""@echo off
rem Attende la chiusura dell'applicazione, poi sostituisce l'eseguibile.
echo Aggiornamento in corso, attendere...
:attendi
tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto attendi
)
timeout /t 1 /nobreak >nul
move /y "{nuovo_exe}" "{corrente}" >nul
if errorlevel 1 (
    echo [ERRORE] Impossibile sostituire il programma.
    echo Chiudi l'applicazione e riprova, oppure copia a mano:
    echo   da:  {nuovo_exe}
    echo   a :  {corrente}
    pause
    exit /b 1
)
start "" "{corrente}"
del "%~f0"
"""
    with open(bat, "w", encoding="ascii", errors="ignore") as f:
        f.write(contenuto)

    if log:
        log.info("Avvio dello script di aggiornamento: %s", bat)
    subprocess.Popen(["cmd", "/c", bat],
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return True
