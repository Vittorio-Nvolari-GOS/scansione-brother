# -*- coding: utf-8 -*-
"""
============================================================================
 telefono_scan.py - Scansione da telefono in rete locale
----------------------------------------------------------------------------
 Il programma espone un piccolo server web nella rete locale: il telefono
 apre un indirizzo (o inquadra un QR mostrato dal programma) nel browser,
 scatta le foto delle pagine con la fotocamera e le invia al programma, che
 le aggiunge alla sessione come se fossero state scansionate.

 - Nessuna app da installare: la pagina funziona nel browser e puo' anche
   essere "aggiunta alla schermata Home" (PWA) per comportarsi come un'app,
   sia su Android che su iPhone.
 - Un PIN a 4 cifre, generato a ogni avvio del server e incluso nel link/QR,
   evita che altri dispositivi sulla stessa rete inviino foto per errore.
 - Il programma tiene l'elenco dei telefoni collegati: la pagina si
   ri-annuncia ogni pochi secondi finche' resta aperta, chi smette di
   rispondere sparisce dall'elenco dopo poco.
============================================================================
"""

import json
import os
import random
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs

import notifiche_push
from pagina_telefono import MANIFEST, SERVICE_WORKER, PAGINA_HTML, icona_png

PORTA_INIZIALE = 8765
TENTATIVI_PORTA = 20
TIMEOUT_TELEFONO = 25          # secondi senza segnali di vita = considerato offline
DIMENSIONE_MAX_FOTO = 40 * 1024 * 1024

