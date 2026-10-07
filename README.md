# Scansione Brother + OCR + LLM

Applicazione Windows che **scansiona documenti da uno scanner Brother**, ne
estrae il testo con OCR e **assegna automaticamente un nome al file PDF** in
base al contenuto del documento.

Pensata per lo sportello: si mette la carta d'identità (o la tessera sanitaria)
nello scanner e si ottiene un PDF già nominato con cognome, nome, comune di
residenza, tipo di servizio e data.

---

## Cosa fa

1. **Scansiona** da scanner Brother via WIA — rileva da solo se usare
   l'alimentatore (ADF) o il piano, corregge l'orientamento dei fogli storti.
   In alternativa allo scanner puoi **aggiungere un PDF o una foto** già
   presenti sul computer: le pagine entrano nella stessa sessione e seguono
   lo stesso percorso di riconoscimento.
2. **Riconosce il documento** fra i fogli scansionati (carta d'identità,
   tessera sanitaria, patente, passaporto).
3. **Estrae cognome e nome** in modo deterministico e verificato:
   - dalla **zona a lettura ottica (MRZ)**, il formato macchina in fondo al
     documento — la fonte più affidabile;
   - dai campi **COGNOME / NOME**, saltando le etichette bilingui e il campo
     dei genitori;
   - usando il **codice fiscale come checksum**: le prime sei lettere
     codificano cognome e nome, quindi individuano la parola giusta anche
     quando l'OCR la storpia.
4. **Estrae il comune di residenza** dalla voce *INDIRIZZO DI RESIDENZA*, con
   consolidamento fra le varie letture del documento.
5. **Chiede il tipo di servizio** e compone il nome finale:

```
carta_identita_Rossi_Mario_Verona_Attivazione_2026-07-23.pdf
```

6. Se qualcosa non è riconosciuto con certezza, **chiede conferma** invece di
   inventare. Il nome proposto è comunque sempre modificabile prima del
   salvataggio.

L'LLM locale (Ollama) interviene **solo come riserva** per i documenti generici:
sui documenti d'identità il riconoscimento è interamente deterministico.

---

## Scansionare con il telefono

Oltre allo scanner e ai file già presenti sul PC, le pagine si possono
acquisire con la fotocamera del telefono: nessuna app da installare, il
programma stesso espone una pagina web nella rete locale.

1. Premi **📱 Scansiona con telefono**: si apre una finestra con un **QR
   code**, il link diretto e un **PIN** a 4 cifre (rigenerato a ogni avvio,
   evita che altri dispositivi sulla stessa rete inviino foto per sbaglio).
2. Sul telefono (stessa rete Wi-Fi del PC) inquadra il QR con la fotocamera,
   oppure apri il link nel browser: la pagina si collega da sola (il PIN è
   già incluso nel QR).
3. Dalla pagina, **📷 Scatta pagina** apre la fotocamera del telefono: ogni
   foto scattata viene inviata subito al programma e compare nell'anteprima
   della sessione, pronta per **Elabora e salva PDF** insieme alle altre
   pagine.
4. La finestra sul PC mostra l'elenco dei **telefoni collegati** in tempo
   reale; **Ferma server** chiude il servizio (si può riavviare in
   qualsiasi momento).

La pagina si può anche "Aggiungere alla schermata Home" dal browser del
telefono, per richiamarla come una normale app: essendo QR e PIN legati alla
sessione del server, se cambiano basta reinquadrare il QR o digitare il
nuovo PIN mostrato dal programma.

### Avvisare il telefono dal programma (notifiche push)

