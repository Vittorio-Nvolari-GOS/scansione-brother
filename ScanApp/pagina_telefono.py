# -*- coding: utf-8 -*-
"""
============================================================================
 pagina_telefono.py - Pagina web, manifest PWA e service worker per la
 scansione da telefono (serviti da telefono_scan.py)
============================================================================
"""

import io


def icona_png(dimensione):
    """Genera al volo una piccola icona per il manifest PWA (nessun file da
    distribuire): un quadrato blu con una fotocamera stilizzata."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (dimensione, dimensione), "#1f5f8b")
    d = ImageDraw.Draw(img)
    m = dimensione // 5
    d.rounded_rectangle([m, m * 1.6, dimensione - m, dimensione - m],
                        radius=m // 2, fill="#ffffff")
    r = dimensione // 4
    c = dimensione // 2
    y = dimensione // 2
    d.ellipse([c - r, y - r, c + r, y + r], fill="#1f5f8b")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


MANIFEST = {
    "name": "Scansione Documenti",
    "short_name": "Scansione",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#111417",
    "theme_color": "#1f5f8b",
    "icons": [
        {"src": "/icona-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/icona-512.png", "sizes": "512x512", "type": "image/png"},
    ],
}

SERVICE_WORKER = """
self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => self.clients.claim());
self.addEventListener('fetch', e => {}); // niente cache: la pagina serve sempre dal programma