def _ip_locale():
    """IP del PC nella rete locale (quello raggiungibile dal telefono)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()

class _GestoreRichieste(BaseHTTPRequestHandler):
    server_version = "ScansioneBrotherTelefono/1"

    def log_message(self, fmt, *args):
        pass  # niente rumore in console: gli eventi utili vanno nel log dell'app

    def _app(self):
        return self.server.app

    def _qs(self):
        return parse_qs(urlsplit(self.path).query)

    def _pin_ok(self, qs):
        return bool(qs.get("pin", [""])[0]) and qs["pin"][0] == self._app().pin

    def _invia(self, codice, corpo, tipo="text/plain; charset=utf-8"):
        dati = corpo if isinstance(corpo, bytes) else corpo.encode("utf-8")
        self.send_response(codice)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dati)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(dati)
        except Exception:
            pass

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/":
            self._invia(200, PAGINA_HTML, "text/html; charset=utf-8")
        elif path == "/manifest.webmanifest":
            self._invia(200, json.dumps(MANIFEST), "application/manifest+json")
        elif path == "/sw.js":
            self._invia(200, SERVICE_WORKER, "application/javascript")
        elif path in ("/icona-192.png", "/icona-512.png"):
            dim = 512 if "512" in path else 192
            self._invia(200, self._app().icona(dim), "image/png")
        elif path == "/chiave-pubblica":
            chiave = self._app().chiave_pubblica
            if chiave:
                self._invia(200, chiave, "text/plain; charset=utf-8")
            else:
                self._invia(404, "Notifiche non disponibili")
        elif path == "/attendi-notifica":
            # Long-poll usato dall'app Android: resta in attesa (fino a
            # ~25s) di una notifica inviata dal PC, senza bisogno di
            # Internet ne' di un servizio push esterno.
            qs = self._qs()
            if not self._pin_ok(qs):
                self._invia(403, '{"errore":"pin"}', "application/json")
                return
            tid = qs.get("id", [""])[0]
            arrivata = self._app().attendi_notifica(tid)
            self._invia(200, json.dumps({"notifica": arrivata}),
                       "application/json")
        else:
            self._invia(404, "Non trovato")

    def do_POST(self):
        path = urlsplit(self.path).path
        qs = self._qs()
        app = self._app()
        tid = qs.get("id", [""])[0]

        if path == "/registra":
            if not self._pin_ok(qs):
                self._invia(403, '{"errore":"pin"}', "application/json")
                return
            nome = qs.get("nome", ["Telefono"])[0] or "Telefono"
            app.registra_telefono(tid, nome)
            self._invia(200, '{"ok":true}', "application/json")

        elif path == "/ping":
            if not self._pin_ok(qs):
                self._invia(403, '{"errore":"pin"}', "application/json")
                return
            app.rinnova_telefono(tid)
            self._invia(200, '{"ok":true}', "application/json")

        elif path == "/carica":
            if not self._pin_ok(qs):
                self._invia(403, '{"errore":"pin"}', "application/json")
                return
            try:
                lunghezza = int(self.headers.get("Content-Length", 0))
            except ValueError:
                lunghezza = 0
            if lunghezza <= 0 or lunghezza > DIMENSIONE_MAX_FOTO:
                self._invia(400, '{"errore":"dimensione"}', "application/json")
                return
            dati = self.rfile.read(lunghezza)
            try:
                app.ricevi_foto(tid, dati)
                self._invia(200, '{"ok":true}', "application/json")
            except Exception as e:
                self._invia(500, json.dumps({"errore": str(e)}), "application/json")

        elif path == "/sottoscrizione":
            if not self._pin_ok(qs):
                self._invia(403, '{"errore":"pin"}', "application/json")
                return
            try:
                lunghezza = int(self.headers.get("Content-Length", 0))
                sub = json.loads(self.rfile.read(lunghezza) or b"{}")
            except (ValueError, json.JSONDecodeError):
                self._invia(400, '{"errore":"dati"}', "application/json")
                return
            app.imposta_sottoscrizione(tid, sub)
            self._invia(200, '{"ok":true}', "application/json")

        else:
            self._invia(404, "Non trovato")

class TelefonoScanServer:
    """Server HTTP in rete locale che riceve le foto scattate dal telefono e le
    inserisce nella sessione di scansione tramite le callback fornite.

    on_foto(percorso_jpg)     - chiamata per ogni pagina ricevuta e normalizzata
    on_telefoni(lista_dict)   - chiamata quando cambia l'elenco dei telefoni
                                 collegati; ogni voce e'
                                 {"id":..., "nome":..., "da": sec,
                                  "notifiche": bool}
    """

    def __init__(self, cartella_sessione, log, engine, on_foto, on_telefoni,
                cartella_chiavi=None):
        self.cartella = cartella_sessione
        self.log = log
        self.engine = engine
        self.on_foto = on_foto
        self.on_telefoni = on_telefoni
        self.pin = f"{random.randint(0, 9999):04d}"
        self._telefoni = {}
        self._attese = {}          # tid -> [threading.Event, ...] (long-poll app Android)
        self._lock = threading.Lock()
        self._contatore = 0
        self._icone = {}
        self._httpd = None
        self._porta = None
        # Chiavi VAPID per le notifiche push: salvate in una cartella stabile
        # (non quella di sessione, che e' temporanea) cosi' le sottoscrizioni
        # dei telefoni restano valide da un avvio all'altro del programma.
        self.chiave_privata, self.chiave_pubblica = notifiche_push.prepara_chiavi(
            cartella_chiavi or cartella_sessione)

    # --------------------------------------------------------------- avvio
    def avvia(self):
        """Avvia il server su una porta libera e ritorna l'URL da mostrare
        (QR o testo) al telefono."""
        for tentativo in range(TENTATIVI_PORTA):
            porta = PORTA_INIZIALE + tentativo
            try:
                self._httpd = ThreadingHTTPServer(("0.0.0.0", porta),
                                                  _GestoreRichieste)
                self._porta = porta
                break
            except OSError:
                continue
        else:
            raise RuntimeError("Nessuna porta disponibile per il server "
                              "di scansione da telefono.")
        self._httpd.app = self
        self._httpd.daemon_threads = True
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        url = self.url()
        self.log.info("Server scansione da telefono avviato: %s", url)
        return url

    def ferma(self):
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass
            self._httpd = None

    def url(self):
        return f"http://{_ip_locale()}:{self._porta}/?pin={self.pin}"

    def icona(self, dimensione):
        if dimensione not in self._icone:
            self._icone[dimensione] = icona_png(dimensione)
        return self._icone[dimensione]

    # --------------------------------------------------------- telefoni
    def registra_telefono(self, tid, nome):
        if not tid:
            return
        with self._lock:
            voce = self._telefoni.setdefault(tid, {"sub": None})
            voce["nome"] = nome
            voce["ultimo"] = time.time()
        self.log.info("Telefono collegato: %s (%s)", nome, tid[:8])
        self._notifica_telefoni()

    def rinnova_telefono(self, tid):
        with self._lock:
            if tid in self._telefoni:
                self._telefoni[tid]["ultimo"] = time.time()

    def nome_telefono(self, tid):
        with self._lock:
            return self._telefoni.get(tid, {}).get("nome", "Telefono")

    def imposta_sottoscrizione(self, tid, sub):
        """Registra (o aggiorna) la sottoscrizione push del telefono, usata
        per inviargli una notifica quando l'operatore lo seleziona dal PC."""
        with self._lock:
            if tid in self._telefoni:
                self._telefoni[tid]["sub"] = sub
        self.log.info("Notifiche push attivate per il telefono %s", tid[:8])
        self._notifica_telefoni()

    def elenca_telefoni(self):
        """Rimuove i telefoni che non danno segni di vita da un po' e ritorna
        l'elenco di quelli attivi."""
        adesso = time.time()
        with self._lock:
            for tid in list(self._telefoni):
                if adesso - self._telefoni[tid]["ultimo"] > TIMEOUT_TELEFONO:
                    del self._telefoni[tid]
            return [{"id": tid, "nome": v["nome"], "da": int(adesso - v["ultimo"]),
                     "notifiche": bool(v.get("sub")) or bool(self._attese.get(tid))}
                    for tid, v in self._telefoni.items()]

    def _notifica_telefoni(self):
        try:
            self.on_telefoni(self.elenca_telefoni())
        except Exception:
            pass

    # ----------------------------------------------------------- notifiche
    def attendi_notifica(self, tid, timeout=25):
        """Blocca (fino a 'timeout' secondi) in attesa che notifica_telefono()
        venga chiamata per questo telefono. Usato dall'app Android con una
        connessione long-poll: niente Internet ne' account esterni, solo
        rete locale."""
        evento = threading.Event()
        with self._lock:
            era_vuota = not self._attese.get(tid)
            self._attese.setdefault(tid, []).append(evento)
        self.rinnova_telefono(tid)
        if era_vuota:
            # Prima connessione long-poll di questo telefono: la finestra sul
            # PC deve saperlo subito per abilitare il pulsante "Notifica",
            # non solo alla prossima registrazione.
            self.log.info("Telefono %s in ascolto per le notifiche (app)", tid[:8])
            self._notifica_telefoni()
        arrivata = evento.wait(timeout)
        with self._lock:
            lista = self._attese.get(tid)
            if lista and evento in lista:
                lista.remove(evento)
        if arrivata:
            self.log.info("Notifica consegnata al telefono %s", tid[:8])
        return arrivata

    def _sveglia_attese(self, tid):
        """Sblocca le eventuali connessioni long-poll in corso per questo
        telefono. Ritorna True se ce n'era almeno una."""
        with self._lock:
            eventi = list(self._attese.get(tid, []))
        for e in eventi:
            e.set()
        return bool(eventi)

    def notifica_telefono(self, tid, titolo="Scansione documenti",
                          corpo="Il programma ti chiede di scattare una pagina."):
        """Avvisa il telefono scelto dall'operatore: sblocca subito l'app
        Android se e' collegata (long-poll in rete locale) e, se il
        telefono ha attivato le notifiche push del browser, invia anche
        quelle. Solleva RuntimeError con un messaggio da mostrare se non
        c'e' nessun canale attivo."""
        con_attesa = self._sveglia_attese(tid)
        with self._lock:
            sub = self._telefoni.get(tid, {}).get("sub")
        if sub and not self.chiave_privata:
            sub = None  # pacchetti per le notifiche push non installati
        self.log.info("Notifica per %s: canale app=%s, canale push=%s",
                      tid[:8], con_attesa, bool(sub))
        if sub:
            try:
                notifiche_push.invia(sub, titolo, corpo, self.chiave_privata)
            except Exception as e:
                # Sottoscrizione scaduta o rifiutata: la rimuoviamo cosi'
                # l'operatore vede che va riattivata.
                with self._lock:
                    if tid in self._telefoni:
                        self._telefoni[tid]["sub"] = None
                self._notifica_telefoni()
                if not con_attesa:
                    raise RuntimeError(f"Invio notifica non riuscito: {e}") from e
        elif not con_attesa:
            raise RuntimeError(
                "Questo telefono non ha nessun canale di notifica attivo: "
                "apri l'app Android, oppure attiva le notifiche nella "
                "pagina web.")

    # -------------------------------------------------------------- foto
    def ricevi_foto(self, tid, dati_jpeg):
        """Salva la foto ricevuta, la normalizza (orientamento EXIF, RGB) con
        lo stesso motore usato per 'Aggiungi PDF/foto', e la notifica alla GUI."""
        self._contatore += 1
        nome_tel = self.nome_telefono(tid)
        os.makedirs(self.cartella, exist_ok=True)
        grezzo = os.path.join(self.cartella, f"_grezzo_{self._contatore:03d}.jpg")
        with open(grezzo, "wb") as f:
            f.write(dati_jpeg)
        try:
            pagine = self.engine.immagine_importata(
                grezzo, self.cartella, self.log,
                prefisso=f"telefono_{self._contatore:03d}")
        finally:
            try:
                os.remove(grezzo)
            except OSError:
                pass
        self.rinnova_telefono(tid)
        for p in pagine:
            self.on_foto(p)
        self.log.info("Pagina ricevuta da %s (%s): %s", nome_tel, tid[:8],
                      os.path.basename(pagine[0]) if pagine else "?")