Sulla pagina del telefono, **🔔 Attiva notifiche** abilita l'invio di una
notifica push al dispositivo. Da quel momento, nella finestra "Scansiona con
il telefono" sul PC, ogni telefono collegato ha un pulsante **📸 Notifica**:
premendolo, il telefono scelto riceve una notifica ("Il programma ti chiede
di scattare una pagina"), anche se il browser è in background — toccandola
si riapre la pagina pronta a scattare.

Da sapere:

- Le notifiche passano dal servizio push del browser (Google/Apple), quindi
  **serve Internet** sia sul PC sia sul telefono, non basta la rete locale.
- Su **iPhone** funzionano solo se la pagina è stata "Aggiunta alla
  schermata Home" (richiede iOS 16.4 o successivo): è un limite di Safari.
- Se il pulsante "📸 Notifica" è disattivato, il telefono non ha ancora
  premuto "Attiva notifiche" (o il permesso è stato negato nel browser).

### App Android (AppTelefono)

Oltre alla pagina web, il repository contiene un'app Android vera e propria
(cartella `AppTelefono/`), con interfaccia nativa (Kotlin, nessuna WebView):
schermata di collegamento, pulsante di scatto che apre la fotocamera del
telefono e griglia con lo stato di invio di ogni pagina. Parla con il
programma chiamando direttamente le stesse API HTTP della pagina web. Le
notifiche arrivano **in tempo reale sulla sola rete locale**, senza passare
da Internet ne' da un servizio push esterno (connessione long-poll verso
l'endpoint `/attendi-notifica` del programma, gestita da un servizio in
primo piano che resta attivo anche ad app in background).

**Uso:** installa l'APK sul telefono (va abilitata l'opzione "Installa da
fonti sconosciute" per il file), aprila, incolla il link mostrato dalla
finestra "Scansiona con il telefono" sul PC (pulsante "Copia") e premi
**Connetti**. Da quel momento il telefono compare nell'elenco sul PC con il
pulsante "📸 Notifica" già attivo, anche ad app in background.

- **Più programmi collegati**: l'app ricorda ogni PC a cui ti sei mai
  collegato. Dal menu "Cambia programma" torni all'elenco, dove ogni
  collegamento salvato ha un pulsante **Connetti** (per tornarci) e uno
  **🗑** per disabbinarlo definitivamente. Se il PIN di un collegamento
  salvato è scaduto (il PC è stato riavviato), basta incollare di nuovo il
  link aggiornato: aggiorna quello stesso collegamento invece di duplicarlo.
- **Riconoscimento e ritaglio automatico**: **📷 Scatta pagina** apre lo
  scanner di documenti di Google ML Kit, che riconosce da solo i bordi del
  documento nell'inquadratura, corregge la prospettiva e ritaglia — tutto
  sul telefono, prima ancora che la foto parta verso il programma. Richiede
  Google Play Services aggiornato (presente sulla quasi totalità dei
  telefoni Android con Play Store).
- **Fronte/retro in automatico**: dopo il primo scatto l'app legge il testo
  (sul telefono, con ML Kit) per capire se è un documento d'identità a due
  facciate (carta d'identità, tessera sanitaria, patente...). Se lo è,
  mostra un'animazione che chiede di girare il documento e scatta anche il
  retro, poi unisce fronte e retro in un'unica pagina prima di inviarla. Per
  un foglio, una SIM o qualunque altra cosa a facciata singola, invia
  subito la pagina singola senza chiedere altro.

**Ricompilare l'APK** (serve un Android SDK con `platform-tools`,
`platforms;android-34` e `build-tools;34.0.0`, referenziato in
`AppTelefono/local.properties` come `sdk.dir=...`):

```bash
cd AppTelefono
./gradlew assembleDebug
# APK: app/build/outputs/apk/debug/app-debug.apk
```

È una build di debug, pensata per l'installazione manuale interna: non è
firmata per la pubblicazione su store.

---

## Installazione

### Programma

Scarica `ScansioneBrother.exe` dall'ultima
[release](../../releases/latest) e mettilo dove preferisci. Non richiede
installazione: Python e le librerie sono già incluse.

Al primo avvio Windows potrebbe segnalare l'app come proveniente da un
editore sconosciuto, perché firmata con un certificato interno. **Non serve
più installarlo a mano**: l'app se ne accorge da sola e, se manca (o se nel
frattempo ne è uscito uno nuovo, come successo con la v1.1.0), chiede una
volta il permesso e lo installa con un'unica richiesta di Windows (UAC) —
niente più script da cercare ed eseguire come amministratore.

