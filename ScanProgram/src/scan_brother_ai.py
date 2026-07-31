# -*- coding: utf-8 -*-
"""
============================================================================
 scan_brother_ai.py
 Scansione da scanner Brother (WIA) + OCR (Tesseract) + naming via LLM locale
 (Ollama), salvataggio PDF con nome riconosciuto automaticamente.
 Target: Windows 10/11.
============================================================================

----------------------------------------------------------------------------
 ISTRUZIONI DI INSTALLAZIONE (Windows)
----------------------------------------------------------------------------
 NOVITA': con CONFIG["AUTO_INSTALL"] = True (default) lo script prova a
 installare DA SOLO cio' che manca al primo avvio:
   - moduli Python (pip),
   - Tesseract-OCR (winget) + pacchetto lingua ita (download automatico),
   - Ollama (winget) + avvio servizio + 'ollama pull' del modello.
 Requisiti minimi perche' l'auto-install funzioni:
   - Python gia' installato (serve per eseguire lo script);
   - 'winget' presente (Windows 10/11 aggiornati: "App Installer" dallo Store);
   - connessione a Internet;
   - a volte serve avviare lo script come AMMINISTRATORE (per scrivere in
     "C:\\Program Files\\...") e/o RIAVVIARE il terminale dopo l'installazione
     di Tesseract/Ollama perche' il PATH venga aggiornato.
 Se preferisci fare tutto a mano, metti AUTO_INSTALL = False e segui i passi:

 1) Python 3.9+ per Windows (da https://www.python.org/, spunta "Add to PATH").

 2) Moduli Python (apri PowerShell o cmd):
        pip install pywin32 img2pdf pillow pytesseract requests
    NB: pywin32 serve per pilotare WIA via COM. Se dopo l'installazione COM
        desse errori, esegui una volta (come amministratore):
        python -m pywin32_postinstall -install

 3) Tesseract-OCR per Windows:
        - Scarica l'installer (UB-Mannheim):
          https://github.com/UB-Mannheim/tesseract/wiki
        - Durante l'installazione seleziona i pacchetti lingua "Italian" (ita)
          e "English" (eng).
        - Percorso di default atteso:
          C:\\Program Files\\Tesseract-OCR\\tesseract.exe
          (configurabile qui sotto in CONFIG -> TESSERACT_PATH)

 4) Ollama per Windows:
        - Scarica e installa da https://ollama.com/download
        - Avvia Ollama (di norma parte come servizio su http://localhost:11434)
        - Scarica un modello leggero:
              ollama pull llama3.2:3b
          oppure:
              ollama pull qwen2.5:3b

 5) (OPZIONALE) NAPS2 come fallback allo scanner:
        - Installa NAPS2 (https://www.naps2.com/)
        - Fornisce naps2.console.exe per scansione da riga di comando.
        - Vedi la funzione scansione_naps2_fallback() piu' in basso.

----------------------------------------------------------------------------
 AVVIO
----------------------------------------------------------------------------
 - Doppio click su "Avvia_Scansione.bat" (consigliato), oppure:
        python scan_brother_ai.py
 - Parametri opzionali da riga di comando:
        python scan_brother_ai.py --device-id "{ID}"  (forza un device)
        python scan_brother_ai.py --naps2             (usa il fallback NAPS2)
        python scan_brother_ai.py --list-devices      (elenca i device WIA)
============================================================================
"""

import os
import sys
import re
import json
import time
import logging
import argparse
import tempfile
import subprocess
from datetime import datetime

# ===========================================================================
# CONFIG  -- Modifica qui i parametri principali
# ===========================================================================
CONFIG = {
    # ID del device WIA da usare. Se vuoto ("") lo script rileva/chiede il Brother.
    # Puoi ottenerlo con: python scan_brother_ai.py --list-devices
    "DEVICE_ID": "",
    # Nome dello scanner scelto (solo per mostrarlo nell'interfaccia)
    "DEVICE_NAME": "",

    # Preferenza sul nome del produttore per l'auto-rilevamento
    "DEVICE_NAME_HINT": "brother",

    # Parametri di scansione
    "DPI": 400,                 # risoluzione (400 dpi: buona resa sulle tessere)
    "COLOR_MODE": "RGB",        # "RGB" = colore 24 bit (8 bit x canale). Alt.: "Grayscale", "BlackWhite"
    "PAGE_SIZE": "A4",          # A4 (usato per calcolo area flatbed)
    # Origine documenti:
    #   "Auto"    -> se l'ADF (alimentatore sopra) ha fogli caricati usa quello,
    #                altrimenti ripiega sul piano (flatbed). CONSIGLIATO.
    #   "Feeder"  -> forza l'ADF
    #   "Flatbed" -> forza il piano
    "SOURCE": "Auto",
    "MULTIPAGE": True,          # True = da Flatbed chiede se ci sono altri fogli

    # Cartelle
    "OUTPUT_DIR": os.path.join(os.path.expanduser("~"), "Documents", "Scansioni"),
    "LOG_DIR": os.path.join(os.path.expanduser("~"), "Scansioni", "log"),

    # OCR
    "TESSERACT_PATH": r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    "OCR_LANG": "ita+eng",
    # Pre-elaborazione immagine prima dell'OCR: migliora molto la lettura di
    # documenti difficili come carta d'identita' e tessera sanitaria
    # (font piccoli, sfondi di sicurezza, poco contrasto). Metti False per
    # disattivarla.
    "OCR_PREPROCESS": True,
    # Ingrandisce l'immagine se e' piccola (aiuta l'OCR su testo minuto delle
    # tessere). 1.0 = nessun ingrandimento.
    "OCR_UPSCALE": 2.0,

    # Estrazione deterministica per documenti d'identita':
    # per carta d'identita'/tessera sanitaria il nome viene letto dai campi
    # COGNOME/NOME e VERIFICATO tramite il codice fiscale (che codifica cognome
    # e nome). E' piu' preciso di qualsiasi LLM su questi documenti. L'LLM resta
    # come fallback per gli altri tipi di documento. Metti False per usare solo l'LLM.
    "USE_CF_EXTRACTION": True,

    # LLM locale (Ollama) - usato come fallback e per i documenti generici.
    "OLLAMA_URL": "http://localhost:11434",
    # qwen2.5:3b e' piu' preciso di llama3.2:3b nell'estrazione di dati.
    "OLLAMA_MODEL": "qwen2.5:3b",    # alternative: "llama3.2:3b", "qwen2.5:1.5b"
    "OLLAMA_TIMEOUT": 300,           # secondi (modelli 3B su CPU sono lenti)

    # Qualita'/compressione del PDF salvato. Valori: "Massima", "Alta",
    # "Media", "Bassa", "Minima". Piu' bassa = file piu' leggero (utile per i
    # limiti di peso di certi portali). "Massima" = nessuna perdita.
    "PDF_QUALITA": "Massima",

    # Naming file
    # Alzato per far stare: tipo_Cognome_Nome_Paese_Servizio_Data
    "MAX_FILENAME_LEN": 100,
    # Prima di salvare, mostra il nome proposto e consente di confermarlo o
    # correggerlo a mano (INVIO = accetta). Cosi' un nome sbagliato non finisce
    # mai su disco. Metti False per salvataggio automatico senza chiedere.
    "CONFIRM_NAME": True,
    # Salva il testo OCR grezzo in un file .txt accanto al log: utile per capire
    # perche' un nome e' stato sbagliato (si vede cosa ha letto davvero l'OCR).
    "SAVE_OCR_DEBUG": True,

    # NAPS2 (fallback)
    "NAPS2_CONSOLE": r"C:\Program Files\NAPS2\naps2.console.exe",

    # ---- Auto-installazione dipendenze mancanti ----
    # Se True, lo script tenta di installare da solo cio' che manca:
    #   - moduli Python via pip
    #   - Tesseract-OCR via winget (+ download pacchetto lingua ita)
    #   - Ollama via winget (+ avvio servizio + ollama pull del modello)
    # Metti False se preferisci installare tutto manualmente.
    "AUTO_INSTALL": True,
}

# Costanti WIA (Windows Image Acquisition) -----------------------------------
WIA_FORMAT_JPEG = "{B96B3CAE-0728-11D3-9D7B-0000F81EF32E}"
WIA_FORMAT_PNG  = "{B96B3CAF-0728-11D3-9D7B-0000F81EF32E}"

# Proprieta' device/item WIA (property id)
WIA_DPS_DOCUMENT_HANDLING_SELECT = 3088   # 1=Feeder(ADF), 2=Flatbed
WIA_DPS_DOCUMENT_HANDLING_STATUS = 3087   # bit 0x01 = feeder pronto/carta presente
WIA_DPS_DOCUMENT_HANDLING_CAPS   = 3086   # bit 0x01 = FEEDER presente, 0x02 = FLATBED
FEEDER = 1
FLATBED = 2

WIA_IPS_CUR_INTENT   = 6146
WIA_IPS_XRES         = 6147
WIA_IPS_YRES         = 6148
WIA_IPS_XPOS         = 6149
WIA_IPS_YPOS         = 6150
WIA_IPS_XEXTENT      = 6151
WIA_IPS_YEXTENT      = 6152
WIA_IPA_DATATYPE     = 4103   # 0=BW, 2=Grayscale, 3=Color(RGB)
WIA_IPA_DEPTH        = 4104   # profondita' colore in bit (24 = RGB 8bit/canale)

# Intent flags
WIA_INTENT_COLOR      = 1
WIA_INTENT_GRAYSCALE  = 2
WIA_INTENT_TEXT       = 4

# Dimensioni A4 in pixel a dato DPI (210 x 297 mm)
def a4_pixels(dpi):
    larghezza = int(round(8.27 * dpi))   # 210 mm  ~ 8.27"
    altezza   = int(round(11.69 * dpi))  # 297 mm  ~ 11.69"
    return larghezza, altezza


# ===========================================================================
# LOGGING
# ===========================================================================
def setup_logging(log_dir):
    """Configura logging su console + file con timestamp."""
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "scan_brother_ai.log")

    logger = logging.getLogger("scan")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    # Console
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # File
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    logger.info("Log file: %s", log_file)
    return logger


# ===========================================================================
# BARRA DI AVANZAMENTO (per i download gestiti da Python)
# ===========================================================================
def _formato_byte(n):
    """Formatta un numero di byte in unita' leggibili."""
    for unita in ("B", "KB", "MB", "GB"):
        if n < 1024 or unita == "GB":
            return f"{n:.1f}{unita}"
        n /= 1024


def _barra_progresso(scaricato, totale, etichetta="", larghezza=30):
    """Disegna una barra di avanzamento su una singola riga del terminale.
    Se 'totale' e' sconosciuto (0), mostra solo i byte scaricati."""
    if totale > 0:
        frazione = min(scaricato / totale, 1.0)
        pieni = int(larghezza * frazione)
        barra = "#" * pieni + "-" * (larghezza - pieni)
        testo = (f"\r  {etichetta} [{barra}] {frazione*100:5.1f}%  "
                 f"{_formato_byte(scaricato)}/{_formato_byte(totale)}")
    else:
        testo = f"\r  {etichetta} ... {_formato_byte(scaricato)} scaricati"
    sys.stdout.write(testo)
    sys.stdout.flush()


def _fine_barra():
    """Chiude la riga della barra andando a capo."""
    sys.stdout.write("\n")
    sys.stdout.flush()


class Barra:
    """Barra di avanzamento a step con percentuale e TEMPO STIMATO residuo.
    La stima e' calcolata sul tempo medio degli step gia' completati."""

    def __init__(self, totale, etichetta, larghezza=30):
        self.totale = max(1, totale)
        self.fatti = 0
        self.t0 = time.time()
        self.etichetta = etichetta
        self.larghezza = larghezza
        self._disegna()

    def _disegna(self):
        fraz = min(self.fatti / self.totale, 1.0)
        pieni = int(self.larghezza * fraz)
        barra = "#" * pieni + "-" * (self.larghezza - pieni)
        trascorso = time.time() - self.t0
        if self.fatti > 0:
            residuo = int(trascorso / self.fatti * (self.totale - self.fatti))
            eta = f"restano ~{residuo // 60}m{residuo % 60:02d}s" if residuo >= 60 \
                else f"restano ~{residuo}s"
        else:
            eta = "stima in corso..."
        sys.stdout.write(f"\r  {self.etichetta} [{barra}] {fraz*100:5.1f}%  {eta}   ")
        sys.stdout.flush()

    def avanza(self, n=1):
        self.fatti += n
        self._disegna()

    def fine(self):
        self.fatti = self.totale
        self._disegna()
        sys.stdout.write("\n")
        sys.stdout.flush()


