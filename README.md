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

## Installazione

### Programma

Scarica `ScansioneBrother.exe` dall'ultima
[release](../../releases/latest) e mettilo dove preferisci. Non richiede
installazione: Python e le librerie sono già incluse.

Al primo avvio Windows potrebbe bloccare l'app perché firmata con un
certificato interno. Per risolvere una volta per tutte, esegui **come
amministratore**:

```powershell
powershell -ExecutionPolicy Bypass -File .\Certificato\Installa_Certificato.ps1
```

### Componenti esterni richiesti

| Componente | A cosa serve | Note |
|---|---|---|
| **Tesseract-OCR** | lettura del testo | serve il pacchetto lingua **ita** |
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
3. **Elabora e salva PDF** — parte OCR e riconoscimento.
4. Inserisci il **tipo di servizio**, controlla il nome proposto e conferma.

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
  Avvia_ScanApp.bat       avvio da sorgente
ScanProgram/
  ScansioneBrother.exe     eseguibile compilato
Certificato/
  Installa_Certificato.ps1 rende attendibile la firma
  Firma_Exe.ps1            rifirma l'exe dopo una ricompilazione
```

### Compilare

```powershell
py -m pip install pyinstaller customtkinter pywin32 pillow img2pdf pytesseract requests
py -m PyInstaller --noconfirm --onefile --windowed --name ScansioneBrother `
   --icon ScanProgram\src\app.ico --add-data "ScanProgram\src\app.ico;." `
   --collect-all customtkinter `
   --hidden-import win32timezone --hidden-import win32com.client --hidden-import pythoncom `
   ScanProgram\src\scan_gui.py
```

Dopo la compilazione, rifirma l'eseguibile con `Certificato\Firma_Exe.ps1`.

### Pubblicare un aggiornamento

1. Aumenta `VERSIONE` in `ScanApp/aggiornamenti.py`.
2. Ricompila e rifirma.
3. Crea la release:

```powershell
gh release create v1.0.1 ScanProgram\ScansioneBrother.exe --title "v1.0.1" --notes "Descrizione delle novità"
```

Il file allegato **deve chiamarsi** `ScansioneBrother.exe`: è il nome che
l'app cerca per aggiornarsi.