Se preferisci farlo comunque a mano (o l'installazione automatica non è
disponibile, ad esempio eseguendo da sorgente senza i permessi giusti):

```powershell
powershell -ExecutionPolicy Bypass -File .\Certificato\Installa_Certificato.ps1
```

Il vecchio certificato (prima della v1.1.0) si può rimuovere da
`certmgr.msc` → *Autorità di certificazione radice attendibili*.

### Componenti esterni richiesti

| Componente | A cosa serve | Note |
|---|---|---|
| **Tesseract-OCR** | lettura del testo | serve il pacchetto lingua **ita** |
| **pypdfium2** | lettura dei PDF importati | modulo Python, già incluso nell'eseguibile |
| **qrcode** | QR per la scansione da telefono | modulo Python, già incluso nell'eseguibile; senza, si usa il link a mano |
| **py_vapid / pywebpush** | notifiche push al telefono | moduli Python, già inclusi nell'eseguibile; senza, la scansione da telefono funziona lo stesso, solo senza il pulsante di notifica |
| **Ollama** | riserva per documenti generici | facoltativo per i documenti d'identità |

L'app prova a installarli da sola tramite `winget` al primo avvio (opzione
*Auto-installa dipendenze* nelle impostazioni).

Installazione manuale:

```powershell
winget install UB-Mannheim.TesseractOCR
winget install Ollama.Ollama
ollama pull qwen2.5:3b
```

---

## Uso

1. Avvia `ScansioneBrother.exe`.
2. **Scansiona pagine** — ripeti per aggiungere fogli; le miniature compaiono a
   sinistra e si possono rimuovere singolarmente.
   Oppure **Aggiungi PDF/foto** — vedi sotto.
3. **Elabora e salva PDF** — parte OCR e riconoscimento.
4. Inserisci il **tipo di servizio**, controlla il nome proposto e conferma.

### Aggiungere un PDF o una foto (senza scanner)

Il pulsante **📁 Aggiungi PDF/foto** apre una finestra di scelta file e mette
le pagine nella sessione esattamente come se fossero state scansionate: si
possono mescolare con le pagine dello scanner, riordinare l'aggiunta e
rimuovere le singole pagine, poi si preme **Elabora e salva PDF** come sempre.

- Si possono selezionare **più file insieme**; un PDF di più pagine diventa
  altrettante pagine.
- Formati accettati: `.pdf`, `.jpg`, `.jpeg`, `.png`, `.bmp`, `.tif`, `.tiff`,
  `.gif`, `.webp`.
- Le foto scattate col telefono vengono **raddrizzate** in base
  all'orientamento registrato dalla fotocamera (EXIF).
- Le pagine dei PDF vengono rasterizzate alla risoluzione impostata in ⚙
  (limitata all'intervallo 150–400 DPI: oltre non migliora l'OCR).
- Se un file non è leggibile, gli altri vengono importati lo stesso e compare
  un avviso con l'elenco degli scartati.

