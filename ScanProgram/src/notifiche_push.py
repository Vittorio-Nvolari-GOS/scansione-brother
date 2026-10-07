# -*- coding: utf-8 -*-
"""
============================================================================
 notifiche_push.py - Notifiche push verso il telefono (Web Push / VAPID)
----------------------------------------------------------------------------
 Quando il telefono abilita le notifiche, il browser crea una sottoscrizione
 al servizio push del produttore (Google per Chrome/Android, Apple per
 Safari/iPhone). Il programma firma i messaggi con una coppia di chiavi
 VAPID generata la prima volta e salvata accanto alla configurazione: non
 serve nessun account esterno ne' server di terze parti da configurare.

 NB: l'invio passa dal servizio push del browser, quindi serve Internet
 (non basta la sola rete locale) sia sul PC sia sul telefono. Su iPhone le
 notifiche funzionano solo se la pagina e' stata "Aggiunta alla schermata
 Home" (richiede iOS 16.4 o successivo): e' un limite di Safari, non
 dell'app.
============================================================================
"""

import base64
import json
import os

NOME_CHIAVE = "telefono_vapid_private.pem"
CLAIMS_SUB = "mailto:scansione@localhost"


def disponibile():
    """True se i pacchetti necessari (py_vapid, pywebpush) sono installati."""
    try:
        import py_vapid  # noqa: F401
        import pywebpush  # noqa: F401
        return True
    except ImportError:
        return False


def prepara_chiavi(cartella):
    """Genera (la prima volta) o carica la coppia di chiavi VAPID salvata
    accanto alla configurazione. Ritorna (percorso_chiave_privata,
    chiave_pubblica_base64url) oppure (None, None) se i pacchetti per le
    notifiche push non sono installati."""
    if not disponibile():
        return None, None
    from py_vapid import Vapid
    from cryptography.hazmat.primitives.serialization import (Encoding,
                                                                PublicFormat)
    percorso = os.path.join(cartella, NOME_CHIAVE)
    if os.path.isfile(percorso):
        v = Vapid.from_file(percorso)
    else:
        v = Vapid()
        v.generate_keys()
        v.save_key(percorso)
    grezza = v.public_key.public_bytes(Encoding.X962,
                                       PublicFormat.UncompressedPoint)
    pubblica = base64.urlsafe_b64encode(grezza).rstrip(b"=").decode("ascii")
    return percorso, pubblica


def invia(subscription_info, titolo, corpo, chiave_privata_pem):
    """Invia una notifica push al telefono. Solleva eccezione se fallisce
    (es. sottoscrizione scaduta o rifiutata: chi chiama la rimuove)."""
    from pywebpush import webpush
    webpush(
        subscription_info=subscription_info,
        data=json.dumps({"titolo": titolo, "corpo": corpo}),
        vapid_private_key=chiave_privata_pem,
        vapid_claims={"sub": CLAIMS_SUB},
    )