// Notifica push: il programma la invia quando l'operatore sceglie questo
// telefono dall'elenco dei dispositivi collegati.
self.addEventListener('push', event => {
  let dati = {};
  try { dati = event.data.json(); } catch (e) {}
  const titolo = dati.titolo || 'Scansione documenti';
  event.waitUntil(self.registration.showNotification(titolo, {
    body: dati.corpo || 'Il programma ti chiede di scattare una pagina.',
    icon: '/icona-192.png',
    badge: '/icona-192.png',
    tag: 'scansione-richiesta',
    requireInteraction: true,
    vibrate: [200, 100, 200],
    data: {url: '/'},
  }));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil(clients.matchAll({type: 'window', includeUncontrolled: true})
    .then(elenco => {
      for (const c of elenco) { if ('focus' in c) return c.focus(); }
      if (clients.openWindow) return clients.openWindow(event.notification.data.url || '/');
    }));
});
"""

PAGINA_HTML = """<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Scansione documenti</title>
<link rel="manifest" href="/manifest.webmanifest">
<link rel="apple-touch-icon" href="/icona-192.png">
<meta name="theme-color" content="#1f5f8b">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
         background:#111417; color:#eee;
         padding: 16px calc(16px + env(safe-area-inset-right))
                  calc(24px + env(safe-area-inset-bottom))
                  calc(16px + env(safe-area-inset-left)); }
  h1 { font-size: 1.2rem; margin: 4px 0 14px; }
  .stato { padding:10px 12px; border-radius:10px; margin-bottom:14px; font-size:.92rem; }
  .stato.ok { background:#173a2e; color:#8fe3b0; }
  .stato.err { background:#3a1717; color:#f0a3a3; }
  .pin-box { display:flex; gap:8px; margin-bottom:14px; }
  .pin-box input { flex:1; font-size:1.1rem; padding:10px; border-radius:8px;
                    border:1px solid #333; background:#1a1d21; color:#eee; }
  .pin-box button { padding:10px 14px; border-radius:8px; border:none;
                     background:#1f5f8b; color:#fff; font-weight:600; }
  #scatta { display:block; width:100%; padding:22px; font-size:1.15rem; font-weight:700;
            border:none; border-radius:14px; background:#2e7d32; color:#fff; margin-bottom:16px; }
  #scatta:disabled { background:#2e4a30; color:#9c9; }
  #scatta:active:not(:disabled) { background:#1b5e20; }
  #pagine { display:grid; grid-template-columns: repeat(auto-fill, minmax(84px,1fr)); gap:8px; }
  #pagine div { position:relative; }
  #pagine img { width:100%; border-radius:8px; display:block; aspect-ratio:3/4; object-fit:cover; }
  #pagine span { position:absolute; bottom:2px; right:4px; background:#000a;
                 font-size:.65rem; padding:1px 5px; border-radius:6px; }
  .nome-box { margin-bottom:14px; }
  .nome-box input { width:100%; padding:9px; border-radius:8px; border:1px solid #333;
                     background:#1a1d21; color:#eee; }
  label { font-size:.8rem; color:#9aa; }
  #notifiche { display:block; width:100%; padding:12px; margin-bottom:16px; font-size:.9rem;
               border:1px solid #333; border-radius:10px; background:#1a1d21; color:#eee; }
  #notifiche.attive { border-color:#2e7d32; color:#8fe3b0; }
</style>
</head>
<body>
<h1>&#128241; Scansione documenti</h1>
<div id="stato" class="stato">Connessione...</div>

<div class="nome-box">
  <label>Nome di questo telefono</label>
  <input id="nome" placeholder="es. Telefono sportello">
</div>

<div class="pin-box" id="box-pin" hidden>
  <input id="pin" placeholder="PIN mostrato sul programma" inputmode="numeric" maxlength="6">
  <button onclick="registra()">Collega</button>
</div>

<button id="scatta" onclick="document.getElementById('file').click()" disabled>
  &#128247; Scatta pagina
</button>
<input type="file" id="file" accept="image/*" capture="environment" style="display:none">

<button id="notifiche" onclick="abilitaNotifiche()">
  &#128276; Attiva notifiche (per essere avvisato dal programma)
</button>

<div id="pagine"></div>

<script>
const qs = new URLSearchParams(location.search);
let pin = qs.get('pin') || localStorage.getItem('pin') || '';
let id = localStorage.getItem('tel_id');
if (!id) {
  id = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random());
  localStorage.setItem('tel_id', id);
}
document.getElementById('nome').value = localStorage.getItem('tel_nome') || '';
let contatore = 0;

function setStato(testo, ok) {
  const el = document.getElementById('stato');
  el.textContent = testo;
  el.className = 'stato ' + (ok ? 'ok' : 'err');
}

function scollegato(messaggio) {
  document.getElementById('scatta').disabled = true;
  document.getElementById('box-pin').hidden = false;
  setStato(messaggio, false);
}

function registra() {
  pin = (document.getElementById('pin').value || pin || '').trim();
  const nome = (document.getElementById('nome').value || 'Telefono').trim();
  if (!pin) { setStato('Inserisci il PIN mostrato sul programma.', false); return; }
  localStorage.setItem('pin', pin);
  localStorage.setItem('tel_nome', nome);
  fetch(`/registra?id=${id}&nome=${encodeURIComponent(nome)}&pin=${pin}`, {method: 'POST'})
    .then(r => { if (!r.ok) throw 0; })
    .then(() => {
      setStato('Collegato al programma. Pronto a scansionare.', true);
      document.getElementById('box-pin').hidden = true;
      document.getElementById('scatta').disabled = false;
    })
    .catch(() => setStato('PIN errato o programma non raggiungibile.', false));
}

setInterval(() => {
  if (document.visibilityState !== 'visible' || document.getElementById('box-pin').hidden === false) return;
  fetch(`/ping?id=${id}&pin=${pin}`, {method: 'POST'})
    .then(r => { if (!r.ok) scollegato('Collegamento perso: ricollegati con il PIN.'); })
    .catch(() => {});
}, 8000);

document.getElementById('file').addEventListener('change', async (ev) => {
  const file = ev.target.files[0];
  ev.target.value = '';
  if (!file) return;
  contatore++;
  const url = URL.createObjectURL(file);
  const div = document.createElement('div');
  div.innerHTML = `<img src="${url}"><span>Invio...</span>`;
  document.getElementById('pagine').prepend(div);
  try {
    const r = await fetch(`/carica?id=${id}&pin=${pin}&pagina=${contatore}`,
                          {method: 'POST', body: file});
    if (r.status === 403) { scollegato('PIN scaduto: ricollegati.'); throw 0; }
    if (!r.ok) throw 0;
    div.querySelector('span').textContent = 'Inviata ✓';
  } catch (e) {
    div.querySelector('span').textContent = 'Errore';
  }
});

function base64UrlAUint8(base64) {
  const padding = '='.repeat((4 - base64.length % 4) % 4);
  const b64 = (base64 + padding).replace(/-/g, '+').replace(/_/g, '/');
  const grezzo = atob(b64);
  return Uint8Array.from([...grezzo].map(c => c.charCodeAt(0)));
}

async function abilitaNotifiche() {
  const btn = document.getElementById('notifiche');
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    btn.textContent = 'Notifiche non supportate da questo browser';
    return;
  }
  try {
    const rChiave = await fetch('/chiave-pubblica');
    if (!rChiave.ok) { btn.textContent = 'Notifiche non disponibili sul programma'; return; }
    const chiave = await rChiave.text();
    const perm = await Notification.requestPermission();
    if (perm !== 'granted') { btn.textContent = 'Notifiche rifiutate: abilitale nelle impostazioni del browser'; return; }
    const reg = await navigator.serviceWorker.ready;
    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: base64UrlAUint8(chiave),
      });
    }
    await fetch(`/sottoscrizione?id=${id}&pin=${pin}`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(sub),
    });
    btn.textContent = '✅ Notifiche attive';
    btn.classList.add('attive');
  } catch (e) {
    btn.textContent = 'Attivazione notifiche non riuscita';
  }
}

if (pin) { registra(); } else { scollegato('Inquadra di nuovo il QR o inserisci il PIN.'); }
if ('serviceWorker' in navigator) { navigator.serviceWorker.register('/sw.js').catch(() => {}); }
</script>
</body>
</html>
"""
