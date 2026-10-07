# -*- coding: utf-8 -*-
"""
============================================================================
 scan_gui.py - Interfaccia moderna (CustomTkinter) per scan_brother_ai.py
 - Anteprima delle pagine scansionate, con possibilita' di aggiungerne altre
 - Aggiunta di pagine da file gia' esistenti (PDF o foto), senza scanner
 - Impostazioni raggiungibili dall'icona ingranaggio
 Avvio: doppio click su Avvia_ScanApp.bat (o: py scan_gui.py)
============================================================================
"""

import os
import sys
import json
import queue
import shutil
import builtins
import tempfile
import threading
import customtkinter as ctk
from tkinter import filedialog, messagebox
from PIL import Image

# Il motore e' scan_brother_ai.py: prima la copia locale, poi la cartella sopra.
if getattr(sys, "frozen", False):
    BASE = os.path.dirname(sys.executable)
else:
    BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.dirname(BASE))
import scan_brother_ai as engine  # noqa: E402
import aggiornamenti  # noqa: E402
import certificato  # noqa: E402
import finestra_telefono  # noqa: E402

CONFIG_FILE = os.path.join(BASE, "scan_gui_config.json")
PARAMETRI = ["DEVICE_ID", "DEVICE_NAME", "DPI", "COLOR_MODE", "SOURCE",
             "OUTPUT_DIR", "OLLAMA_MODEL", "TESSERACT_PATH", "OCR_LANG",
             "PDF_QUALITA", "AUTO_INSTALL", "SAVE_OCR_DEBUG"]

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Marcatore restituito dai dialoghi quando l'utente preme Annulla / chiude la
# finestra (da NON confondere con una stringa vuota confermata con OK).
ANNULLATO = object()


class OperazioneAnnullata(Exception):
    """Sollevata quando l'utente annulla un dialogo: interrompe l'elaborazione
    senza salvare nulla."""