Per leggere i PDF serve un motore di rendering: l'app usa **pypdfium2**
(installato da solo al primo uso quando si lavora da sorgente, e incluso
nell'eseguibile), con riserva su PyMuPDF e pdf2image se già presenti.

### Impostazioni (icona ⚙)

| Parametro | Predefinito | Note |
|---|---|---|
| Risoluzione | 400 DPI | 300 è più veloce, 600 più preciso sulle tessere |
| Colore | RGB (24 bit) | |
| Origine | Auto | ADF se ha fogli, altrimenti piano |
| Cartella PDF | `Documenti\Scansioni` | |
| Scanner | automatico | menu a tendina con i dispositivi rilevati |
| Modello Ollama | `qwen2.5:3b` | |
| Tesseract | `C:\Program Files\Tesseract-OCR\tesseract.exe` | |
| Lingue OCR | `ita+eng` | |
| Qualità PDF | Massima | comprime il PDF per rientrare nei limiti di peso: Massima → Alta → Media → Bassa → Minima (file sempre più leggero) |

Le impostazioni si salvano in `scan_gui_config.json`, accanto all'eseguibile.

---

## Aggiornamenti

All'avvio l'app controlla se su GitHub è stata pubblicata una versione più
recente. Se c'è, compare un popup che chiede se installarla: al sì il nuovo
eseguibile viene scaricato, sostituito e l'app si riavvia da sola.

Il controllo si può lanciare anche a mano da **⚙ → Cerca aggiornamenti**.
Se non c'è rete, l'app parte normalmente senza avvisi.

---

## Risoluzione dei problemi

I log si trovano in `%USERPROFILE%\Scansioni\log\`:

- `scan_brother_ai.log` — cronologia delle operazioni;
- `ocr_<data>.txt` — il testo che l'OCR ha letto davvero, utile per capire
  perché un nome è stato sbagliato.

| Sintomo | Causa probabile |
|---|---|
| Nome sbagliato o mancante | scansione di qualità scarsa: prova il piano invece dell'ADF, o alza i DPI |
| «Impossibile leggere il PDF» | manca il motore di rendering: `pip install pypdfium2` |
| Foto ruotata di lato | la foto non ha l'orientamento EXIF: ruotala prima di aggiungerla |
| Chiede sempre quale scanner | seleziona il dispositivo da ⚙ → Scanner e salva |
| Windows blocca l'app | installa il certificato (vedi sopra) |
| OCR molto lento | abbassa i DPI a 300 |

---

## Struttura del progetto

```
scan_brother_ai.py        motore: scansione, OCR, riconoscimento
ScanApp/
  scan_gui.py             interfaccia grafica (CustomTkinter)
  aggiornamenti.py        controllo e installazione aggiornamenti
  telefono_scan.py        server locale per la scansione da telefono
  pagina_telefono.py      pagina web/PWA e service worker mostrati al telefono
  notifiche_push.py       chiavi VAPID e invio delle notifiche push
  finestra_telefono.py    finestra QR/PIN/elenco telefoni sul programma
  certificato.py          installazione automatica del certificato di firma
  Avvia_ScanApp.bat       avvio da sorgente
ScanProgram/
  ScansioneBrother.exe     eseguibile compilato
Certificato/
  Installa_Certificato.ps1 rende attendibile la firma
  Firma_Exe.ps1            rifirma l'exe dopo una ricompilazione
AppTelefono/
  app/src/main/java/...    app Android nativa (interfaccia propria + notifiche long-poll)
```

### Compilare

```powershell
py -m pip install pyinstaller customtkinter pywin32 pillow img2pdf pytesseract requests pypdfium2 qrcode py_vapid pywebpush
py -m PyInstaller --noconfirm --onefile --windowed --name ScansioneBrother `
   --icon ScanProgram\src\app.ico --add-data "ScanProgram\src\app.ico;." `
   --add-data "Certificato\ScansioneBrother.cer;." `
   --collect-all customtkinter --collect-all pypdfium2 --collect-all qrcode `
   --collect-all pywebpush --collect-all py_vapid `
   --hidden-import win32timezone --hidden-import win32com.client --hidden-import pythoncom `
   ScanProgram\src\scan_gui.py
```

Dopo la compilazione, rifirma l'eseguibile con `Certificato\Firma_Exe.ps1`. Il
file `.cer` incluso con `--add-data` è quello che l'app userà poi per
riconoscersi ed auto-installarsi: se cambi certificato, ricompila con il
nuovo `.cer` e chi aggiorna lo riceverà già pronto all'installazione
automatica.

### Pubblicare un aggiornamento

1. Aumenta `VERSIONE` in `ScanApp/aggiornamenti.py`.
2. Ricompila e rifirma.
3. Crea la release:

```powershell
gh release create v1.0.1 ScanProgram\ScansioneBrother.exe --title "v1.0.1" --notes "Descrizione delle novità"
```

Il file allegato **deve chiamarsi** `ScansioneBrother.exe`: è il nome che
l'app cerca per aggiornarsi.
