# -*- coding: utf-8 -*-
"""
============================================================================
 finestra_telefono.py - Finestra "Scansiona con il telefono": avvia il
 server, mostra QR/link/PIN, l'elenco dei telefoni collegati e permette di
 inviare la notifica push a quello scelto. Richiamato da scan_gui.py.
============================================================================
"""

import tempfile

import customtkinter as ctk
from tkinter import messagebox

import telefono_scan


def scansiona_con_telefono(app, base_dir):
    """Avvia (se non gia' attivo) il server per il telefono e apre la
    finestra di gestione. 'app' e' l'istanza di App in scan_gui.py."""
    if app._tel_server is None:
        import scan_brother_ai as engine
        log = engine.setup_logging(engine.CONFIG["LOG_DIR"])
        cartella = tempfile.mkdtemp(prefix="telefono_", dir=app.session_dir)
        server = telefono_scan.TelefonoScanServer(
            cartella, log, engine,
            on_foto=lambda p: app.req_queue.put(("pagina", p)),
            on_telefoni=lambda l: app.req_queue.put(("telefoni", l)),
            cartella_chiavi=base_dir)  # le chiavi delle notifiche restano
                                      # valide da un avvio all'altro
        try:
            url = server.avvia()
        except Exception as e:
            messagebox.showerror(
                "Errore", f"Impossibile avviare il server per il "
                f"telefono:\n{e}")
            return
        app._tel_server = server
        app._tel_url = url
    _apri_finestra(app)


def _apri_finestra(app):
    if app._tel_win is not None and app._tel_win.winfo_exists():
        app._tel_win.lift()
        return
    win = ctk.CTkToplevel(app)
    win.title("Scansiona con il telefono")
    win.geometry("380x680")
    win.resizable(False, False)
    win.attributes("-topmost", True)
    app._tel_win = win

    ctk.CTkLabel(
        win, text="Apri il link (o inquadra il QR) con il telefono,\n"
                  "nella stessa rete Wi-Fi del PC.",
        justify="center").pack(padx=16, pady=(16, 10))

    try:
        import qrcode
        img = qrcode.make(app._tel_url).resize((230, 230))
        cimg = ctk.CTkImage(light_image=img, dark_image=img, size=(230, 230))
        app._tel_qr_ref = cimg
        ctk.CTkLabel(win, image=cimg, text="").pack(pady=(0, 10))
    except Exception:
        ctk.CTkLabel(
            win, text="(installa il pacchetto 'qrcode' per vedere il QR:\n"
                      "apri il link a mano nel frattempo)",
            text_color="gray").pack(pady=(0, 10))

    f_link = ctk.CTkFrame(win, fg_color="transparent")
    f_link.pack(fill="x", padx=16)
    campo = ctk.CTkEntry(f_link)
    campo.insert(0, app._tel_url)
    campo.configure(state="readonly")
    campo.pack(side="left", fill="x", expand=True)
    ctk.CTkButton(f_link, text="Copia", width=64,
                  command=lambda: (app.clipboard_clear(),
                                   app.clipboard_append(app._tel_url))
                  ).pack(side="left", padx=(6, 0))

    ctk.CTkLabel(
        win, text=f"PIN: {app._tel_server.pin}",
        font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(10, 4))
    ctk.CTkLabel(
        win, text="Il PIN e' gia' incluso nel QR: serve solo se il\n"
                  "link va inserito a mano.",
        text_color="gray", justify="center").pack(pady=(0, 10))

    ctk.CTkLabel(win, text="Telefoni collegati",
                 font=ctk.CTkFont(size=13, weight="bold")).pack(pady=(6, 2))
    if not app._tel_server.chiave_privata:
        ctk.CTkLabel(
            win, text="(notifiche non disponibili: installa i pacchetti\n"
                      "'py_vapid' e 'pywebpush')",
            text_color="gray", justify="center").pack(pady=(0, 4))
    app._tel_lista = ctk.CTkScrollableFrame(win, height=220)
    app._tel_lista.pack(fill="both", expand=True, padx=16, pady=(0, 10))
    aggiorna_lista(app)
    _pianifica_aggiornamento(app, win)

    ctk.CTkButton(win, text="Ferma server", fg_color="#8e2424",
                  hover_color="#6f1c1c",
                  command=lambda: ferma_server(app)).pack(pady=(4, 14))

    win.protocol("WM_DELETE_WINDOW", win.destroy)  # il server resta attivo


def _pianifica_aggiornamento(app, win):
    """Ricontrolla l'elenco ogni paio di secondi finche' la finestra resta
    aperta: non dipende dagli eventi (registrazione, ping...) del server,
    cosi' lo stato mostrato non puo' restare disallineato."""
    if not win.winfo_exists() or app._tel_server is None:
        return
    app._telefoni_correnti = app._tel_server.elenca_telefoni()
    aggiorna_lista(app)
    win.after(2000, lambda: _pianifica_aggiornamento(app, win))


def aggiorna_lista(app):
    """Ridisegna l'elenco dei telefoni collegati nella finestra, se aperta."""
    lista = getattr(app, "_tel_lista", None)
    if lista is None or not lista.winfo_exists():
        return
    for w in lista.winfo_children():
        w.destroy()
    if not app._telefoni_correnti:
        ctk.CTkLabel(lista, text="(nessuno ancora)",
                    text_color="gray").pack(pady=8)
        return
    for t in app._telefoni_correnti:
        riga = ctk.CTkFrame(lista, fg_color="transparent")
        riga.pack(fill="x", pady=3)
        testo = f"✅ {t['nome']}  ({t['da']}s fa)"
        ctk.CTkLabel(riga, text=testo, anchor="w").pack(side="left",
                                                        fill="x", expand=True)
        btn = ctk.CTkButton(
            riga, text="📸 Notifica", width=100, height=28,
            fg_color="#6a1f8b", hover_color="#511668",
            command=lambda tid=t["id"], nome=t["nome"]:
                _invia_notifica(app, tid, nome))
        if not t.get("notifiche"):
            btn.configure(state="disabled", fg_color="gray30")
        btn.pack(side="right")


def _invia_notifica(app, tid, nome):
    try:
        app._tel_server.notifica_telefono(tid)
        app.log(f"Notifica inviata a {nome}.")
    except Exception as e:
        messagebox.showerror("Notifica", str(e))


def ferma_server(app):
    if app._tel_server is not None:
        app._tel_server.ferma()
        app._tel_server = None
    app._telefoni_correnti = []
    if app._tel_win is not None:
        try:
            app._tel_win.destroy()
        except Exception:
            pass
        app._tel_win = None
