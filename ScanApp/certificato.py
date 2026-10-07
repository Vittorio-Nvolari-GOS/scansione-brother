# -*- coding: utf-8 -*-
"""
============================================================================
 certificato.py - Installazione automatica del certificato di firma
----------------------------------------------------------------------------
 L'eseguibile e' firmato con un certificato interno (Certificato/*.cer):
 finche' Windows non lo considera attendibile, segnala l'app come "da
 editore sconosciuto". In passato bisognava eseguire a mano, da
 amministratore, Installa_Certificato.ps1 — e rifarlo ogni volta che il
 certificato cambiava (es. v1.1.0).

 Da qui in poi l'app se ne accorge da sola: ad ogni avvio controlla se il
 certificato con cui e' firmata l'ESEGUIBILE ATTUALE e' gia' fra quelli
 attendibili sul PC; se non lo e' (prima installazione, o perche' nel
 frattempo e' uscita una firma nuova), chiede una volta il permesso e la
 installa, con un'unica richiesta di Windows (UAC) al posto dei passaggi
 manuali.
============================================================================
"""

import ctypes
import hashlib
import os
import subprocess
import sys

NOME_CER = "ScansioneBrother.cer"


def percorso_certificato():
    """Trova il .cer accanto all'eseguibile (bundle PyInstaller) o nel
    sorgente. Ritorna None se non lo trova: niente da installare."""
    candidati = []
    if getattr(sys, "_MEIPASS", None):
        candidati.append(os.path.join(sys._MEIPASS, NOME_CER))
    if getattr(sys, "frozen", False):
        base_exe = os.path.dirname(sys.executable)
        candidati.append(os.path.join(base_exe, "Certificato", NOME_CER))
    base_sorgente = os.path.dirname(os.path.abspath(__file__))
    candidati.append(os.path.join(os.path.dirname(base_sorgente),
                                  "Certificato", NOME_CER))
    for c in candidati:
        if os.path.isfile(c):
            return c
    return None


def impronta(percorso_cer):
    """Impronta digitale (SHA1, come la mostra certmgr/certutil) del
    certificato: il file .cer e' gia' la forma binaria (DER), quindi basta
    l'hash dei byte grezzi."""
    with open(percorso_cer, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest().upper()


def gia_attendibile(percorso_cer, log=None):
    """True se il certificato risulta gia' fra le Autorita' di
    certificazione radice attendibili del computer (certutil, incluso in
    ogni Windows, lo cerca per impronta)."""
    try:
        esito = subprocess.run(
            ["certutil", "-store", "Root", impronta(percorso_cer)],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return esito.returncode == 0
    except Exception as e:
        if log:
            log.debug("Controllo certificato non riuscito: %s", e)
        # In dubbio meglio non insistere ad ogni avvio con una richiesta di
        # amministratore: se il controllo fallisce si assume gia' a posto.
        return True


def installa(percorso_cer, log=None):
    """Installa il certificato fra le Autorita' radice e gli Editori
    attendibili del computer, con un'unica elevazione (UAC): l'utente non
    deve piu' cercare ed eseguire lo script a mano. Ritorna True se la
    richiesta di elevazione e' partita (l'esito dipende poi dalla risposta
    dell'utente al prompt di Windows, che resta sempre necessario: non si
    puo' e non si deve installare un certificato radice senza il consenso
    esplicito di chi usa il PC)."""
    comando = (
        f"Import-Certificate -FilePath '{percorso_cer}' "
        f"-CertStoreLocation Cert:\\LocalMachine\\Root | Out-Null; "
        f"Import-Certificate -FilePath '{percorso_cer}' "
        f"-CertStoreLocation Cert:\\LocalMachine\\TrustedPublisher | Out-Null"
    )
    try:
        esito = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", "powershell.exe",
            f'-NoProfile -ExecutionPolicy Bypass -Command "{comando}"',
            None, 0)
    except Exception as e:
        if log:
            log.warning("Elevazione per il certificato non riuscita: %s", e)
        return False
    # ShellExecuteW ritorna un valore > 32 se il processo e' partito; valori
    # piu' bassi segnalano un errore (incluso l'utente che nega lo UAC).
    avviato = esito > 32
    if log:
        log.info("Installazione certificato richiesta (avviata: %s)", avviato)
    return avviato


def controlla_e_installa(log, chiedi_conferma):
    """Punto d'ingresso per l'avvio dell'app: se serve, chiede conferma
    all'utente (tramite 'chiedi_conferma(messaggio) -> bool') e installa.
    Non fa nulla se il certificato non si trova o e' gia' attendibile."""
    cer = percorso_certificato()
    if not cer:
        return
    if gia_attendibile(cer, log):
        return
    if not chiedi_conferma(
            "Per evitare che Windows segnali l'app come non sicura, va "
            "installato (una volta sola, o quando cambia) il certificato "
            "di firma.\n\nVuoi installarlo ora? Windows chiedera' la "
            "conferma di amministratore."):
        log.info("Installazione del certificato rimandata dall'utente.")
        return
    installa(cer, log)