class Attesa:
    """Indicatore per attese a durata ignota (chiamate LLM): mostra uno spinner
    col tempo trascorso, aggiornato da un thread."""

    def __init__(self, etichetta):
        import threading
        self.etichetta = etichetta
        self.t0 = time.time()
        self._stop = threading.Event()
        self._th = threading.Thread(target=self._gira, daemon=True)
        self._th.start()

    def _gira(self):
        simboli = "|/-\\"
        i = 0
        while not self._stop.is_set():
            trascorso = int(time.time() - self.t0)
            sys.stdout.write(f"\r  {self.etichetta} {simboli[i % 4]}  {trascorso}s   ")
            sys.stdout.flush()
            i += 1
            self._stop.wait(0.5)

    def fine(self):
        self._stop.set()
        self._th.join(timeout=2)
        trascorso = int(time.time() - self.t0)
        sys.stdout.write(f"\r  {self.etichetta} completato in {trascorso}s        \n")
        sys.stdout.flush()


# ===========================================================================
# AUTO-INSTALLAZIONE DIPENDENZE
# ===========================================================================
def _comando_disponibile(nome):
    """True se un eseguibile e' raggiungibile nel PATH (usa 'where')."""
    try:
        r = subprocess.run(["where", nome], capture_output=True, text=True)
        return r.returncode == 0
    except Exception:
        return False


def _winget_disponibile(log):
    """Verifica che winget (gestore pacchetti Windows) sia presente."""
    if _comando_disponibile("winget"):
        return True
    log.warning("winget non disponibile: impossibile installare automaticamente "
                "programmi esterni. Su Windows 10/11 aggiorna 'App Installer' "
                "dal Microsoft Store.")
    return False


def _winget_install(package_id, log, extra_args=None):
    """Installa un pacchetto via winget. NON cattura l'output cosi' la barra
    di avanzamento nativa di winget resta visibile a schermo."""
    # Nota: niente --silent per mostrare il progresso del download.
    cmd = ["winget", "install", "--id", package_id, "-e",
           "--accept-package-agreements", "--accept-source-agreements"]
    if extra_args:
        cmd += extra_args
    log.info("winget: installazione '%s' in corso (puo' richiedere qualche minuto)...",
             package_id)
    print("-" * 60)
    try:
        # output lasciato scorrere sul terminale -> barra di winget visibile
        r = subprocess.run(cmd, timeout=900)
        print("-" * 60)
        if r.returncode not in (0,):
            log.warning("winget ha restituito codice %d per '%s'.",
                        r.returncode, package_id)
            return False
        return True
    except Exception as e:
        log.error("Esecuzione winget fallita per '%s': %s", package_id, e)
        return False


def _installa_moduli_python(mancanti, log):
    """Installa i moduli Python mancanti via pip nel Python corrente."""
    if not mancanti:
        return []
    pacchetti = sorted(set(mancanti.values()))
    log.info("Installazione moduli Python mancanti: %s", ", ".join(pacchetti))
    print("-" * 60)
    try:
        # output NON catturato -> pip mostra la sua barra di avanzamento
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade"] + pacchetti
        r = subprocess.run(cmd, timeout=600)
        print("-" * 60)
        if r.returncode != 0:
            log.error("pip ha restituito codice di errore %d.", r.returncode)
    except Exception as e:
        log.error("Impossibile eseguire pip: %s", e)

    # Ricontrolla quali risultano ancora mancanti
    ancora = {}
    for modulo, pacchetto in mancanti.items():
        try:
            # invalida cache import per moduli appena installati
            import importlib
            importlib.invalidate_caches()
            __import__(modulo)
        except ImportError:
            ancora[modulo] = pacchetto
    return list(ancora.keys())


def _installa_tesseract(log):
    """Installa Tesseract-OCR via winget e scarica il pacchetto lingua ita."""
    if not _winget_disponibile(log):
        return False
    ok = _winget_install("UB-Mannheim.TesseractOCR", log)
    # winget puo' non aggiornare il PATH nella sessione corrente: il percorso
    # atteso resta CONFIG["TESSERACT_PATH"].
    if not os.path.isfile(CONFIG["TESSERACT_PATH"]):
        # prova percorso alternativo comune
        alt = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe")
        if os.path.isfile(alt):
            CONFIG["TESSERACT_PATH"] = alt
    return ok and os.path.isfile(CONFIG["TESSERACT_PATH"])


def _scarica_lingua_tesseract(lang, log):
    """Scarica il file <lang>.traineddata nella cartella tessdata di Tesseract."""
    import requests
    tess = CONFIG["TESSERACT_PATH"]
    tessdata = os.path.join(os.path.dirname(tess), "tessdata")
    os.makedirs(tessdata, exist_ok=True)
    destinazione = os.path.join(tessdata, f"{lang}.traineddata")
    if os.path.isfile(destinazione):
        return True
    url = f"https://github.com/tesseract-ocr/tessdata/raw/main/{lang}.traineddata"
    log.info("Scarico pacchetto lingua Tesseract '%s'...", lang)
    try:
        # stream=True per scaricare a blocchi e disegnare la barra
        r = requests.get(url, timeout=120, stream=True)
        r.raise_for_status()
        totale = int(r.headers.get("Content-Length", 0))
        scaricato = 0
        etichetta = f"{lang}.traineddata"
        with open(destinazione, "wb") as f:
            for blocco in r.iter_content(chunk_size=64 * 1024):
                if not blocco:
                    continue
                f.write(blocco)
                scaricato += len(blocco)
                _barra_progresso(scaricato, totale, etichetta)
        _fine_barra()
        log.info("Lingua '%s' installata in %s", lang, tessdata)
        return True
    except Exception as e:
        log.error("Download lingua '%s' fallito: %s "
                  "(potrebbe servire eseguire lo script come amministratore).",
                  lang, e)
        return False