def _imposta_appid():
    """Assegna un AppUserModelID esplicito: senza, Windows raggruppa la finestra
    sotto python/exe generico e la TASKBAR mostra un'icona diversa da quella
    della finestra. Con l'AppID la taskbar usa l'icona della finestra."""
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "ScansioneBrother.OCR.LLM.1")
    except Exception:
        pass


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"Scansione Brother + OCR + LLM  v{aggiornamenti.VERSIONE}")
        self.geometry("1180x700")
        self.minsize(1000, 560)
        # Icona finestra = stessa dell'eseguibile (icona CustomTkinter)
        self._imposta_icona()

        # Sessione: pagine accumulate prima dell'elaborazione
        self.pagine = []
        self.contatore = 0
        self.session_dir = tempfile.mkdtemp(prefix="scan_sess_")
        self.req_queue = queue.Queue()
        self.occupato = False
        self._thumb_refs = []
        self._prog_win = None
        self._tel_server = None
        self._tel_win = None
        self._tel_lista = None
        self._tel_qr_ref = None
        self._telefoni_correnti = []

        self._carica_config()
        self._costruisci_ui()
        self.after(100, self._poll_queue)
        self.protocol("WM_DELETE_WINDOW", self._chiudi)
        # Controllo aggiornamenti in background (non rallenta l'avvio)
        threading.Thread(target=self._controlla_aggiornamenti,
                         daemon=True).start()
        # Idem per il certificato di firma: si installa da solo se manca o
        # se nel frattempo ne e' uscito uno nuovo (nessun passaggio manuale).
        threading.Thread(target=self._controlla_certificato,
                         daemon=True).start()

    # ------------------------------------------------------------------ UI
    def _costruisci_ui(self):
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # --- Barra superiore ---
        top = ctk.CTkFrame(self, corner_radius=0, fg_color=("gray90", "gray13"))
        top.grid(row=0, column=0, columnspan=2, sticky="new")
        top.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(top, text="  Scansione documenti",
                     font=ctk.CTkFont(size=20, weight="bold")
                     ).grid(row=0, column=0, sticky="w", padx=14, pady=10)
        ctk.CTkButton(top, text="⚙", width=44, height=36,
                      font=ctk.CTkFont(size=20),
                      command=self._apri_impostazioni
                      ).grid(row=0, column=1, padx=12, pady=8)

        # --- Colonna sinistra: anteprime ---
        sx = ctk.CTkFrame(self, width=300)
        sx.grid(row=1, column=0, sticky="nsw", padx=(12, 6), pady=8)
        sx.grid_propagate(False)
        sx.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(sx, text="Anteprima pagine",
                     font=ctk.CTkFont(size=14, weight="bold")
                     ).grid(row=0, column=0, pady=(10, 4))
        self.lista = ctk.CTkScrollableFrame(sx, width=270)
        self.lista.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

        # --- Colonna destra: azioni + log ---
        dx = ctk.CTkFrame(self, fg_color="transparent")
        dx.grid(row=1, column=1, sticky="nsew", padx=(6, 12), pady=8)
        dx.grid_columnconfigure(0, weight=1)
        dx.grid_rowconfigure(2, weight=1)

        azioni = ctk.CTkFrame(dx)
        azioni.grid(row=0, column=0, sticky="new")
        azioni.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)

        self.b_scan = ctk.CTkButton(
            azioni, text="\U0001F4C4  Scansiona pagine", height=52,
            font=ctk.CTkFont(size=15, weight="bold"), command=self.scansiona)
        self.b_scan.grid(row=0, column=0, padx=8, pady=10, sticky="ew")

        # Stesso flusso della scansione, ma partendo da file gia' esistenti
        # (PDF ricevuto via mail, foto scattata col telefono...).
        self.b_importa = ctk.CTkButton(
            azioni, text="\U0001F4C1  Aggiungi PDF/foto", height=52,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color="#1f5f8b", hover_color="#164a6d",
            command=self.importa)
        self.b_importa.grid(row=0, column=1, padx=8, pady=10, sticky="ew")

        # Server locale: il telefono scatta le pagine e le invia al programma.
        self.b_telefono = ctk.CTkButton(
            azioni, text="\U0001F4F1  Scansiona con telefono", height=52,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color="#6a1f8b", hover_color="#511668",
            command=self.scansiona_con_telefono)
        self.b_telefono.grid(row=0, column=2, padx=8, pady=10, sticky="ew")

        self.b_elabora = ctk.CTkButton(
            azioni, text="✅  Elabora e salva PDF", height=52,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color="#2e7d32", hover_color="#1b5e20",
            command=self.elabora)
        self.b_elabora.grid(row=0, column=3, padx=8, pady=10, sticky="ew")

        self.b_svuota = ctk.CTkButton(
            azioni, text="\U0001F5D1  Svuota", height=52,
            fg_color="#8e2424", hover_color="#6f1c1c",
            command=self.svuota)
        self.b_svuota.grid(row=0, column=4, padx=8, pady=10, sticky="ew")

        self.stato = ctk.CTkLabel(
            dx, text="Pronto. Scansiona la prima pagina "
                     "oppure aggiungi un PDF/una foto.", anchor="w")
        self.stato.grid(row=1, column=0, sticky="ew", padx=4, pady=(2, 4))

        self.log_box = ctk.CTkTextbox(dx, font=("Consolas", 11))
        self.log_box.grid(row=2, column=0, sticky="nsew")
        self.log_box.configure(state="disabled")

    # ------------------------------------------------------- Anteprime
    def _aggiungi_anteprima(self, percorso):
        idx = len(self.pagine)
        riga = ctk.CTkFrame(self.lista)
        riga.pack(fill="x", pady=4)
        try:
            img = Image.open(percorso)
            img.thumbnail((210, 280))
            cimg = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
            self._thumb_refs.append(cimg)
            ctk.CTkLabel(riga, image=cimg, text="").pack(pady=(6, 2))
        except Exception:
            ctk.CTkLabel(riga, text="(anteprima non disponibile)").pack(pady=6)
        piede = ctk.CTkFrame(riga, fg_color="transparent")
        piede.pack(fill="x", padx=6, pady=(0, 6))
        ctk.CTkLabel(piede, text=f"Pagina {idx}").pack(side="left", padx=4)
        ctk.CTkButton(piede, text="✕", width=30, height=24,
                      fg_color="#8e2424", hover_color="#6f1c1c",
                      command=lambda p=percorso, r=riga: self._rimuovi(p, r)
                      ).pack(side="right")

    def _rimuovi(self, percorso, riga):
        if self.occupato:
            return
        if percorso in self.pagine:
            self.pagine.remove(percorso)
        riga.destroy()
        self._rinumera()

    def _rinumera(self):
        for i, riga in enumerate(self.lista.winfo_children(), 1):
            for f in riga.winfo_children():
                for w in f.winfo_children():
                    if isinstance(w, ctk.CTkLabel) and str(w.cget("text")).startswith("Pagina"):
                        w.configure(text=f"Pagina {i}")
        self.stato.configure(text=f"{len(self.pagine)} pagina/e in sessione.")

    def _svuota_anteprime(self):
        for w in self.lista.winfo_children():
            w.destroy()
        self._thumb_refs.clear()

    def svuota(self):
        if self.occupato:
            return
        self.pagine.clear()
        self.contatore = 0
        self._svuota_anteprime()
        self.stato.configure(text="Sessione svuotata.")

    # --------------------------------------------------------------- Log
    def log(self, testo):
        self.req_queue.put(("log", testo + "\n"))

    def _append(self, testo):
        self.log_box.configure(state="normal")
        testo = testo.replace("\r\n", "\n")
        if "\r" in testo:
            parti = testo.split("\r")
            self.log_box.delete("end-1l", "end-1c")
            self.log_box.insert("end", parti[-1])
        else:
            self.log_box.insert("end", testo)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    # ----------------------------------------------- Ponte thread -> GUI
    def _poll_queue(self):
        try:
            while True:
                voce = self.req_queue.get_nowait()
                tipo = voce[0]
                if tipo == "log":
                    self._append(voce[1])
                elif tipo == "input":
                    _, prompt, resp = voce
                    resp.put(self._dialog_input(prompt))
                elif tipo == "pagina":
                    self.pagine.append(voce[1])
                    self._aggiungi_anteprima(voce[1])
                    self._rinumera()
                elif tipo == "stato":
                    self.stato.configure(text=voce[1])
                elif tipo == "prog_apri":
                    self._prog_apri(voce[1])
                elif tipo == "prog":
                    self._prog_aggiorna(voce[1], voce[2])
                elif tipo == "prog_chiudi":
                    self._prog_chiudi()
                elif tipo == "fine":
                    self.occupato = False
                    self._abilita(True)
                    self.stato.configure(text=voce[1])
                elif tipo == "avviso":
                    messagebox.showwarning("Attenzione", voce[1])
                elif tipo == "salvato":
                    self.svuota()
                    messagebox.showinfo("Salvato", voce[1])
                elif tipo == "telefoni":
                    self._telefoni_correnti = voce[1]
                    self._aggiorna_lista_telefoni()
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _dialog_input(self, prompt):
        p = prompt.strip()
        if "[s/N]" in p or "[s/n]" in p.lower():
            return "s" if messagebox.askyesno("Domanda", p) else "n"
        if not p or "INVIO" in p.upper():
            messagebox.showinfo("Continua", p or "Premi OK per continuare.")
            return ""
        iniziale = ""
        if "\n" in p:
            ultima = p.rsplit("\n", 1)[1].strip()
            if not (ultima.endswith(">") or ultima.endswith(":")):
                iniziale = ultima
                p = p.rsplit("\n", 1)[0]
        return self._finestra_input("Richiesta", p, iniziale)

    def _finestra_input(self, titolo, testo, iniziale=""):
        """Finestra di input moderna unica. Ritorna la stringa inserita se si
        preme OK (anche vuota), oppure ANNULLATO se si preme Annulla / si chiude
        la finestra: cosi' il chiamante distingue 'campo vuoto confermato' da
        'operazione annullata'."""
        win = ctk.CTkToplevel(self)
        win.title(titolo)
        win.geometry("480x210")
        win.resizable(False, False)
        win.grab_set()
        win.attributes("-topmost", True)
        risultato = {"val": ANNULLATO}          # default = annullato (anche 'X')
        ctk.CTkLabel(win, text=testo, wraplength=440,
                     justify="left").pack(padx=18, pady=(18, 8))
        campo = ctk.CTkEntry(win, width=440)
        campo.pack(padx=18, pady=6)
        if iniziale:
            campo.insert(0, iniziale)
        campo.focus_set()

        def ok(_evt=None):
            risultato["val"] = campo.get()
            win.destroy()

        f = ctk.CTkFrame(win, fg_color="transparent")
        f.pack(pady=12)
        ctk.CTkButton(f, text="OK", width=120, command=ok).pack(side="left",
                                                                padx=8)
        ctk.CTkButton(f, text="Annulla", width=120, fg_color="#555555",
                      hover_color="#404040",
                      command=win.destroy).pack(side="left", padx=8)
        campo.bind("<Return>", ok)
        campo.bind("<Escape>", lambda e: win.destroy())
        self.wait_window(win)
        return risultato["val"]

    def gui_input(self, prompt=""):
        """Sostituto di input() per il motore. Se l'utente annulla il dialogo,
        solleva OperazioneAnnullata per interrompere l'elaborazione: cosi' il
        file NON viene salvato."""
        resp = queue.Queue()
        self.req_queue.put(("input", prompt, resp))
        valore = resp.get()
        if valore is ANNULLATO:
            raise OperazioneAnnullata()
        return valore

    def _abilita(self, on):
        stato = "normal" if on else "disabled"
        self.b_scan.configure(state=stato)
        self.b_importa.configure(state=stato)
        self.b_elabora.configure(state=stato)
        self.b_svuota.configure(state=stato)

    # ---------------------------------------------------------- Scansione
    def scansiona(self):
        if self.occupato:
            return
        self.occupato = True
        self._abilita(False)
        self.stato.configure(text="Scansione in corso...")
        threading.Thread(target=self._worker_scan, daemon=True).start()

    def _worker_scan(self):
        import pythoncom
        pythoncom.CoInitialize()
        vecchio_input = builtins.input
        vecchio_stdout = sys.stdout
        builtins.input = self.gui_input
        sys.stdout = _StdProxy(self.req_queue)
        try:
            self._applica_config()
            engine.CONFIG["MULTIPAGE"] = False   # aggiunta pagine dai pulsanti
            log = engine.setup_logging(engine.CONFIG["LOG_DIR"])
            batch = tempfile.mkdtemp(prefix="batch_", dir=self.session_dir)
            immagini = engine.scansiona_wia(batch, log)
            for p in immagini:
                self.contatore += 1
                dest = os.path.join(self.session_dir,
                                    f"pagina_{self.contatore:03d}.jpg")
                shutil.move(p, dest)
                self.req_queue.put(("pagina", dest))
            self.req_queue.put(("fine",
                                f"Acquisite {len(immagini)} pagina/e. "
                                f"Aggiungine altre o elabora."))
        except OperazioneAnnullata:
            self.req_queue.put(("fine", "Scansione annullata."))
        except Exception as e:
            self.log(f"[ERRORE] {e}")
            self.req_queue.put(("fine", "Errore scansione - vedi log."))
        finally:
            builtins.input = vecchio_input
            sys.stdout = vecchio_stdout
            pythoncom.CoUninitialize()

    # -------------------------------------------------- Importazione file
    def importa(self):
        """Aggiunge alla sessione pagine prese da file gia' esistenti (PDF o
        foto), senza passare dallo scanner. Da qui in poi il flusso e' identico
        a quello della scansione."""
        if self.occupato:
            return
        percorsi = filedialog.askopenfilenames(
            title="Scegli i PDF o le foto da aggiungere",
            filetypes=[
                ("PDF e immagini",
                 "*.pdf *.jpg *.jpeg *.png *.bmp *.tif *.tiff *.gif *.webp"),
                ("PDF", "*.pdf"),
                ("Immagini",
                 "*.jpg *.jpeg *.png *.bmp *.tif *.tiff *.gif *.webp"),
                ("Tutti i file", "*.*"),
            ])
        if not percorsi:
            return
        self.occupato = True
        self._abilita(False)
        self.stato.configure(text="Importazione in corso...")
        threading.Thread(target=self._worker_importa,
                         args=(list(percorsi),), daemon=True).start()

    def _worker_importa(self, percorsi):
        vecchio_input = builtins.input
        vecchio_stdout = sys.stdout
        builtins.input = self.gui_input
        sys.stdout = _StdProxy(self.req_queue)
        try:
            self._applica_config()
            log = engine.setup_logging(engine.CONFIG["LOG_DIR"])
            batch = tempfile.mkdtemp(prefix="import_", dir=self.session_dir)
            immagini, errori = engine.importa_documenti(percorsi, batch, log)
            for p in immagini:
                self.contatore += 1
                dest = os.path.join(self.session_dir,
                                    f"pagina_{self.contatore:03d}.jpg")
                shutil.move(p, dest)
                self.req_queue.put(("pagina", dest))
            if errori:
                self.req_queue.put(
                    ("avviso", "File non importati:\n\n" + "\n".join(errori)))
            if not immagini:
                self.req_queue.put(("fine", "Nessuna pagina importata."))
            else:
                self.req_queue.put(
                    ("fine", f"Aggiunte {len(immagini)} pagina/e dai file. "
                             f"Aggiungine altre o elabora."))
        except OperazioneAnnullata:
            self.req_queue.put(("fine", "Importazione annullata."))
        except Exception as e:
            self.log(f"[ERRORE] {e}")
            self.req_queue.put(("fine", "Errore importazione - vedi log."))
        finally:
            builtins.input = vecchio_input
            sys.stdout = vecchio_stdout

    # ------------------------------------------------ Scansione da telefono
    # La finestra (QR/PIN, elenco telefoni, invio notifiche) e' in
    # finestra_telefono.py: qui restano solo i punti di ingresso richiamati
    # dai pulsanti e dal poll della coda.
    def scansiona_con_telefono(self):
        finestra_telefono.scansiona_con_telefono(self, BASE)

    def _aggiorna_lista_telefoni(self):
        finestra_telefono.aggiorna_lista(self)

    # -------------------------------------------------------- Elaborazione
    def elabora(self):
        if self.occupato:
            return
        if not self.pagine:
            messagebox.showinfo("Nessuna pagina",
                                "Scansiona almeno una pagina, oppure aggiungi "
                                "un PDF/una foto, prima di elaborare.")
            return
        self.occupato = True
        self._abilita(False)
        self.stato.configure(text="Elaborazione in corso (OCR + LLM)...")
        threading.Thread(target=self._worker_elabora, daemon=True).start()

    def _worker_elabora(self):
        import pythoncom
        pythoncom.CoInitialize()
        vecchio_input = builtins.input
        vecchio_stdout = sys.stdout
        builtins.input = self.gui_input
        sys.stdout = _StdProxy(self.req_queue)
        try:
            self._applica_config()
            log = engine.setup_logging(engine.CONFIG["LOG_DIR"])
            engine.controlla_dipendenze(log)
            os.makedirs(engine.CONFIG["OUTPUT_DIR"], exist_ok=True)

            immagini = list(self.pagine)
            pagine_testo = engine.ocr_testo(immagini, log)
            testo = "\n".join(pagine_testo).strip()

            pdf_temp = os.path.join(self.session_dir, "documento.pdf")
            engine.immagini_in_pdf(immagini, pdf_temp, log)
            engine.salva_ocr_debug(testo, log)

            pag_doc, _tipo = engine._pagina_documento_identita(pagine_testo, log)
            testo_naming = pag_doc if pag_doc else testo
            pagine_res = [pag_doc] if pag_doc else pagine_testo

            base = engine.determina_nome_file(testo_naming, log, testo_cf=testo)
            if not base:
                base = engine.nome_fallback()
            paese = engine.estrai_paese_residenza(pagine_res, log)
            servizio = engine.chiedi_servizio(log)
            data = engine.estrai_data(testo, log)
            nome = engine.componi_nome(base, paese, servizio, data, log)

            nuovo = self.gui_input(f"Nome file (modificabile):\n{nome}")
            if nuovo.strip():
                nome = engine.sanifica_nome(nuovo) or nome

            dest = engine.percorso_univoco(engine.CONFIG["OUTPUT_DIR"],
                                           nome, ".pdf")
            shutil.copy2(pdf_temp, dest)
            log.info("PDF salvato in: %s", dest)
            self.req_queue.put(("salvato", f"PDF salvato:\n{dest}"))
            self.req_queue.put(("fine", f"Salvato: {os.path.basename(dest)}"))
        except OperazioneAnnullata:
            self.log("Operazione annullata: il file NON e' stato salvato.")
            self.req_queue.put(("fine", "Annullato: nessun file salvato."))
        except Exception as e:
            self.log(f"[ERRORE] {e}")
            self.req_queue.put(("fine", "Errore elaborazione - vedi log."))
        finally:
            builtins.input = vecchio_input
            sys.stdout = vecchio_stdout
            pythoncom.CoUninitialize()

    # -------------------------------------------------------- Impostazioni
    def _apri_impostazioni(self):
        win = ctk.CTkToplevel(self)
        win.title("Impostazioni")
        win.geometry("560x520")
        win.grab_set()
        win.grid_columnconfigure(1, weight=1)

        def riga(r, testo, widget):
            ctk.CTkLabel(win, text=testo).grid(row=r, column=0, sticky="w",
                                               padx=(14, 8), pady=6)
            widget.grid(row=r, column=1, sticky="ew", padx=(0, 14), pady=6)

        riga(0, "Risoluzione (DPI)",
             ctk.CTkComboBox(win, variable=self.v_dpi,
                             values=["200", "300", "400", "600"]))
        riga(1, "Colore",
             ctk.CTkComboBox(win, variable=self.v_col,
                             values=["RGB", "Grayscale", "BlackWhite"]))
        riga(2, "Origine",
             ctk.CTkComboBox(win, variable=self.v_src,
                             values=["Auto", "Flatbed", "Feeder"]))

        f_out = ctk.CTkFrame(win, fg_color="transparent")
        f_out.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(f_out, textvariable=self.v_out).grid(row=0, column=0,
                                                          sticky="ew")
        ctk.CTkButton(f_out, text="...", width=36,
                      command=self._scegli_output).grid(row=0, column=1,
                                                        padx=(6, 0))
        riga(3, "Cartella PDF", f_out)

        riga(4, "Modello Ollama",
             ctk.CTkComboBox(win, variable=self.v_mod,
                             values=["qwen2.5:3b", "llama3.2:3b",
                                     "qwen2.5:1.5b"]))

        f_tes = ctk.CTkFrame(win, fg_color="transparent")
        f_tes.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(f_tes, textvariable=self.v_tes).grid(row=0, column=0,
                                                          sticky="ew")
        ctk.CTkButton(f_tes, text="...", width=36,
                      command=self._scegli_tesseract).grid(row=0, column=1,
                                                           padx=(6, 0))
        riga(5, "Tesseract", f_tes)

        riga(6, "Lingue OCR", ctk.CTkEntry(win, textvariable=self.v_lng))

        # Qualita' / compressione del PDF (per rientrare nei limiti di peso)
        f_qual = ctk.CTkFrame(win, fg_color="transparent")
        f_qual.grid_columnconfigure(0, weight=1)
        ctk.CTkComboBox(f_qual, variable=self.v_qual,
                        values=["Massima", "Alta", "Media", "Bassa", "Minima"]
                        ).grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(f_qual, text="file più leggero →",
                     text_color="gray").grid(row=0, column=1, padx=(8, 0))
        riga(7, "Qualità PDF", f_qual)

        # Scanner: menu a tendina con i device rilevati (niente ID da incollare)
        f_dev = ctk.CTkFrame(win, fg_color="transparent")
        f_dev.grid_columnconfigure(0, weight=1)
        self.combo_dev = ctk.CTkComboBox(f_dev, variable=self.v_dev_label,
                                         values=self._valori_scanner())
        self.combo_dev.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(f_dev, text="Rileva", width=70,
                      command=self._rileva_scanner).grid(row=0, column=1,
                                                         padx=(6, 0))
        riga(8, "Scanner", f_dev)

        f_chk = ctk.CTkFrame(win, fg_color="transparent")
        ctk.CTkCheckBox(f_chk, text="Auto-installa dipendenze",
                        variable=self.v_auto).pack(side="left", padx=(0, 16))
        ctk.CTkCheckBox(f_chk, text="Salva OCR di debug",
                        variable=self.v_dbg).pack(side="left")
        riga(9, "", f_chk)

        # Popola subito l'elenco degli scanner disponibili
        if not self._scanner_noti:
            self._rileva_scanner()

        f_btn = ctk.CTkFrame(win, fg_color="transparent")
        f_btn.grid(row=10, column=0, columnspan=2, pady=16)
        ctk.CTkButton(f_btn, text="Salva",
                      command=lambda: (self._salva_config(), win.destroy())
                      ).pack(side="left", padx=8)
        ctk.CTkButton(f_btn, text="Elenca scanner",
                      command=self.elenca_scanner).pack(side="left", padx=8)
        ctk.CTkButton(f_btn, text="Apri cartella PDF",
                      command=self._apri_output).pack(side="left", padx=8)
        ctk.CTkButton(f_btn, text="Cerca aggiornamenti",
                      command=self._aggiornamenti_manuale).pack(side="left",
                                                                padx=8)

    AUTO_LABEL = "(automatico)"

    def _valori_scanner(self):
        """Voci del menu a tendina: '(automatico)' + i device rilevati."""
        valori = [self.AUTO_LABEL]
        for did, nome in self._scanner_noti:
            valori.append(f"{nome}  |  {did}")
        # mostra comunque l'eventuale scanner salvato ma non ancora rilevato
        corrente = self.v_dev_label.get()
        if corrente and corrente not in valori:
            valori.append(corrente)
        return valori

    def _rileva_scanner(self):
        """Cerca gli scanner WIA e aggiorna il menu a tendina."""
        def lavoro():
            import pythoncom
            pythoncom.CoInitialize()
            try:
                self._scanner_noti = engine.elenca_device_wia()
                self.after(0, self._aggiorna_combo_scanner)
                self.log(f"Rilevati {len(self._scanner_noti)} scanner.")
            except Exception as e:
                self.log(f"[ERRORE] rilevamento scanner: {e}")
            finally:
                pythoncom.CoUninitialize()
        threading.Thread(target=lavoro, daemon=True).start()

    def _aggiorna_combo_scanner(self):
        try:
            self.combo_dev.configure(values=self._valori_scanner())
        except Exception:
            pass

    def _device_id_scelto(self):
        """Ricava il DEVICE_ID dalla voce selezionata nel menu a tendina."""
        voce = (self.v_dev_label.get() or "").strip()
        if not voce or voce == self.AUTO_LABEL:
            return ""
        if "|" in voce:
            return voce.split("|")[-1].strip()
        return voce

    def elenca_scanner(self):
        def lavoro():
            import pythoncom
            pythoncom.CoInitialize()
            try:
                devices = engine.elenca_device_wia()
                if not devices:
                    self.log("Nessuno scanner WIA trovato.")
                for did, nome in devices:
                    self.log(f"  {nome}  ->  {did}")
            except Exception as e:
                self.log(f"[ERRORE] {e}")
            finally:
                pythoncom.CoUninitialize()
        threading.Thread(target=lavoro, daemon=True).start()

    # ------------------------------------------------------------ Config
    def _carica_config(self):
        self.v_dpi = ctk.StringVar(value=str(engine.CONFIG["DPI"]))
        self.v_col = ctk.StringVar(value=engine.CONFIG["COLOR_MODE"])
        self.v_src = ctk.StringVar(value=engine.CONFIG["SOURCE"])
        self.v_out = ctk.StringVar(value=engine.CONFIG["OUTPUT_DIR"])
        self.v_mod = ctk.StringVar(value=engine.CONFIG["OLLAMA_MODEL"])
        self.v_tes = ctk.StringVar(value=engine.CONFIG["TESSERACT_PATH"])
        self.v_lng = ctk.StringVar(value=engine.CONFIG["OCR_LANG"])
        self.v_dev = ctk.StringVar(value=engine.CONFIG["DEVICE_ID"])
        # Etichetta mostrata nel menu a tendina degli scanner
        self.v_dev_label = ctk.StringVar(value="")
        self._scanner_noti = []
        self.v_qual = ctk.StringVar(value=engine.CONFIG.get("PDF_QUALITA",
                                                            "Massima"))
        self.v_auto = ctk.BooleanVar(value=engine.CONFIG["AUTO_INSTALL"])
        self.v_dbg = ctk.BooleanVar(value=engine.CONFIG.get("SAVE_OCR_DEBUG",
                                                            True))
        if os.path.isfile(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    dati = json.load(f)
                engine.CONFIG.update({k: v for k, v in dati.items()
                                      if k in PARAMETRI})
                self.v_dpi.set(str(engine.CONFIG["DPI"]))
                self.v_col.set(engine.CONFIG["COLOR_MODE"])
                self.v_src.set(engine.CONFIG["SOURCE"])
                self.v_out.set(engine.CONFIG["OUTPUT_DIR"])
                self.v_mod.set(engine.CONFIG["OLLAMA_MODEL"])
                self.v_tes.set(engine.CONFIG["TESSERACT_PATH"])
                self.v_lng.set(engine.CONFIG["OCR_LANG"])
                self.v_dev.set(engine.CONFIG["DEVICE_ID"])
                self.v_qual.set(engine.CONFIG.get("PDF_QUALITA", "Massima"))
                self.v_auto.set(engine.CONFIG["AUTO_INSTALL"])
                self.v_dbg.set(engine.CONFIG.get("SAVE_OCR_DEBUG", True))
            except Exception:
                pass
        # Etichetta iniziale del menu scanner: nome salvato se disponibile
        salvato = engine.CONFIG.get("DEVICE_ID", "")
        nome_salvato = engine.CONFIG.get("DEVICE_NAME", "")
        if salvato:
            self.v_dev_label.set(f"{nome_salvato}  |  {salvato}"
                                 if nome_salvato else salvato)
        else:
            self.v_dev_label.set(self.AUTO_LABEL)

    def _applica_config(self):
        try:
            engine.CONFIG["DPI"] = int(self.v_dpi.get())
        except ValueError:
            engine.CONFIG["DPI"] = 400
        engine.CONFIG["COLOR_MODE"] = self.v_col.get()
        engine.CONFIG["SOURCE"] = self.v_src.get()
        engine.CONFIG["OUTPUT_DIR"] = self.v_out.get()
        engine.CONFIG["OLLAMA_MODEL"] = self.v_mod.get()
        engine.CONFIG["TESSERACT_PATH"] = self.v_tes.get()
        engine.CONFIG["OCR_LANG"] = self.v_lng.get()
        engine.CONFIG["PDF_QUALITA"] = self.v_qual.get()
        # Scanner scelto dal menu a tendina (o '' = automatico)
        scelto = self._device_id_scelto()
        self.v_dev.set(scelto)
        engine.CONFIG["DEVICE_ID"] = scelto
        voce = (self.v_dev_label.get() or "")
        engine.CONFIG["DEVICE_NAME"] = (voce.split("|")[0].strip()
                                        if "|" in voce else "")
        engine.CONFIG["AUTO_INSTALL"] = self.v_auto.get()
        engine.CONFIG["SAVE_OCR_DEBUG"] = self.v_dbg.get()
        engine.CONFIG["CONFIRM_NAME"] = False

    def _salva_config(self):
        self._applica_config()
        dati = {k: engine.CONFIG[k] for k in PARAMETRI}
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(dati, f, indent=2, ensure_ascii=False)
            self.log("Impostazioni salvate.")
        except Exception as e:
            messagebox.showerror("Errore", f"Salvataggio fallito: {e}")

    def _scegli_output(self):
        d = filedialog.askdirectory(initialdir=self.v_out.get() or None)
        if d:
            self.v_out.set(d)

    def _scegli_tesseract(self):
        f = filedialog.askopenfilename(
            title="Seleziona tesseract.exe",
            filetypes=[("Eseguibile", "tesseract.exe"), ("Tutti", "*.*")])
        if f:
            self.v_tes.set(f)

    def _apri_output(self):
        cartella = self.v_out.get()
        if os.path.isdir(cartella):
            os.startfile(cartella)
        else:
            messagebox.showinfo("Info", "La cartella non esiste ancora.")

    # ---------------------------------------------------------- Certificato
    def _controlla_certificato(self):
        """Se il certificato con cui e' firmato l'eseguibile attuale non e'
        ancora attendibile su questo PC (prima installazione, o perche' nel
        frattempo ne e' uscito uno nuovo), chiede conferma e lo installa da
        solo: l'utente non deve piu' cercare ed eseguire lo script a mano.
        Gira in un thread separato, come il controllo aggiornamenti."""
        log = engine.setup_logging(engine.CONFIG["LOG_DIR"])
        try:
            certificato.controlla_e_installa(log, self._chiedi_conferma_certificato)
        except Exception as e:
            log.debug("Controllo certificato non riuscito: %s", e)

    def _chiedi_conferma_certificato(self, messaggio):
        """Ponte verso il thread dell'interfaccia: la domanda va mostrata
        (ed e' bloccante) sul thread principale, mentre questa funzione gira
        chiamata dal thread di controllo in background."""
        risposta = queue.Queue()
        self.after(0, lambda: risposta.put(
            messagebox.askyesno("Certificato di sicurezza", messaggio)))
        return risposta.get()

    # --------------------------------------------------------- Aggiornamenti
    def _controlla_aggiornamenti(self):
        """Chiede a GitHub se esiste una versione piu' recente. Gira in un
        thread separato: se la rete non risponde, l'app parte comunque."""
        try:
            info = aggiornamenti.controlla()
        except Exception:
            return
        if info:
            self.after(0, lambda: self._proponi_aggiornamento(info))

    def _aggiornamenti_manuale(self):
        """Controllo aggiornamenti richiesto dall'utente: qui, a differenza
        dell'avvio, si avvisa anche quando NON ci sono novita'."""
        def lavoro():
            info = None
            try:
                info = aggiornamenti.controlla()
            except Exception as e:
                self.log(f"[ERRORE] controllo aggiornamenti: {e}")
            if info:
                self.after(0, lambda: self._proponi_aggiornamento(info))
            else:
                self.after(0, lambda: messagebox.showinfo(
                    "Aggiornamenti",
                    f"Stai usando la versione più recente "
                    f"({aggiornamenti.VERSIONE})."))
        threading.Thread(target=lavoro, daemon=True).start()

    def _proponi_aggiornamento(self, info):
        """Popup che chiede se installare l'aggiornamento trovato."""
        note = info.get("note", "")
        if len(note) > 400:
            note = note[:400] + "..."
        testo = (f"È disponibile una nuova versione: {info['versione']}\n"
                 f"Versione in uso: {aggiornamenti.VERSIONE}\n\n"
                 + (f"Novità:\n{note}\n\n" if note else "")
                 + "Vuoi scaricarla e installarla ora?\n"
                   "L'applicazione verrà riavviata al termine.")
        if not messagebox.askyesno("Aggiornamento disponibile", testo):
            self.log("Aggiornamento rimandato.")
            return
        threading.Thread(target=self._esegui_aggiornamento, args=(info,),
                         daemon=True).start()

    def _esegui_aggiornamento(self, info):
        """Scarica il nuovo eseguibile e avvia la sostituzione, mostrando una
        barra di avanzamento grafica per download e installazione."""
        self.req_queue.put(("prog_apri", "Aggiornamento"))
        try:
            destinazione = os.path.join(tempfile.gettempdir(),
                                        "ScansioneBrother_nuovo.exe")

            def progresso(fatti, totale):
                if totale:
                    fraz = fatti / totale
                    testo = (f"Scaricamento... {fraz*100:.0f}%  "
                             f"({fatti/1048576:.1f} di {totale/1048576:.1f} MB)")
                else:
                    fraz = None
                    testo = f"Scaricamento... {fatti/1048576:.1f} MB"
                self.req_queue.put(("prog", fraz, testo))

            aggiornamenti.scarica(info["url"], destinazione, progresso)

            # Fase installazione: avanzamento indeterminato (dura poco)
            self.req_queue.put(("prog", 1.0,
                                "Installazione e riavvio in corso..."))
            aggiornamenti.installa(destinazione)
            self.after(400, self._chiudi)        # lo script riavvia l'app
        except Exception as e:
            self.log(f"[ERRORE] Aggiornamento non riuscito: {e}")
            self.req_queue.put(("prog_chiudi",))
            self.req_queue.put(("stato", "Aggiornamento non riuscito."))
            self.after(0, lambda: messagebox.showerror(
                "Aggiornamento",
                f"Aggiornamento non riuscito:\n{e}"))

    # ------------------------------------------------ Finestra avanzamento
    def _prog_apri(self, titolo):
        if getattr(self, "_prog_win", None) is not None:
            return
        win = ctk.CTkToplevel(self)
        win.title(titolo)
        win.geometry("440x150")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        try:
            win.grab_set()
        except Exception:
            pass
        win.protocol("WM_DELETE_WINDOW", lambda: None)   # non chiudibile a mano
        self._prog_lbl = ctk.CTkLabel(win, text="Preparazione...",
                                      font=ctk.CTkFont(size=13))
        self._prog_lbl.pack(padx=20, pady=(26, 10))
        self._prog_bar = ctk.CTkProgressBar(win, width=380)
        self._prog_bar.pack(padx=20, pady=(0, 20))
        self._prog_bar.set(0)
        self._prog_win = win

    def _prog_aggiorna(self, frazione, testo):
        if getattr(self, "_prog_win", None) is None:
            return
        try:
            self._prog_lbl.configure(text=testo)
            if frazione is None:
                self._prog_bar.configure(mode="indeterminate")
                self._prog_bar.start()
            else:
                self._prog_bar.configure(mode="determinate")
                self._prog_bar.set(max(0.0, min(1.0, frazione)))
        except Exception:
            pass

    def _prog_chiudi(self):
        win = getattr(self, "_prog_win", None)
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass
            self._prog_win = None

    def _imposta_icona(self):
        """Applica alla finestra la stessa icona .ico usata per l'eseguibile.
        Cerca app.ico accanto al programma o nel pacchetto customtkinter."""
        candidati = [os.path.join(BASE, "app.ico"),
                     os.path.join(BASE, "src", "app.ico")]
        if getattr(sys, "_MEIPASS", None):   # bundle PyInstaller
            candidati.insert(0, os.path.join(sys._MEIPASS, "app.ico"))
        try:
            import customtkinter as _c
            candidati.append(os.path.join(os.path.dirname(_c.__file__),
                                          "assets", "icons",
                                          "CustomTkinter_icon_Windows.ico"))
        except Exception:
            pass
        for ico in candidati:
            if os.path.isfile(ico):
                try:
                    self.iconbitmap(ico)
                    return
                except Exception:
                    continue

    def _chiudi(self):
        try:
            if self._tel_server is not None:
                self._tel_server.ferma()
            shutil.rmtree(self.session_dir, ignore_errors=True)
        finally:
            self.destroy()


class _StdProxy:
    """Reindirizza stdout (log e barre di avanzamento) verso la coda GUI."""

    def __init__(self, coda):
        self.coda = coda

    def write(self, s):
        if s:
            self.coda.put(("log", s))

    def flush(self):
        pass


if __name__ == "__main__":
    _imposta_appid()
    App().mainloop()