def _avvia_ollama(log):
    """Avvia il servizio Ollama in background se non e' in esecuzione."""
    try:
        # 'ollama serve' avvia il server; su Windows l'app di norma lo fa gia'.
        subprocess.Popen(["ollama", "serve"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        log.debug("Avvio 'ollama serve' non riuscito (forse gia' attivo): %s", e)


def _ollama_online(log):
    """True se l'endpoint Ollama risponde."""
    try:
        import requests
        r = requests.get(CONFIG["OLLAMA_URL"] + "/api/tags", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def _installa_ollama(log):
    """Installa Ollama via winget, lo avvia e attende che risponda."""
    if not _winget_disponibile(log):
        return False
    _winget_install("Ollama.Ollama", log)
    _avvia_ollama(log)
    # Attende l'avvio del servizio (fino a ~30s)
    for _ in range(15):
        if _ollama_online(log):
            return True
        time.sleep(2)
    return _ollama_online(log)


def _pull_modello_ollama(modello, log):
    """Scarica il modello LLM con 'ollama pull'."""
    log.info("Scarico il modello LLM '%s' (puo' richiedere diversi minuti)...",
             modello)
    try:
        r = subprocess.run(["ollama", "pull", modello], timeout=1800)
        return r.returncode == 0
    except Exception as e:
        log.error("'ollama pull %s' fallito: %s", modello, e)
        return False


# ===========================================================================
# CONTROLLO DIPENDENZE (all'avvio)  -- con auto-installazione
# ===========================================================================
def controlla_dipendenze(log, usa_naps2=False):
    """Verifica (e, se AUTO_INSTALL, installa) moduli Python, Tesseract e Ollama.
    Solleva RuntimeError con messaggi chiari se qualcosa resta irrisolto."""
    auto = CONFIG["AUTO_INSTALL"]
    problemi = []

    # --- Moduli Python -----------------------------------------------------
    moduli = {
        "win32com.client": "pywin32",
        "PIL": "pillow",
        "img2pdf": "img2pdf",
        "pytesseract": "pytesseract",
        "requests": "requests",
    }
    mancanti = {}
    for modulo, pacchetto in moduli.items():
        try:
            __import__(modulo)
        except ImportError:
            mancanti[modulo] = pacchetto

    if mancanti:
        if auto:
            log.info("Moduli Python mancanti: %s -> tento installazione automatica.",
                     ", ".join(mancanti.values()))
            residui = _installa_moduli_python(mancanti, log)
            for m in residui:
                problemi.append(
                    f"Modulo Python '{m}' non installabile automaticamente. "
                    f"Installa a mano: pip install {moduli[m]}"
                )
        else:
            for m, p in mancanti.items():
                problemi.append(f"Modulo Python mancante: '{m}'. pip install {p}")

    # --- Tesseract ---------------------------------------------------------
    if not os.path.isfile(CONFIG["TESSERACT_PATH"]):
        if auto:
            log.info("Tesseract non trovato -> tento installazione via winget.")
            if not _installa_tesseract(log):
                problemi.append(
                    f"Tesseract non installato automaticamente. Installa da "
                    f"https://github.com/UB-Mannheim/tesseract/wiki e/o correggi "
                    f"TESSERACT_PATH. NB: dopo l'installazione con winget puo' servire "
                    f"riavviare il terminale per aggiornare il PATH."
                )
        else:
            problemi.append(
                f"Tesseract non trovato in '{CONFIG['TESSERACT_PATH']}'. "
                f"Installa Tesseract-OCR o correggi TESSERACT_PATH."
            )

    # Pacchetti lingua OCR
    if os.path.isfile(CONFIG["TESSERACT_PATH"]):
        try:
            out = subprocess.run([CONFIG["TESSERACT_PATH"], "--list-langs"],
                                 capture_output=True, text=True, timeout=30)
            disponibili = out.stdout.lower()
            for lang in CONFIG["OCR_LANG"].split("+"):
                lang = lang.strip()
                if lang and lang not in disponibili:
                    if auto:
                        log.info("Lingua OCR '%s' mancante -> scarico.", lang)
                        if not _scarica_lingua_tesseract(lang, log):
                            problemi.append(
                                f"Pacchetto lingua Tesseract '{lang}' non installato. "
                                f"Scaricalo manualmente in tessdata."
                            )
                    else:
                        log.warning("Lingua Tesseract '%s' non trovata.", lang)
        except Exception as e:
            log.warning("Impossibile verificare le lingue Tesseract: %s", e)

    # --- Ollama ------------------------------------------------------------
    if not _ollama_online(log):
        if auto:
            log.info("Ollama non raggiungibile -> tento avvio/installazione.")
            _avvia_ollama(log)          # magari e' installato ma spento
            if not _ollama_online(log):
                _installa_ollama(log)
        if not _ollama_online(log):
            problemi.append(
                f"Ollama non raggiungibile su {CONFIG['OLLAMA_URL']}. "
                f"Installa da https://ollama.com/download e avvialo."
            )

    # Modello LLM
    if _ollama_online(log):
        try:
            import requests
            r = requests.get(CONFIG["OLLAMA_URL"] + "/api/tags", timeout=5)
            modelli = [m.get("name", "") for m in r.json().get("models", [])]
            log.info("Ollama online. Modelli: %s",
                     ", ".join(modelli) if modelli else "(nessuno)")
            presente = any(m == CONFIG["OLLAMA_MODEL"]
                           or m.split(":")[0] == CONFIG["OLLAMA_MODEL"].split(":")[0]
                           for m in modelli)
            if not presente:
                if auto:
                    if not _pull_modello_ollama(CONFIG["OLLAMA_MODEL"], log):
                        problemi.append(
                            f"Modello '{CONFIG['OLLAMA_MODEL']}' non scaricato. "
                            f"Esegui: ollama pull {CONFIG['OLLAMA_MODEL']}"
                        )
                else:
                    log.warning("Modello '%s' non presente. ollama pull %s",
                                CONFIG["OLLAMA_MODEL"], CONFIG["OLLAMA_MODEL"])
        except Exception as e:
            log.warning("Verifica modelli Ollama fallita: %s", e)

    # --- NAPS2 (solo se richiesto come fallback) ---------------------------
    if usa_naps2 and not os.path.isfile(CONFIG["NAPS2_CONSOLE"]):
        if auto and _winget_disponibile(log):
            log.info("NAPS2 non trovato -> tento installazione via winget.")
            _winget_install("Cyanfish.NAPS2", log)
        if not os.path.isfile(CONFIG["NAPS2_CONSOLE"]):
            problemi.append(
                f"NAPS2 console non trovato in '{CONFIG['NAPS2_CONSOLE']}'. "
                f"Installa NAPS2 o correggi NAPS2_CONSOLE."
            )

    if problemi:
        raise RuntimeError(
            "Controllo dipendenze fallito:\n  - " + "\n  - ".join(problemi)
        )

    log.info("Controllo dipendenze superato.")


# ===========================================================================
# SCANSIONE VIA WIA
# ===========================================================================
def elenca_device_wia(log=None):
    """Ritorna la lista dei device WIA come [(device_id, nome), ...]."""
    import win32com.client
    dm = win32com.client.Dispatch("WIA.DeviceManager")
    devices = []
    for i in range(1, dm.DeviceInfos.Count + 1):
        info = dm.DeviceInfos.Item(i)
        dev_id = info.DeviceID
        nome = ""
        try:
            # Property "Name" (id 7) descrive il device
            for j in range(1, info.Properties.Count + 1):
                p = info.Properties.Item(j)
                if p.Name.lower() in ("name", "description"):
                    nome = str(p.Value)
                    if p.Name.lower() == "name":
                        break
        except Exception:
            pass
        devices.append((dev_id, nome or "(sconosciuto)"))
    if log:
        for idx, (did, nome) in enumerate(devices, 1):
            log.info("  [%d] %s  ->  %s", idx, nome, did)
    return devices


def _imposta_proprieta(props, prop_id, valore, log):
    """Imposta una proprieta' WIA in modo tollerante (alcune non sono scrivibili
    su tutti i device Brother)."""
    try:
        for i in range(1, props.Count + 1):
            p = props.Item(i)
            if int(p.PropertyID) == prop_id:
                p.Value = valore
                return True
    except Exception as e:
        log.debug("Impossibile impostare property %s=%s: %s", prop_id, valore, e)
    return False


def _connetti_device(log, device_id_forzato=None):
    """Seleziona/collega il device Brother. Ritorna l'oggetto Device WIA."""
    import win32com.client

    device_id = device_id_forzato or CONFIG["DEVICE_ID"]
    devices = elenca_device_wia()

    if not devices:
        raise RuntimeError(
            "Nessuno scanner WIA rilevato. Verifica che lo scanner Brother sia "
            "acceso, collegato (USB/rete) e con i driver WIA installati."
        )

    scelto = None

    # 1) device scelto dall'utente (ID o nome). Confronto tollerante: spazi,
    #    maiuscole/minuscole e corrispondenza parziale, cosi' un ID copiato
    #    dall'elenco funziona sempre.
    if device_id:
        voluto = device_id.strip().strip('"').lower()
        # a) corrispondenza esatta sull'ID
        for did, nome in devices:
            if did.strip().lower() == voluto:
                scelto = (did, nome)
                break
        # b) corrispondenza parziale su ID o nome (l'utente puo' aver incollato
        #    il nome dello scanner invece dell'identificativo)
        if not scelto:
            for did, nome in devices:
                if voluto in did.strip().lower() or voluto in nome.strip().lower():
                    scelto = (did, nome)
                    log.info("Scanner selezionato per corrispondenza: %s", nome)
                    break
        if not scelto:
            log.warning("Lo scanner indicato ('%s') non e' fra quelli "
                        "disponibili: uso il rilevamento automatico.", device_id)

    # 2) auto-rilevamento Brother
    if not scelto:
        hint = CONFIG["DEVICE_NAME_HINT"].lower()
        candidati = [(did, nome) for did, nome in devices if hint in nome.lower()]
        if len(candidati) == 1:
            scelto = candidati[0]
            log.info("Device Brother rilevato automaticamente: %s", scelto[1])
        elif len(candidati) > 1:
            log.info("Piu' scanner Brother trovati:")
            scelto = _scegli_interattivo(candidati, log)

    # 3) scelta interattiva tra tutti
    if not scelto:
        log.info("Scanner disponibili:")
        scelto = _scegli_interattivo(devices, log)

    device_id_finale = scelto[0]
    log.info("Uso scanner: %s (%s)", scelto[1], device_id_finale)

    dm = win32com.client.Dispatch("WIA.DeviceManager")
    for i in range(1, dm.DeviceInfos.Count + 1):
        info = dm.DeviceInfos.Item(i)
        if info.DeviceID == device_id_finale:
            try:
                return info.Connect()
            except Exception as e:
                raise RuntimeError(
                    f"Impossibile connettersi allo scanner ({scelto[1]}). "
                    f"Potrebbe essere occupato da un altro programma o in errore. "
                    f"Dettagli: {e}"
                )
    raise RuntimeError("Device selezionato non piu' disponibile.")


def _scegli_interattivo(lista, log):
    """Chiede all'utente di scegliere un device dalla lista."""
    for idx, (did, nome) in enumerate(lista, 1):
        print(f"  [{idx}] {nome}")
    while True:
        try:
            scelta = input("Seleziona il numero dello scanner: ").strip()
            n = int(scelta)
            if 1 <= n <= len(lista):
                return lista[n - 1]
        except (ValueError, EOFError):
            pass
        print("Scelta non valida, riprova.")


def _configura_item(item, log):
    """Applica DPI, colore e area A4 all'item di scansione."""
    props = item.Properties
    dpi = CONFIG["DPI"]

    # Colore / tipo dato
    color_map = {"RGB": 3, "Grayscale": 2, "BlackWhite": 0}
    depth_map = {"RGB": 24, "Grayscale": 8, "BlackWhite": 1}
    modo = CONFIG["COLOR_MODE"]
    _imposta_proprieta(props, WIA_IPA_DATATYPE, color_map.get(modo, 3), log)
    # Profondita' colore esplicita: RGB = 24 bit (8 bit per canale)
    _imposta_proprieta(props, WIA_IPA_DEPTH, depth_map.get(modo, 24), log)

    # Risoluzione
    _imposta_proprieta(props, WIA_IPS_XRES, dpi, log)
    _imposta_proprieta(props, WIA_IPS_YRES, dpi, log)

    # Area A4 (origine 0,0 + estensione)
    w, h = a4_pixels(dpi)
    _imposta_proprieta(props, WIA_IPS_XPOS, 0, log)
    _imposta_proprieta(props, WIA_IPS_YPOS, 0, log)
    _imposta_proprieta(props, WIA_IPS_XEXTENT, w, log)
    _imposta_proprieta(props, WIA_IPS_YEXTENT, h, log)


def _device_ha_feeder(device):
    """True se lo scanner dichiara di avere un ADF (alimentatore)."""
    try:
        for i in range(1, device.Properties.Count + 1):
            p = device.Properties.Item(i)
            if int(p.PropertyID) == WIA_DPS_DOCUMENT_HANDLING_CAPS:
                # bit 0x01 = FEEDER presente
                return (int(p.Value) & 0x01) != 0
    except Exception:
        pass
    return False


def _imposta_origine(device, log):
    """Imposta l'origine documenti in base a CONFIG['SOURCE'].

    In modalita' 'Auto': se l'ADF (alimentatore sopra) e' presente e ha fogli
    caricati -> usa l'ADF; altrimenti usa il piano (flatbed).
    """
    modo = CONFIG["SOURCE"].lower()

    def _prova_feeder():
        """Tenta di impostare l'ADF; ritorna True se riuscito."""
        return _imposta_proprieta(device.Properties,
                                  WIA_DPS_DOCUMENT_HANDLING_SELECT, FEEDER, log)

    def _usa_flatbed():
        _imposta_proprieta(device.Properties,
                           WIA_DPS_DOCUMENT_HANDLING_SELECT, FLATBED, log)
        log.info("Origine: Flatbed (piano).")
        return "flatbed"

    # --- AUTO: preferisci l'ADF se ha carta ---
    if modo == "auto":
        if _device_ha_feeder(device) and _feeder_ha_carta(device):
            if _prova_feeder():
                log.info("Origine: ADF (rilevati fogli nell'alimentatore) -> "
                         "uso l'alimentatore invece del piano.")
                return "feeder"
            log.warning("Fogli nell'ADF ma impostazione ADF non riuscita: uso il piano.")
        else:
            log.info("ADF vuoto o assente: uso il piano (flatbed).")
        return _usa_flatbed()

    # --- FEEDER forzato ---
    if modo == "feeder":
        if _prova_feeder():
            log.info("Origine: ADF (Feeder) forzato.")
            return "feeder"
        log.warning("ADF non impostabile, ripiego sul piano (flatbed).")
        return _usa_flatbed()

    # --- FLATBED forzato (default) ---
    return _usa_flatbed()


def _feeder_ha_carta(device):
    """Controlla lo stato del feeder (bit 0x01 = documento presente)."""
    try:
        for i in range(1, device.Properties.Count + 1):
            p = device.Properties.Item(i)
            if int(p.PropertyID) == WIA_DPS_DOCUMENT_HANDLING_STATUS:
                return (int(p.Value) & 0x01) != 0
    except Exception:
        pass
    return False


def scansiona_wia(temp_dir, log, device_id_forzato=None):
    """Esegue la scansione (WIA) e ritorna la lista di percorsi immagine."""
    device = _connetti_device(log, device_id_forzato)
    modo_auto = CONFIG["SOURCE"].lower() == "auto"
    origine = _imposta_origine(device, log)

    immagini = []
    pagina = 1

    while True:
        # In modalita' Auto, dal secondo giro ri-rileva l'origine: se ricarichi
        # l'ADF o passi al piano tra un blocco e l'altro, lo script si adegua.
        if modo_auto and pagina > 1:
            origine = _imposta_origine(device, log)

        # Ottiene l'item da scansionare
        try:
            item = device.Items.Item(1)
        except Exception as e:
            raise RuntimeError(f"Impossibile ottenere l'item di scansione: {e}")

        _configura_item(item, log)

        log.info("Scansione pagina %d in corso...", pagina)
        try:
            image = item.Transfer(WIA_FORMAT_JPEG)
        except Exception as e:
            # Con ADF: quando la carta finisce, Transfer solleva eccezione -> stop
            if origine == "feeder" and pagina > 1:
                log.info("ADF vuoto: acquisizione terminata.")
                break
            raise RuntimeError(
                f"Errore durante la scansione (scanner occupato o carta assente?): {e}"
            )

        percorso = os.path.join(temp_dir, f"pagina_{pagina:03d}.jpg")
        # Rimuove eventuale file preesistente (WIA.SaveFile non sovrascrive)
        if os.path.exists(percorso):
            os.remove(percorso)
        image.SaveFile(percorso)
        immagini.append(percorso)
        log.info("Pagina %d salvata: %s", pagina, percorso)
        pagina += 1

        # Da ADF: se ci sono ancora fogli, prosegue il batch senza chiedere
        if origine == "feeder" and _feeder_ha_carta(device):
            continue

        # --- Chiede SEMPRE se ci sono altre pagine da scansionare ---
        if not CONFIG["MULTIPAGE"]:
            break
        try:
            risposta = input("\nCi sono altre pagine da scansionare? [s/N]: ").strip().lower()
        except EOFError:
            risposta = ""
        if risposta not in ("s", "si", "sì", "y", "yes"):
            break
        if origine == "feeder":
            print("Carica altri fogli nell'alimentatore (o mettili sul piano), "
                  "poi premi INVIO...")
            try:
                input()
            except EOFError:
                pass

    if not immagini:
        raise RuntimeError("Nessuna pagina acquisita.")
    log.info("Acquisite %d pagina/e in totale.", len(immagini))
    return immagini


# ===========================================================================
# FALLBACK: SCANSIONE VIA NAPS2 (console)
# ===========================================================================
def scansione_naps2_fallback(temp_dir, log):
    """
    Fallback con NAPS2 se WIA dà problemi col Brother.
    Documentazione naps2.console.exe:
      - Elenca driver/device:
          naps2.console.exe --listdevices --driver wia
      - Scansione diretta in PDF (piu' semplice):
          naps2.console.exe --driver wia --source glass \
              --dpi 300 --pagesize a4 --output "C:\\out\\scan.pdf"
        Per l'ADF usare: --source feeder
      - Profilo salvato in NAPS2 (consigliato per Brother):
          naps2.console.exe -p "NomeProfilo" -o "C:\\out\\scan.pdf"

    Qui produciamo direttamente un PDF temporaneo (NAPS2 gestisce multipagina
    da ADF nativamente). Ritorniamo il percorso del PDF.
    """
    pdf_temp = os.path.join(temp_dir, "naps2_scan.pdf")
    source = "feeder" if CONFIG["SOURCE"].lower() == "feeder" else "glass"
    cmd = [
        CONFIG["NAPS2_CONSOLE"],
        "--driver", "wia",
        "--source", source,
        "--dpi", str(CONFIG["DPI"]),
        "--pagesize", "a4",
        "--output", pdf_temp,
    ]
    log.info("Fallback NAPS2: %s", " ".join(cmd))
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except Exception as e:
        raise RuntimeError(f"Esecuzione NAPS2 fallita: {e}")

    if res.returncode != 0 or not os.path.isfile(pdf_temp):
        raise RuntimeError(
            f"NAPS2 non ha prodotto il PDF. stdout={res.stdout} stderr={res.stderr}"
        )
    log.info("NAPS2 ha prodotto: %s", pdf_temp)
    return pdf_temp


# ===========================================================================
# UNIONE IMMAGINI -> PDF
# ===========================================================================
# Livelli di compressione del PDF: (qualita_jpeg, fattore_ridimensionamento).
# Qualita' 100 e fattore 1.0 = nessuna perdita/ridimensionamento.
LIVELLI_QUALITA = {
    "Massima":   (95, 1.00),   # file piu' grande, qualita' migliore
    "Alta":      (85, 1.00),
    "Media":     (70, 0.85),   # buon compromesso per l'invio
    "Bassa":     (55, 0.70),
    "Minima":    (40, 0.55),   # file piu' piccolo, per limiti stretti
}


def immagini_in_pdf(immagini, pdf_out, log):
    """Unisce le immagini in un unico PDF.

    Se la qualita' e' impostata su 'Massima' si usa img2pdf senza ricompressione
    (fedelta' totale). Con gli altri livelli le pagine vengono ricompresse in
    JPEG (ed eventualmente ridotte) per rientrare in un limite di peso: piu'
    bassa la qualita', piu' piccolo il file."""
    livello = CONFIG.get("PDF_QUALITA", "Massima")
    qualita, fattore = LIVELLI_QUALITA.get(livello, (95, 1.0))

    # --- Massima qualita': nessuna ricompressione (comportamento originale) ---
    if livello == "Massima":
        try:
            import img2pdf
            with open(pdf_out, "wb") as f:
                f.write(img2pdf.convert(immagini))
            log.info("PDF creato con img2pdf (qualita' massima): %s", pdf_out)
            return pdf_out
        except Exception as e:
            log.warning("img2pdf fallito (%s), provo con Pillow.", e)

    # --- Con compressione: ricomprime le pagine in JPEG (via Pillow) ---
    try:
        from PIL import Image
        pagine = []
        for p in immagini:
            img = Image.open(p).convert("RGB")
            if fattore < 1.0:
                nuova = (max(1, int(img.width * fattore)),
                         max(1, int(img.height * fattore)))
                img = img.resize(nuova, Image.LANCZOS)
            pagine.append(img)
        pagine[0].save(pdf_out, save_all=True, append_images=pagine[1:],
                       format="PDF", quality=qualita, optimize=True)
        dim = os.path.getsize(pdf_out) / 1048576.0
        log.info("PDF creato con compressione '%s' (qualita' JPEG %d, scala %.0f%%): "
                 "%s  (%.2f MB)", livello, qualita, fattore * 100, pdf_out, dim)
        return pdf_out
    except Exception as e:
        raise RuntimeError(f"Creazione PDF fallita: {e}")


# ===========================================================================
# OCR con Tesseract
# ===========================================================================
def _preprocessa_per_ocr(percorso, log):
    """Prepara la pagina: scala di grigi + correzione dell'orientamento.
    L'ingrandimento e il contrasto si applicano dopo, sui singoli ritagli
    (vedi _affina), cosi' si lavora su immagini piccole e nitide."""
    from PIL import Image, ImageOps
    img = Image.open(percorso)

    if not CONFIG.get("OCR_PREPROCESS", True):
        return img

    # 1) scala di grigi (toglie il rumore cromatico degli sfondi di sicurezza)
    img = ImageOps.grayscale(img)

    # 2) correzione orientamento: fogli capovolti o ruotati nell'ADF
    img = _correggi_orientamento(img, log)

    log.debug("Pagina preparata per OCR: %s -> %dx%d",
              os.path.basename(percorso), img.width, img.height)
    return img


def _affina(img):
    """Porta il ritaglio a una dimensione utile per l'OCR.

    NB: niente 'sharpen' e niente ingrandimenti forti. Le fotocopie hanno un
    RETINO di puntini: ingrandire e affilare lo amplifica e l'OCR legge solo
    rumore. La pulizia vera (mediana + binarizzazione) avviene in _ocr_migliore.
    """
    from PIL import Image
    lato = max(img.size)
    if lato and lato < 900:            # ingrandisce solo i ritagli minuscoli
        f = 900.0 / lato
        img = img.resize((max(1, int(img.width * f)),
                          max(1, int(img.height * f))), Image.LANCZOS)
    return img


def _regioni_contenuto(img, log):
    """Individua i BLOCCHI DI CONTENUTO nella pagina.

    Caso tipico: la fotocopia di una carta d'identita' mette fronte e retro
    (piccoli) su un A4 quasi tutto bianco. L'OCR sull'intera pagina produce
    rumore; isolando i due riquadri e ingrandendoli il testo diventa leggibile.

    Ritorna una lista di box (sx, sopra, dx, sotto) in coordinate immagine."""
    from PIL import Image
    # Analisi su copia ridotta: veloce e sufficiente per localizzare i blocchi
    piccola = img.copy()
    piccola.thumbnail((700, 700), Image.BILINEAR)
    w, h = piccola.size
    if w < 20 or h < 20:
        return []
    px = piccola.load()

    SOGLIA_SCURO = 190          # sotto questo valore il pixel e' "inchiostro"
    righe = [0] * h
    for y in range(h):
        conta = 0
        for x in range(w):
            if px[x, y] < SOGLIA_SCURO:
                conta += 1
        righe[y] = conta

    # Bande orizzontali con contenuto (almeno l'1,5% della larghezza)
    min_riga = max(2, int(w * 0.015))
    bande, inizio = [], None
    gap_max = max(4, int(h * 0.02))     # unisce bande separate da poco spazio
    for y in range(h):
        if righe[y] >= min_riga:
            if inizio is None:
                inizio = y
            fine = y
        elif inizio is not None and y - fine > gap_max:
            bande.append((inizio, fine))
            inizio = None
    if inizio is not None:
        bande.append((inizio, fine))

    # Per ogni banda calcola l'estensione orizzontale del contenuto
    regioni = []
    for y0, y1 in bande:
        if y1 - y0 < max(8, int(h * 0.02)):      # banda troppo sottile: rumore
            continue
        colonne = [0] * w
        for y in range(y0, y1 + 1):
            for x in range(w):
                if px[x, y] < SOGLIA_SCURO:
                    colonne[x] += 1
        min_col = max(1, int((y1 - y0) * 0.02))
        xs = [x for x in range(w) if colonne[x] >= min_col]
        if not xs:
            continue
        x0, x1 = xs[0], xs[-1]
        if x1 - x0 < max(8, int(w * 0.05)):
            continue
        # margine + riporto alle coordinate dell'immagine piena
        sx = img.width / float(w)
        sy = img.height / float(h)
        mx = int((x1 - x0) * 0.04 * sx) + 8
        my = int((y1 - y0) * 0.06 * sy) + 8
        regioni.append((max(0, int(x0 * sx) - mx),
                        max(0, int(y0 * sy) - my),
                        min(img.width, int((x1 + 1) * sx) + mx),
                        min(img.height, int((y1 + 1) * sy) + my)))

    if regioni:
        log.info("Rilevati %d blocchi di contenuto nella pagina.", len(regioni))
    return regioni


def _punteggio_ocr(testo):
    """Punteggio qualita' di un testo OCR: caratteri alfanumerici + forte bonus
    per le parole-chiave dei documenti (una lettura sensata le contiene)."""
    if not testo:
        return 0
    comp = re.sub(r"[^A-Z]", "", testo.upper())
    s = sum(c.isalnum() for c in testo)
    for kw in ("COGNOME", "SURNAME", "IDENTIT", "TESSERA", "SANITARIA",
               "RESIDEN", "CODICEFISCALE", "COMUNE", "NASCITA", "CARTA",
               "REPUBBLICA", "ITALIANA"):
        if kw in comp:
            s += 400
    return s


def _correggi_orientamento(img, log):
    """Le scansioni possono arrivare capovolte o ruotate (foglio messo storto
    nell'ADF): l'OCR su testo ruotato produce solo spazzatura. Prova le 4
    orientazioni su una copia ridotta (veloce) e tiene quella col punteggio
    migliore, poi ruota l'immagine piena di conseguenza."""
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = CONFIG["TESSERACT_PATH"]
    piccola = img.copy()
    piccola.thumbnail((1500, 1500))
    migliore_ang, migliore_p = 0, -1
    for ang in (0, 90, 180, 270):
        prova = piccola if ang == 0 else piccola.rotate(ang, expand=True)
        try:
            t = pytesseract.image_to_string(prova, lang=CONFIG["OCR_LANG"],
                                            config="--oem 1 --psm 3")
        except Exception:
            continue
        p = _punteggio_ocr(t)
        if p > migliore_p:
            migliore_p, migliore_ang = p, ang
    if migliore_ang:
        log.info("Pagina ruotata: correggo l'orientamento di %d gradi.",
                 migliore_ang)
        return img.rotate(migliore_ang, expand=True)
    return img


def _ocr_migliore(img, log, barra=None):
    """OCR robusto su documenti fotocopiati.

    Due accorgimenti fondamentali, ricavati da prove sui documenti reali:

    1) FILTRO MEDIANO: le fotocopie riproducono il testo con un retino di
       puntini. Senza filtro Tesseract legge il retino e produce solo rumore.
    2) BINARIZZAZIONE a piu' soglie: le tessere hanno uno sfondo di sicurezza
       grigio (guilloche) che verrebbe scambiato per testo. Tenendo solo i
       pixel scuri resta il testo vero. La soglia migliore varia col documento,
       quindi se ne provano diverse.

    Ogni combinazione soglia/PSM legge bene campi diversi (una l'intestazione,
    un'altra COGNOME/NOME): i risultati migliori vengono quindi CONCATENATI,
    ordinati per qualita', cosi' l'estrazione successiva trova tutti i campi.
    """
    import pytesseract
    from PIL import ImageFilter

    grande = max(img.width, img.height) > 3000
    soglie = (130,) if grande else (110, 130, 150)
    psms = (6, 3) if grande else (6, 3, 11)

    try:
        pulita = img.filter(ImageFilter.MedianFilter(3))
    except Exception:
        pulita = img

    risultati = []
    for soglia in soglie:
        binaria = pulita.point(lambda p, s=soglia: 255 if p > s else 0)
        for psm in psms:
            try:
                testo = pytesseract.image_to_string(
                    binaria, lang=CONFIG["OCR_LANG"],
                    config=f"--oem 1 --psm {psm}")
            except Exception as e:
                log.debug("OCR soglia %d psm %d fallito: %s", soglia, psm, e)
                continue
            risultati.append((_punteggio_ocr(testo), testo))

    # Passata anche sull'immagine non binarizzata: utile sui documenti puliti
    # (stampati, non fotocopiati), dove la soglia potrebbe togliere del testo.
    try:
        testo = pytesseract.image_to_string(img, lang=CONFIG["OCR_LANG"],
                                            config="--oem 1 --psm 3")
        risultati.append((_punteggio_ocr(testo), testo))
    except Exception:
        pass

    if barra:
        barra.avanza()
    if not risultati:
        return ""

    risultati.sort(key=lambda x: -x[0])
    migliori = [t for _, t in risultati[:4] if t.strip()]
    return "\n".join(migliori)


def ocr_testo(immagini, log):
    """Esegue OCR (ita+eng) sulle immagini, con pre-elaborazione e scelta della
    migliore modalita' PSM. Ritorna la LISTA del testo per singola pagina
    (utile per isolare il retro del documento)."""
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = CONFIG["TESSERACT_PATH"]

    # Barra: uno step per pagina -> percentuale e tempo stimato
    barra = Barra(len(immagini), "OCR")
    pagine_testo = []
    for idx, p in enumerate(immagini, 1):
        try:
            img = _preprocessa_per_ocr(p, log)

            # Se la pagina contiene blocchi piccoli su tanto bianco (es. carta
            # d'identita' fotocopiata fronte/retro su un A4), l'OCR va fatto
            # sui SINGOLI blocchi ingranditi: sull'intera pagina darebbe rumore.
            testo = ""
            regioni = _regioni_contenuto(img, log)
            area_pagina = float(img.width * img.height) or 1.0
            area_reg = sum((b[2] - b[0]) * (b[3] - b[1]) for b in regioni)
            if regioni and area_reg < 0.70 * area_pagina:
                parti = []
                for n, box in enumerate(regioni, 1):
                    ritaglio = _affina(img.crop(box))
                    t = _ocr_migliore(ritaglio, log)
                    log.info("  blocco %d/%d: %d caratteri.", n, len(regioni),
                             len(t))
                    parti.append(t)
                testo = "\n".join(parti)
                barra.avanza()
            else:
                testo = _ocr_migliore(_affina(img), log, barra)

            pagine_testo.append(testo)
            log.info("OCR pagina %d: %d caratteri estratti.", idx, len(testo))
        except Exception as e:
            log.error("OCR fallito su pagina %d: %s", idx, e)
            pagine_testo.append("")
            barra.avanza()
    barra.fine()

    if not any(t.strip() for t in pagine_testo):
        log.warning("OCR non ha estratto testo (documento vuoto/immagine?).")
    return pagine_testo


def ocr_da_pdf(pdf_path, log):
    """OCR su un PDF (usato nel percorso NAPS2). Estrae le pagine come immagini
    tramite Tesseract non e' diretto: qui usiamo Pillow non e' sufficiente per
    PDF, quindi facciamo affidamento sul fatto che, nel percorso normale, l'OCR
    lavori sulle immagini. Se hai solo il PDF, converti con pdf2image (Poppler)
    oppure lascia che l'LLM lavori su meno testo. Qui tentiamo con Tesseract su
    ogni pagina se pdf2image e' disponibile."""
    try:
        from pdf2image import convert_from_path
        pagine = convert_from_path(pdf_path, dpi=CONFIG["DPI"])
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = CONFIG["TESSERACT_PATH"]
        pagine_testo = []
        for idx, img in enumerate(pagine, 1):
            pagine_testo.append(pytesseract.image_to_string(img, lang=CONFIG["OCR_LANG"]))
            log.info("OCR (PDF) pagina %d completata.", idx)
        return pagine_testo
    except ImportError:
        log.warning("pdf2image non installato: OCR sul PDF NAPS2 saltato. "
                    "(pip install pdf2image + Poppler) Uso nome di fallback.")
        return []
    except Exception as e:
        log.error("OCR sul PDF fallito: %s", e)
        return []


# ===========================================================================
# ESTRAZIONE DETERMINISTICA (documenti d'identita')
# ---------------------------------------------------------------------------
# Per carta d'identita' / tessera sanitaria l'intestatario e' in campi ben
# precisi (COGNOME/NOME) e il CODICE FISCALE codifica cognome e nome: possiamo
# quindi estrarre e soprattutto VERIFICARE il nome in modo deterministico,
# senza dipendere dalle "allucinazioni" di un LLM piccolo. Questo e' il
# componente leggero e specializzato che aumenta la precisione sui nomi.
# ===========================================================================
_CONSONANTI = "BCDFGHJKLMNPQRSTVWXYZ"
_VOCALI = "AEIOU"


def _solo_lettere(s):
    """Lascia solo lettere A-Z (rimuove accenti comuni)."""
    trad = str.maketrans("ÀÁÂÃÄÈÉÊËÌÍÎÏÒÓÔÕÖÙÚÛÜÇ", "AAAAAEEEEIIIIOOOOOUUUUC")
    return "".join(c for c in s.upper().translate(trad) if c.isalpha())


def _cf_codice_cognome(cognome):
    """Calcola i 3 caratteri del codice fiscale corrispondenti al cognome."""
    s = _solo_lettere(cognome)
    cons = [c for c in s if c in _CONSONANTI]
    voc = [c for c in s if c in _VOCALI]
    return "".join((cons + voc + ["X", "X", "X"])[:3])


def _cf_codice_nome(nome):
    """Calcola i 3 caratteri del codice fiscale corrispondenti al nome."""
    s = _solo_lettere(nome)
    cons = [c for c in s if c in _CONSONANTI]
    if len(cons) >= 4:
        scelti = [cons[0], cons[2], cons[3]]
    else:
        voc = [c for c in s if c in _VOCALI]
        scelti = (cons + voc + ["X", "X", "X"])[:3]
    return "".join(scelti)


def _trova_codice_fiscale(testo):
    """Cerca un codice fiscale (16 caratteri) nel testo OCR. Tollerante agli
    spazi. Ritorna il CF in maiuscolo o None."""
    compatto = re.sub(r"[ \t\.\-]", "", testo.upper())
    m = re.search(r"[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]", compatto)
    return m.group(0) if m else None


def _codici_cf_parziali(testo):
    """Quando il codice fiscale e' letto male e non passa il controllo completo,
    spesso l'INIZIO e' comunque leggibile: 6 lettere + 2 cifre + 1 lettera
    (es. 'RSSMRC78M...'). Le prime 6 lettere bastano per identificare cognome
    (primi 3) e nome (secondi 3). Ritorna (cod_cognome, cod_nome) o (None, None)."""
    compatto = re.sub(r"[ \t\.\-]", "", testo.upper())
    m = re.search(r"\b([A-Z]{3})([A-Z]{3})\d{2}[A-Z]", compatto)
    if m:
        return m.group(1), m.group(2)
    return None, None


def _titola(s):
    """Cognome/Nome in forma leggibile: iniziali maiuscole, spazi->underscore."""
    parti = re.split(r"\s+", s.strip())
    return "_".join(p.capitalize() for p in parti if p)


def _tipo_documento(testo_up):
    """Riconosce il tipo di documento d'identita' dal testo OCR. Confronto
    'compatto' (senza spazi/punteggiatura) per tollerare gli errori di spaziatura
    dell'OCR (es. 'CARTA D' IDENTITA', 'TESSERA  SANITARIA')."""
    compatto = re.sub(r"[^A-Z]", "", testo_up.upper())
    # Tessera sanitaria: basta 'TESSERA'+'SANITARIA' (anche separate da altro).
    if ("TESSERA" in compatto and "SANITARIA" in compatto) \
            or "SERVIZIOSANITARIO" in compatto \
            or "ASSICURAZIONEMALATTIA" in compatto:
        return "tessera_sanitaria"
    # Carta d'identita': 'CARTA' + una forma di 'IDENT...' (IDENTITA, IDENTITÀ,
    # e anche letture OCR imperfette tipo IDENTLTA -> contengono comunque 'IDENT').
    if "CARTA" in compatto and "IDENT" in compatto:
        return "carta_identita"
    # Lettura OCR degradata: 'CARTA' puo' sparire del tutto (es. 'EPCADELUI...').
    # Se pero' compaiono un frammento 'IDENTI' E l'etichetta 'COGNOME', e' con
    # ottima probabilita' una carta d'identita'.
    if "IDENTI" in compatto and "COGNOME" in compatto:
        return "carta_identita"
    if "PATENTE" in compatto:
        return "patente"
    if "PASSAPORTO" in compatto or "PASSPORT" in compatto:
        return "passaporto"
    return None


def _pagina_documento_identita(pagine, log):
    """Se sono stati scansionati piu' fogli, individua QUALE pagina e' il
    documento d'identita', riconoscendolo dalla scritta 'CARTA D'IDENTITA' /
    'TESSERA SANITARIA' ecc. Ritorna (testo_pagina, tipo) oppure (None, None)
    se nessuna pagina e' un documento d'identita'.

    Cosi' nome/cognome e residenza vengono estratti SOLO dalla pagina giusta,
    ignorando gli altri fogli (che confonderebbero l'estrazione)."""
    migliore_testo, migliore_tipo, punteggio_max = None, None, 0
    for idx, p in enumerate(pagine, 1):
        up = _solo_lettere_spazi(p).upper()
        tipo = _tipo_documento(up)
        if not tipo:
            continue
        # A parita' di tipo, preferisci la pagina con piu' segnali utili
        s = 2
        if "RESIDENZA" in up:
            s += 1
        if _trova_codice_fiscale(p):
            s += 1
        log.debug("Pagina %d: documento '%s' (punteggio %d)", idx, tipo, s)
        if s > punteggio_max:
            punteggio_max, migliore_testo, migliore_tipo = s, p, tipo

    if migliore_tipo:
        log.info("Documento d'identita' riconosciuto ('%s') tra i fogli scansionati.",
                 migliore_tipo)
    else:
        log.info("Nessun documento d'identita' riconosciuto tra i fogli.")
        # Diagnostica: mostra cosa ha letto l'OCR (versione compattata) per
        # capire perche' il match e' fallito.
        for idx, p in enumerate(pagine, 1):
            comp = re.sub(r"[^A-Z]", "", _solo_lettere_spazi(p).upper())
            log.info("  [diagnostica] pagina %d, testo OCR compattato (primi 160): %s",
                     idx, comp[:160] if comp else "(vuoto)")
    return migliore_testo, migliore_tipo


# Parole che sono ETICHETTE dei campi (in italiano e inglese), da NON confondere
# col valore. Sulla CIE i campi sono bilingui: 'COGNOME / SURNAME', 'NOME / NAME'.
_PAROLE_ETICHETTA = {
    "COGNOME", "SURNAME", "NOME", "NAME", "GIVEN", "NAMES",
    "LUOGO", "DATA", "NASCITA", "BIRTH", "PLACE", "DATE", "OF",
    "SESSO", "SEX", "CITTADINANZA", "NATIONALITY", "STATURA", "HEIGHT",
    "COMUNE", "EMISSIONE", "SCADENZA", "EXPIRY", "ISSUE",
    "CODICE", "FISCALE", "CARTA", "IDENTITA", "REPUBBLICA", "ITALIANA",
    "RESIDENZA", "RESIDENCE", "INDIRIZZO", "ADDRESS",
    # campo "COGNOME E NOME DEI GENITORI O DI CHI NE FA LE VECI"
    "GENITORI", "GENITORE", "PARENTS", "PARENT", "PADRE", "MADRE", "VECI",
    "TUTOR", "TUTORS", "DEI", "DEL", "DELLA", "CHI", "MINISTERO", "INTERNO",
}

# Indizi che l'etichetta trovata NON e' quella dell'intestatario ma il campo
# dei genitori ("COGNOME E NOME DEI GENITORI O DI CHI NE FA LE VECI").
_INDIZI_GENITORI = ("GENITOR", "GENIT", "GENTI", "PARENT", "PADRE", "MADRE",
                    "VECI", "TUTOR")


def _valore_dopo_etichetta(testo, etichette, log=None):
    """Estrae il VALORE che segue un'etichetta di campo, SALTANDO le eventuali
    parole-etichetta successive (es. dopo 'COGNOME' salta 'SURNAME' e prende il
    cognome vero). Gestisce valore sulla stessa riga o sulla riga sotto, e
    cognomi/nomi composti (max 2 parole). Ritorna la stringa o None."""
    for et in etichette:
        for m in re.finditer(et, testo, re.IGNORECASE):
            coda = testo[m.end(): m.end() + 80]
            # Salta il campo dei GENITORI: sulla CIE c'e' anche
            # "COGNOME E NOME DEI GENITORI O DI CHI NE FA LE VECI", che non e'
            # l'intestatario del documento.
            contesto = _solo_lettere_spazi(coda[:60]).upper()
            if any(k in contesto.replace(" ", "") for k in _INDIZI_GENITORI):
                continue
            parole = re.findall(r"[A-Za-zÀ-Ù][A-Za-zÀ-Ù'\-]+", coda)
            valore = []
            for w in parole:
                wu = _solo_lettere(w)          # MAIUSCOLO senza accenti
                if wu in _PAROLE_ETICHETTA:
                    if valore:                 # gia' raccolto il valore -> stop
                        break
                    continue                   # e' un'altra etichetta -> salta
                # Sui documenti d'identita' i valori sono stampati in MAIUSCOLO:
                # una parola con minuscole e' rumore dell'OCR (es. 'yo en'),
                # non il cognome. Scartarla evita nomi inventati.
                if any(c.islower() for c in w):
                    if valore:
                        break
                    continue
                if len(wu) < 3:                # frammenti troppo corti: rumore
                    if valore:
                        break
                    continue
                valore.append(w)
                if len(valore) >= 2:           # cognomi/nomi composti: max 2 parole
                    break
            if valore:
                return " ".join(valore)
    return None


def _estrai_da_mrz(testo, log=None, passaporto=False):
    """Estrae cognome/nome dalla riga MRZ (zona a lettura ottica, righe di '<'
    in fondo al documento). E' un formato macchina: la fonte piu' affidabile.

    Due formati:
      - carta d'identita' (TD1): la riga nomi e' 'COGNOME<<NOME<NOME2<<<'
      - passaporto (TD3): la riga 1 e' 'P<CCCSURNAME<<GIVEN<NAMES<<<' dove
        'P' = tipo, 'CCC' = paese emittente; il nome vero inizia DOPO quel
        prefisso di 5 caratteri.
    """
    def _leggi(corpo):
        """Da 'COGNOME<<NOME<<<' ricava (cognome, nome), o (None, None)."""
        if not re.fullmatch(r"[A-Z]+(<[A-Z]+)*<<+[A-Z]+(<[A-Z]+)*<*", corpo):
            return None, None
        cogn, _, resto = corpo.partition("<<")
        cognome = cogn.replace("<", " ").strip()
        nome = resto.strip("<").replace("<", " ").strip()
        if len(cognome) >= 2 and len(nome) >= 2:
            return cognome, nome
        return None, None

    def _leggi_passaporto(corpo):
        """Riga 1 passaporto: 'P' + tipo + 3 lettere paese + COGNOME<<NOME.
        Toglie il prefisso di 5 caratteri e legge il resto. Tollera l'OCR che
        scambia il primo '<' con una lettera (es. 'PEROU' invece di 'P<ROU')."""
        if "<<" not in corpo or len(corpo) < 8:
            return None, None
        # Il corpo deve iniziare con 'P' (tipo documento passaporto)
        if not corpo.startswith("P"):
            return None, None
        return _leggi(corpo[5:])          # salta P + tipo + paese (3)

    # Righe candidate MRZ: senza cifre, con almeno un '<' e composte quasi solo
    # da lettere maiuscole e '<'.
    righe = testo.splitlines()
    pulite = []
    for r in righe:
        s = re.sub(r"\s", "", r.upper())
        if not s:
            pulite.append("")          # riga vuota: non spezza la sequenza MRZ
            continue
        if re.search(r"\d", s) or "<" not in s:
            pulite.append(None)        # riga non-MRZ: interrompe la sequenza
            continue
        solo = re.sub(r"[^A-Z<]", "", s)
        # deve essere prevalentemente caratteri MRZ, altrimenti e' testo normale
        pulite.append(solo if len(solo) >= 0.8 * len(s) else None)

    # 1) riga singola  2) fino a 3 righe consecutive: l'OCR spesso SPEZZA la
    #    riga dei nomi (es. 'ROSSETTI<' e '<MARCO<<<<<' su righe diverse).
    for finestra in (1, 2, 3):
        for i in range(len(pulite)):
            pezzi = pulite[i:i + finestra]
            if any(p is None for p in pezzi):
                continue
            corpo = "".join(p for p in pezzi if p)
            if corpo.count("<") < 3 or "<<" not in corpo:
                continue
            # Sui passaporti si prova prima il formato TD3 (prefisso P + paese)
            cognome = nome = None
            if passaporto:
                cognome, nome = _leggi_passaporto(corpo)
            if not cognome:
                cognome, nome = _leggi(corpo)
            if cognome:
                if log:
                    log.info("Cognome/nome dalla riga MRZ: %s / %s",
                             cognome, nome)
                return cognome, nome
    return None, None


def _estrai_identita(testo, log, testo_cf=None):
    """Estrae 'tipo_Cognome_Nome' in modo deterministico e VERIFICATO tramite
    codice fiscale. Ritorna la stringa nome-file oppure None (se non applicabile
    o non verificabile -> si passa all'LLM).

    'testo' e' il testo della pagina del documento (per tipo, cognome, nome).
    'testo_cf' (se fornito) e' il testo su cui cercare il CODICE FISCALE: utile
    quando il CF sta su un'altra pagina (es. retro) rispetto al titolo."""
    if not CONFIG.get("USE_CF_EXTRACTION", True):
        return None

    testo_up = _solo_lettere_spazi(testo).upper()
    tipo = _tipo_documento(testo_up)
    # Cerca il CF prima nel testo pagina, poi (se assente) nel testo completo
    cf = _trova_codice_fiscale(testo) or (_trova_codice_fiscale(testo_cf)
                                          if testo_cf else None)
    if cf:
        log.info("Codice fiscale rilevato: %s", cf)
        cod_cog, cod_nom = cf[0:3], cf[3:6]
    else:
        # CF illeggibile per intero: spesso l'inizio e' comunque valido e
        # basta per identificare cognome e nome.
        cod_cog, cod_nom = _codici_cf_parziali(testo)
        if not cod_cog and testo_cf:
            cod_cog, cod_nom = _codici_cf_parziali(testo_cf)
        if cod_cog:
            log.info("Codici parziali dal codice fiscale: cognome=%s nome=%s",
                     cod_cog, cod_nom)

    # Senza tipo documento riconosciuto lasciamo lavorare l'LLM
    if not tipo:
        return None

    # PRIORITA' 1: riga MRZ (COGNOME<<NOME) - formato macchina, la fonte
    # piu' affidabile presente sul documento.
    mrz_cog, mrz_nom = _estrai_da_mrz(testo, log,
                                      passaporto=(tipo == "passaporto"))
    if mrz_cog and mrz_nom:
        risultato = f"{tipo}_{_titola(mrz_cog)}_{_titola(mrz_nom)}"
        log.info("Nome estratto dalla MRZ: %s", risultato)
        return risultato

    # PRIORITA' 2: campi etichettati COGNOME/NOME. Si prova 'COGNOME'/'NOME'
    # (it) e poi 'SURNAME'/'NAME' (en); la funzione salta le etichette bilingui.
    cognome = _valore_dopo_etichetta(testo, [r"COGNOME", r"SURNAME"], log)
    nome = _valore_dopo_etichetta(testo, [r"\bNOME\b", r"\bNAME\b"], log)

    # --- Il codice fiscale RIEMPIE i valori mancanti e CONFERMA quelli letti,
    #     ma NON sovrascrive un cognome/nome gia' estratto dall'etichetta.
    #     (Il CF stesso puo' essere storpiato dall'OCR: sovrascrivere sarebbe
    #     rischioso -> es. sostituire 'Meringhi' con una parola a caso.)
    if cod_cog and cod_nom:
        # Parole del documento utilizzabili come cognome/nome (niente etichette)
        token = [t for t in re.findall(r"[A-ZÀ-Ù]{3,30}", testo_up)
                 if t not in _PAROLE_ETICHETTA]

        def _cerca(codice, funz):
            for t in token:
                if funz(t) == codice:
                    return t
            return None

        # Se il valore etichettato ha PIU' parole (l'OCR incolla rumore accanto
        # al valore vero, es. 'REA MERIGHEAA'), tiene quella che combacia col CF.
        def _filtra(valore, codice, funz):
            parole = valore.split()
            if len(parole) > 1:
                for w in parole:
                    if funz(w) == codice:
                        return w
            return valore

        if cognome:
            cognome = _filtra(cognome, cod_cog, _cf_codice_cognome)
        if nome:
            nome = _filtra(nome, cod_nom, _cf_codice_nome)

        # Il codice fiscale fa da CHECKSUM: se il valore letto non gli
        # corrisponde (o manca), si cerca nel documento la parola che combacia.
        # Le parole-etichetta sono escluse dai candidati, quindi non puo'
        # scegliere 'SURNAME' o simili.
        if not cognome or _cf_codice_cognome(cognome) != cod_cog:
            trovato = _cerca(cod_cog, _cf_codice_cognome)
            if trovato:
                if cognome and trovato != cognome:
                    log.info("Cognome corretto col codice fiscale: '%s' -> '%s'",
                             cognome, trovato)
                else:
                    log.info("Cognome ricavato dal codice fiscale: %s", trovato)
                cognome = trovato
        if not nome or _cf_codice_nome(nome) != cod_nom:
            trovato = _cerca(cod_nom, _cf_codice_nome)
            if trovato:
                if nome and trovato != nome:
                    log.info("Nome corretto col codice fiscale: '%s' -> '%s'",
                             nome, trovato)
                else:
                    log.info("Nome ricavato dal codice fiscale: %s", trovato)
                nome = trovato

        # Log di coerenza (non blocca: serve solo a segnalare eventuali dubbi)
        if cognome and nome:
            coer_cog = _cf_codice_cognome(cognome) == cod_cog
            coer_nom = _cf_codice_nome(nome) == cod_nom
            if coer_cog and coer_nom:
                log.info("Cognome e nome COERENTI col codice fiscale.")
            else:
                log.warning("Cognome/nome non combaciano perfettamente col codice "
                            "fiscale (possibile errore OCR nel CF o nel nome): "
                            "uso comunque i campi del documento.")

    # --- Usa i valori (etichetta e/o CF) se disponibili ------------------
    if cognome and nome and len(cognome) >= 2 and len(nome) >= 2:
        risultato = f"{tipo}_{_titola(cognome)}_{_titola(nome)}"
        log.info("Nome estratto: %s", risultato)
        return risultato

    # Tipo noto ma nome non estraibile: meglio l'LLM (o fallback a valle)
    log.info("Documento '%s' riconosciuto ma nome non estraibile deterministicamente.",
             tipo)
    return None


def _solo_lettere_spazi(s):
    """Come _solo_lettere ma conserva gli spazi (per il matching di frasi)."""
    trad = str.maketrans("ÀÁÂÃÄÈÉÊËÌÍÎÏÒÓÔÕÖÙÚÛÜÇ", "AAAAAEEEEIIIIOOOOOUUUUC")
    s = s.translate(trad)
    return re.sub(r"[^A-Za-z ]", " ", s)


def determina_nome_file(testo, log, testo_cf=None):
    """Sceglie il nome file: prima l'estrazione deterministica verificata
    (documenti d'identita'), poi l'LLM come fallback. Ritorna il nome gia'
    sanificato oppure None. 'testo_cf' e' il testo (tutte le pagine) su cui
    cercare il codice fiscale se non e' nella pagina del documento."""
    # 1) Estrazione deterministica + verifica CF (alta precisione sui nomi)
    nome = _estrai_identita(testo, log, testo_cf)
    if nome:
        return sanifica_nome(nome)

    # 2) Fallback: LLM
    log.info("Richiesta nome file al modello '%s'...", CONFIG["OLLAMA_MODEL"])
    nome = nome_da_llm(testo, log)
    if nome:
        log.info("Nome proposto dall'LLM: %s", nome)
        return nome
    return None


# ===========================================================================
# LLM LOCALE (Ollama) -> nome file
# ===========================================================================
SYSTEM_PROMPT = (
    "Sei un assistente che assegna nomi di file a documenti italiani scansionati. "
    "Ricevi il testo grezzo (OCR, che puo' contenere errori) e proponi UN SOLO "
    "nome file breve e descrittivo, SENZA estensione.\n"
    "\n"
    "PRIMA DI TUTTO, STABILISCI SE E' UN DOCUMENTO D'IDENTITA':\n"
    "- E' un documento d'identita' SOLO se nel testo compare esplicitamente una "
    "di queste diciture: 'CARTA DI IDENTITA' (anche scritta 'CARTA D'IDENTITA'), "
    "'TESSERA SANITARIA', 'SERVIZIO SANITARIO NAZIONALE', 'PATENTE DI GUIDA', "
    "'PASSAPORTO'.\n"
    "- Se quelle diciture NON ci sono, NON e' un documento d'identita': e' un "
    "foglio qualsiasi (fattura, lettera, modulo...). In quel caso nomina il file "
    "in base al contenuto e NON inventare un intestatario che non c'e'.\n"
    "- Basa il nome sull'intestatario (cognome/nome) SOLO se hai riconosciuto un "
    "documento d'identita' con una di quelle diciture.\n"
    "\n"
    "COME RICONOSCERE IL DOCUMENTO E L'INTESTATARIO:\n"
    "- CARTA D'IDENTITA': contiene 'CARTA DI IDENTITA', 'COMUNE DI', i campi "
    "'COGNOME/SURNAME' e 'NOME/NAME'. L'intestatario e' COGNOME + NOME riportati "
    "in quei campi (di solito in MAIUSCOLO). Tipo documento: 'carta_identita'.\n"
    "- TESSERA SANITARIA / TEAM: contiene 'TESSERA SANITARIA', 'SERVIZIO SANITARIO "
    "NAZIONALE' o 'Tessera Europea Assicurazione Malattia'. L'intestatario e' il "
    "COGNOME e NOME stampati; c'e' anche il CODICE FISCALE (16 caratteri). "
    "Tipo documento: 'tessera_sanitaria'.\n"
    "- PATENTE: 'PATENTE DI GUIDA'. Tipo: 'patente'.\n"
    "- PASSAPORTO: 'PASSAPORTO/PASSPORT'. Tipo: 'passaporto'.\n"
    "- CODICE FISCALE (tesserino): 'CODICE FISCALE'. Tipo: 'codice_fiscale'.\n"
    "- Altri: fattura, bolletta, contratto, referto, lettera, ricevuta, busta_paga.\n"
    "\n"
    "REGOLE PER IL NOME:\n"
    "- Formato consigliato: <TipoDocumento>_<Cognome>_<Nome> (aggiungi la data "
    "AAAA-MM-GG solo se chiaramente presente e pertinente).\n"
    "- Correggi ovvi errori OCR nei nomi propri (es. '0'->'O', '1'->'I') quando "
    "sei ragionevolmente sicuro; mantieni Cognome e Nome con l'iniziale "
    "maiuscola.\n"
    "- NON inventare nomi: se il nome non e' leggibile, usa solo il tipo "
    "documento (es. 'tessera_sanitaria').\n"
    "- NON inserire mai nel nome il codice fiscale completo, numeri di documento "
    "o altri dati sensibili.\n"
    "- Usa SOLO lettere, numeri, underscore e trattini; spazi -> underscore.\n"
    "- Vietati i caratteri \\ / : * ? \" < > | e ogni carattere illegale su Windows.\n"
    "- Massimo 60 caratteri.\n"
    "\n"
    "ESEMPI:\n"
    "OCR: 'COMUNE DI MILANO CARTA DI IDENTITA COGNOME/SURNAME ROSSI NOME/NAME "
    "MARIO ...' -> {\"filename\":\"carta_identita_Rossi_Mario\"}\n"
    "OCR: 'SERVIZIO SANITARIO NAZIONALE TESSERA SANITARIA BIANCHI LUCIA "
    "CODICE FISCALE BNCLCU...' -> {\"filename\":\"tessera_sanitaria_Bianchi_Lucia\"}\n"
    "\n"
    "OUTPUT:\n"
    "- Rispondi ESCLUSIVAMENTE con un oggetto JSON valido: "
    '{\"filename\":\"nome_del_file\"}\n'
    "- Nessun testo prima o dopo il JSON, nessuna spiegazione."
)


def nome_da_llm(testo_ocr, log):
    """Chiede a Ollama un nome file pulito. Ritorna una stringa gia' sanificata,
    oppure None se fallisce (il chiamante usera' il fallback)."""
    import requests

    if not testo_ocr:
        return None

    # Limita il testo inviato (i modelli 3B hanno contesto ridotto)
    estratto = testo_ocr[:4000]

    payload = {
        "model": CONFIG["OLLAMA_MODEL"],
        "system": SYSTEM_PROMPT,
        "prompt": (
            "Testo OCR del documento (puo' contenere errori):\n"
            "-----\n" + estratto + "\n-----\n"
            "Restituisci solo il JSON con il nome file."
        ),
        "stream": False,
        "format": "json",           # forza output JSON su Ollama
        "options": {"temperature": 0.1},
    }

    attesa = Attesa("Analisi LLM (nome file)")
    try:
        r = requests.post(CONFIG["OLLAMA_URL"] + "/api/generate",
                          json=payload, timeout=CONFIG["OLLAMA_TIMEOUT"])
        r.raise_for_status()
        risposta = r.json().get("response", "")
        log.debug("Risposta LLM grezza: %s", risposta)
    except Exception as e:
        log.error("Chiamata a Ollama fallita: %s", e)
        return None
    finally:
        attesa.fine()

    nome = _estrai_filename(risposta, log)
    if not nome:
        return None
    return sanifica_nome(nome)


def _estrai_filename(risposta, log):
    """Parsing robusto: prova JSON diretto, poi regex sul campo filename."""
    if not risposta:
        return None
    # 1) JSON pulito
    try:
        obj = json.loads(risposta)
        if isinstance(obj, dict) and obj.get("filename"):
            return str(obj["filename"])
    except Exception:
        pass
    # 2) Cerca un blocco {...} nel testo
    m = re.search(r"\{.*?\}", risposta, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            if obj.get("filename"):
                return str(obj["filename"])
        except Exception:
            pass
    # 3) Regex diretta "filename": "..."
    m = re.search(r'"filename"\s*:\s*"([^"]+)"', risposta)
    if m:
        return m.group(1)
    log.warning("Impossibile estrarre 'filename' dalla risposta LLM.")
    return None


# ===========================================================================
# SANIFICAZIONE NOME FILE
# ===========================================================================
def sanifica_nome(nome):
    """Rende il nome sicuro per Windows: rimuove caratteri illegali, spazi ->
    underscore, taglia a MAX_FILENAME_LEN."""
    if not nome:
        return ""
    nome = nome.strip().strip(".")
    # Rimuovi estensione eventuale
    nome = re.sub(r"\.(pdf|jpg|jpeg|png|txt)$", "", nome, flags=re.IGNORECASE)
    # Spazi -> underscore
    nome = re.sub(r"\s+", "_", nome)
    # Caratteri illegali Windows  \ / : * ? " < > |  + controllo
    nome = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", nome)
    # Solo set sicuro
    nome = re.sub(r"[^A-Za-z0-9._\-]", "", nome)
    # Underscore multipli
    nome = re.sub(r"_+", "_", nome).strip("_-.")
    # Nomi riservati Windows
    riservati = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} \
        | {f"LPT{i}" for i in range(1, 10)}
    if nome.upper() in riservati:
        nome = "doc_" + nome
    return nome[:CONFIG["MAX_FILENAME_LEN"]].strip("_-.")


def nome_fallback():
    """Nome di riserva basato su timestamp."""
    return "scansione_" + datetime.now().strftime("%Y%m%d_%H%M%S")


def chiedi_servizio(log):
    """Chiede all'utente il tipo di servizio da inserire nel nome file."""
    try:
        risposta = input("\nTipo di servizio richiesto (es. rinnovo, iscrizione, "
                         "richiesta_bonus)?\n Servizio > ").strip()
    except EOFError:
        risposta = ""
    servizio = sanifica_nome(risposta)
    if servizio:
        log.info("Tipo di servizio: %s", servizio)
    return servizio


def estrai_data(testo, log):
    """Ritorna la data odierna (data di scansione) in formato AAAA-MM-GG."""
    oggi = datetime.now().strftime("%Y-%m-%d")
    log.info("Uso la data odierna: %s", oggi)
    return oggi


def _sezione_residenza(testo):
    """Isola la porzione di testo che parte dalla voce 'INDIRIZZO DI RESIDENZA'
    (il comune e' scritto subito sotto). Se quella dicitura non c'e', ripiega
    sulla sola voce 'RESIDENZA'.

    NB: fronte e retro del documento possono trovarsi sulla STESSA facciata
    scansionata (es. fotocopia fronte-retro su un unico foglio). Non ci si basa
    quindi sulla pagina, ma sull'ETICHETTA. Ritorna il testo dalla voce in poi,
    o None se nessuna delle due e' presente."""
    # 1) dicitura completa "INDIRIZZO DI RESIDENZA" (tollerante alla spaziatura)
    trovati = [m.start() for m in
               re.finditer(r"INDIRIZZO[\s:.]*DI[\s:.]*RESIDEN[ZT]A", testo,
                           re.IGNORECASE)]
    # 2) ripiego: sola voce "RESIDENZA" oppure "RESIDENCE" (versione inglese)
    if not trovati:
        trovati = [m.start() for m in
                   re.finditer(r"RESIDEN[ZTC][AE]", testo, re.IGNORECASE)]
    if not trovati:
        return None
    # Piu' passate OCR possono aver letto la stessa voce in modi diversi:
    # si restituiscono tutte le occorrenze, cosi' si prova la migliore.
    return [testo[i: i + 250] for i in trovati]


_TIPI_STRADA = {"VIA", "VIALE", "PIAZZA", "CORSO", "LARGO", "VICOLO",
                "STRADA", "CONTRADA", "FRAZIONE", "LOCALITA", "LOC",
                "INT", "SCALA", "PIANO", "SNC"}


def _normalizza_ocr_parola(parola):
    """Corregge le confusioni cifra/lettera tipiche dell'OCR dentro i nomi
    propri (es. 'SAUZZ0LE' -> 'SAUZZOLE'). Ritorna solo lettere maiuscole."""
    tradotte = (parola.upper().replace("0", "O").replace("1", "I")
                .replace("5", "S").replace("8", "B").replace("4", "A"))
    return _solo_lettere(tradotte)


def _consolida_con_testo(candidato, testo, log):
    """Il nome del comune compare spesso PIU' VOLTE nel documento (tipicamente
    anche nel campo 'COMUNE DI' del fronte, stampato piu' grande e letto
    meglio). Se nel testo esiste una parola molto simile al candidato ma con
    lettura piu' pulita/frequente, si preferisce quella.

    Sfrutta la ridondanza del documento: nessun elenco esterno di comuni."""
    import difflib
    from collections import Counter

    if not candidato or not testo:
        return candidato
    freq, puliti = Counter(), Counter()
    for w in re.findall(r"[A-Za-zÀ-Ù0-9']{4,}", testo):
        n = _normalizza_ocr_parola(w)
        if len(n) < 4 or n in _PAROLE_ETICHETTA or n in _TIPI_STRADA:
            continue
        freq[n] += 1
        # Lettura "pulita": non ha avuto bisogno di correggere cifre in lettere
        # (es. 'SALIZZOLE' e' piu' affidabile di 'Sauzz0LE' -> 'SAUZZOLE').
        if not any(c.isdigit() for c in w):
            puliti[n] += 1
    if not freq:
        return candidato

    def punteggio(t):
        return (puliti[t], freq[t], len(t))

    simili = difflib.get_close_matches(candidato, list(freq.keys()),
                                       n=6, cutoff=0.72)
    if not simili:
        return candidato
    migliore = max(simili, key=punteggio)
    if migliore != candidato and punteggio(migliore) > punteggio(candidato):
        log.info("Comune consolidato col resto del documento: '%s' -> '%s' "
                 "(%d letture pulite su %d occorrenze)", candidato, migliore,
                 puliti[migliore], freq[migliore])
        return migliore
    return candidato


def _comune_da_residenza(sezione, log, testo_completo=""):
    """Estrae il comune scritto sotto la voce 'INDIRIZZO DI RESIDENZA'.
    Ordine: 1) riga indirizzo (deterministico), 2) CAP, 3) LLM (fallback,
    con controllo anti-invenzione)."""
    # --- 1) Riga indirizzo: 'VIA CAMPAGNOL, 165 INT.1 SALIZZOLE (VR)'.
    #     Negli indirizzi CIE il comune e' l'ULTIMA parola della riga, esclusi
    #     i tipi di strada, le etichette e la sigla provincia (2 lettere).
    for riga in sezione.splitlines():
        up = riga.upper()
        parole = re.findall(r"[A-ZÀ-Ù][A-ZÀ-Ù0-9']+", up)
        if not any(_normalizza_ocr_parola(w) in _TIPI_STRADA for w in parole):
            continue
        candidati = []
        for w in parole:
            n = _normalizza_ocr_parola(w)     # 'SAUZZ0LE' -> 'SAUZZOLE'
            if (len(n) >= 3 and n not in _TIPI_STRADA
                    and n not in _PAROLE_ETICHETTA):
                candidati.append(n)
        # Servono ALMENO due parole utili: la prima e' il nome della via, il
        # comune viene dopo (es. 'VIA CAMPAGNOL 165 SALIZZOLE'). Se ce n'e' una
        # sola, la riga e' troncata e quella parola e' la VIA, non il comune.
        if len(candidati) >= 2:
            # consolida la lettura con le altre occorrenze nel documento
            paese = _consolida_con_testo(candidati[-1], testo_completo, log)
            paese = sanifica_nome(paese)
            if paese:
                log.info("Comune di residenza (riga indirizzo): %s", paese)
                return paese
        elif candidati:
            log.info("Riga indirizzo incompleta ('%s' sembra il nome della via, "
                     "non il comune): la scarto.", candidati[-1])

    # --- 2) Negli indirizzi italiani il comune segue il CAP (5 cifre) ---
    m = re.search(r"\b\d{5}\b[\s,]+([A-Za-zÀ-Ù'\.\- ]{2,30})", sezione)
    if m and m.group(1).strip():
        grezzo = re.sub(r"\(?\b[A-Z]{2}\b\)?\s*$", "", m.group(1)).strip()
        paese = sanifica_nome(grezzo)
        if paese:
            log.info("Comune di residenza (regex CAP): %s", paese)
            return paese

    # --- 3) LLM: fallback con istruzioni mirate ---
    try:
        import requests
        payload = {
            "model": CONFIG["OLLAMA_MODEL"],
            "system": (
                "Ricevi una porzione di testo (OCR) di un documento d'identita' "
                "italiano che inizia con la voce 'INDIRIZZO DI RESIDENZA'. Il "
                "COMUNE di residenza e' scritto SUBITO SOTTO (o subito dopo) la "
                "voce 'INDIRIZZO DI RESIDENZA'. Restituisci ESATTAMENTE quel "
                "comune (solo la citta'), ignorando la via, il numero civico, il "
                "CAP e la provincia. NON usare eventuali altri 'COMUNE DI' "
                "presenti altrove (es. il comune di rilascio del documento). "
                'Rispondi SOLO con JSON {"comune":"..."}. Vuoto se illeggibile.'
            ),
            "prompt": sezione[:1500],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.0},
        }
        attesa = Attesa("Analisi LLM (residenza)")
        try:
            r = requests.post(CONFIG["OLLAMA_URL"] + "/api/generate",
                              json=payload, timeout=CONFIG["OLLAMA_TIMEOUT"])
        finally:
            attesa.fine()
        r.raise_for_status()
        m = re.search(r'"comune"\s*:\s*"([^"]*)"', r.json().get("response", ""))
        if m and m.group(1).strip():
            paese = sanifica_nome(m.group(1))
            # ANTI-INVENZIONE: accetta la risposta dell'LLM SOLO se quella
            # parola compare davvero nel testo OCR (confronto compattato).
            # Un LLM piccolo puo' "allucinare" un comune mai scritto nel testo.
            comp_sezione = re.sub(r"[^A-Z]", "", sezione.upper())
            comp_paese = re.sub(r"[^A-Z]", "", paese.upper())
            if paese and comp_paese and comp_paese in comp_sezione:
                log.info("Comune di residenza (LLM, verificato nel testo): %s", paese)
                return paese
            if paese:
                log.warning("L'LLM ha proposto '%s' ma non compare nel testo OCR: "
                            "scartato (possibile invenzione).", paese)
    except Exception as e:
        log.debug("Estrazione comune via LLM fallita: %s", e)

    return ""


def _chiedi_paese(log, suggerito=""):
    """Chiede all'utente il paese/comune di residenza. Se c'e' un suggerimento,
    INVIO lo accetta."""
    if suggerito:
        prompt = f"\nComune di residenza [{suggerito}] (INVIO per confermare) > "
    else:
        prompt = ("\nVoce 'RESIDENZA' non riconosciuta: inserisci il comune di "
                  "residenza\n Comune di residenza > ")
    try:
        risposta = input(prompt).strip()
    except EOFError:
        risposta = ""
    if not risposta:
        return sanifica_nome(suggerito)
    return sanifica_nome(risposta)


def estrai_paese_residenza(pagine, log):
    """Determina il comune di residenza agganciandosi alla voce 'RESIDENZA'
    (il comune e' scritto subito sotto). Funziona anche se fronte e retro del
    documento sono sulla stessa facciata. Se la voce 'RESIDENZA' non viene
    riconosciuta, o il comune non e' estraibile, chiede conferma all'utente."""
    testo = "\n".join(pagine) if pagine else ""

    sezioni = _sezione_residenza(testo)
    if not sezioni:
        log.info("Voce 'RESIDENZA' non trovata: chiedo il comune all'utente.")
        return _chiedi_paese(log)

    # Prova ogni occorrenza della voce (le varie passate OCR possono averla
    # letta con qualita' diversa) e tiene il primo risultato valido.
    for sezione in sezioni:
        paese = _comune_da_residenza(sezione, log, testo)
        if paese:
            return paese

    # Riga di residenza illeggibile: si ripiega sul comune che rilascia il
    # documento (campo 'COMUNE DI / MUNICIPALITY'), che nella grande maggioranza
    # dei casi coincide con la residenza. Se non c'e' nemmeno quello, si chiede.
    ripiego = _comune_del_documento(testo, log)
    if ripiego:
        log.info("Riga di residenza illeggibile: uso il comune del documento "
                 "(campo 'COMUNE DI'): %s", ripiego)
        return ripiego
    log.info("Comune non estraibile: chiedo conferma all'utente.")
    return _chiedi_paese(log)


def _comune_del_documento(testo, log):
    """Legge il campo 'COMUNE DI / MUNICIPALITY' (comune che ha rilasciato il
    documento). Usato solo come SUGGERIMENTO quando la residenza e' illeggibile.
    Tollerante agli errori OCR sull'etichetta (es. 'ECMUNE', 'AMURNICIPALITY')."""
    for pat in (r"MUNICIPALIT[AY]?", r"NICIPALIT", r"C[O0]MUNE", r"CMUNE"):
        for m in re.finditer(pat, testo, re.IGNORECASE):
            coda = testo[m.end(): m.end() + 60]
            for w in re.findall(r"[A-ZÀ-Ù][A-ZÀ-Ù']{3,}", coda.upper()):
                n = _normalizza_ocr_parola(w)
                if len(n) >= 4 and n not in _PAROLE_ETICHETTA \
                        and n not in _TIPI_STRADA:
                    paese = sanifica_nome(_consolida_con_testo(n, testo, log))
                    if paese:
                        log.info("Comune dal campo 'COMUNE DI': %s", paese)
                        return paese
    return ""


def componi_nome(base, paese, servizio, data, log):
    """Assembla il nome finale: <base>_<paese>_<servizio>_<data>, saltando le
    parti vuote e sanificando il risultato."""
    parti = [p for p in (base, paese, servizio, data) if p]
    nome = sanifica_nome("_".join(parti))
    log.info("Nome composto: %s", nome)
    return nome or nome_fallback()


def salva_ocr_debug(testo, log):
    """Salva il testo OCR grezzo in un .txt (per diagnosticare nomi sbagliati)."""
    if not CONFIG.get("SAVE_OCR_DEBUG", False):
        return
    try:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        percorso = os.path.join(CONFIG["LOG_DIR"], f"ocr_{stamp}.txt")
        with open(percorso, "w", encoding="utf-8") as f:
            f.write(testo)
        log.info("Testo OCR salvato per diagnosi: %s", percorso)
    except Exception as e:
        log.debug("Impossibile salvare il debug OCR: %s", e)


def conferma_nome(nome, log):
    """Mostra il nome proposto e permette di accettarlo (INVIO) o correggerlo.
    Ritorna il nome definitivo (sanificato)."""
    if not CONFIG.get("CONFIRM_NAME", True):
        return nome
    print("\n----------------------------------------------")
    print(f" Nome proposto:  {nome}")
    print(" Premi INVIO per accettare, oppure scrivi il nome corretto")
    print(" (senza estensione .pdf) e premi INVIO.")
    print("----------------------------------------------")
    try:
        risposta = input(" Nome file > ").strip()
    except EOFError:
        risposta = ""
    if not risposta:
        return nome
    corretto = sanifica_nome(risposta)
    if not corretto:
        log.warning("Nome inserito non valido, mantengo: %s", nome)
        return nome
    log.info("Nome corretto manualmente: %s", corretto)
    return corretto


def percorso_univoco(cartella, nome_base, estensione=".pdf"):
    """Aggiunge _2, _3, ... se il file esiste gia'."""
    candidato = os.path.join(cartella, nome_base + estensione)
    if not os.path.exists(candidato):
        return candidato
    i = 2
    while True:
        candidato = os.path.join(cartella, f"{nome_base}_{i}{estensione}")
        if not os.path.exists(candidato):
            return candidato
        i += 1


# ===========================================================================
# PULIZIA TEMP
# ===========================================================================
def pulisci_temp(temp_dir, log):
    """Elimina i file temporanei."""
    try:
        for f in os.listdir(temp_dir):
            try:
                os.remove(os.path.join(temp_dir, f))
            except Exception:
                pass
        os.rmdir(temp_dir)
        log.info("File temporanei eliminati.")
    except Exception as e:
        log.warning("Pulizia temp non completata: %s", e)


# ===========================================================================
# MAIN
# ===========================================================================
def main():
    parser = argparse.ArgumentParser(description="Scansione Brother + OCR + naming LLM")
    parser.add_argument("--device-id", help="Forza un DEVICE_ID WIA")
    parser.add_argument("--naps2", action="store_true", help="Usa il fallback NAPS2")
    parser.add_argument("--list-devices", action="store_true",
                        help="Elenca i device WIA ed esci")
    args = parser.parse_args()

    log = setup_logging(CONFIG["LOG_DIR"])
    log.info("=== Avvio scan_brother_ai ===")

    # Solo elenco device
    if args.list_devices:
        try:
            log.info("Device WIA disponibili:")
            elenca_device_wia(log)
        except Exception as e:
            log.error("Errore elenco device: %s", e)
        return

    # Controllo dipendenze
    try:
        controlla_dipendenze(log, usa_naps2=args.naps2)
    except RuntimeError as e:
        log.error(str(e))
        input("\nPremi INVIO per uscire...")
        sys.exit(1)

    os.makedirs(CONFIG["OUTPUT_DIR"], exist_ok=True)
    temp_dir = tempfile.mkdtemp(prefix="scan_", dir=os.environ.get("TEMP"))
    log.info("Cartella temporanea: %s", temp_dir)

    immagini = []
    pdf_temp = None
    try:
        # 1) SCANSIONE + OCR (per pagina)
        if args.naps2:
            pdf_temp = scansione_naps2_fallback(temp_dir, log)
            pagine_testo = ocr_da_pdf(pdf_temp, log)
        else:
            try:
                immagini = scansiona_wia(temp_dir, log, args.device_id)
            except RuntimeError as e:
                log.error("Scansione WIA fallita: %s", e)
                log.info("Suggerimento: prova il fallback NAPS2 con --naps2")
                raise
            # 3) OCR (sulle immagini) -> lista di testi per pagina
            pagine_testo = ocr_testo(immagini, log)

        # Testo unito (per il naming complessivo)
        testo = "\n".join(pagine_testo).strip()

        # 2) PDF temporaneo (se percorso immagini)
        if not args.naps2:
            pdf_temp = os.path.join(temp_dir, "documento.pdf")
            immagini_in_pdf(immagini, pdf_temp, log)

        # Salva l'OCR grezzo per eventuale diagnosi di nomi sbagliati
        salva_ocr_debug(testo, log)

        # 3b) Se sono stati messi piu' fogli, individua QUALE pagina e' il
        #     documento d'identita' (dalla scritta 'CARTA D'IDENTITA'/'TESSERA
        #     SANITARIA'...). Nome e residenza si estraggono SOLO da quella,
        #     ignorando gli altri fogli.
        pag_doc, tipo_doc = _pagina_documento_identita(pagine_testo, log)
        testo_naming = pag_doc if pag_doc else testo
        pagine_residenza = [pag_doc] if pag_doc else pagine_testo

        # 4) NOME base: estrazione deterministica verificata (documenti
        #    d'identita'), poi LLM come fallback. Il codice fiscale viene cercato
        #    su TUTTE le pagine (puo' stare sul retro, in un'altra pagina).
        base = determina_nome_file(testo_naming, log, testo_cf=testo)
        if not base:
            base = nome_fallback()
            log.warning("Nome base non riconosciuto, uso fallback: %s", base)

        # 4b) Campi aggiuntivi: paese di residenza (letto dalla voce 'RESIDENZA'
        #     del documento, con conferma utente se non riconosciuta), tipo di
        #     servizio (chiesto all'utente) e data.
        paese = estrai_paese_residenza(pagine_residenza, log)
        servizio = chiedi_servizio(log)
        data = estrai_data(testo, log)

        # 4c) Composizione: <base>_<paese>_<servizio>_<data>
        nome = componi_nome(base, paese, servizio, data, log)

        # 4d) Conferma/correzione manuale prima di salvare
        nome = conferma_nome(nome, log)

        # 5) SALVATAGGIO definitivo
        destinazione = percorso_univoco(CONFIG["OUTPUT_DIR"], nome, ".pdf")
        import shutil
        shutil.copy2(pdf_temp, destinazione)
        log.info("PDF salvato in: %s", destinazione)
        print("\n==============================================")
        print(f" DOCUMENTO SALVATO:\n   {destinazione}")
        print("==============================================\n")

    except Exception as e:
        log.error("Processo interrotto: %s", e)
        input("\nPremi INVIO per uscire...")
        sys.exit(1)
    finally:
        # 5) pulizia temp
        pulisci_temp(temp_dir, log)

    log.info("=== Fine ===")
    # Pausa finale utile in caso di doppio click
    input("Premi INVIO per chiudere...")


if __name__ == "__main__":
    main()
