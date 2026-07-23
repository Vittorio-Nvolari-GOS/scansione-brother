# ============================================================================
#  Installa_Certificato.ps1
#  Rende attendibile su QUESTO PC il certificato con cui e' firmata l'app
#  "ScansioneBrother.exe", cosi' Windows non la blocca piu'.
#
#  COSA FA:
#   - installa il certificato "Scansione Brother" fra le Autorita' di
#     certificazione radice attendibili e fra gli Editori attendibili
#     del computer locale.
#
#  COSA SIGNIFICA:
#   - Windows si fidera' dei programmi firmati con QUESTO certificato.
#     E' un certificato creato da te per uso interno: tienilo al sicuro
#     (il file .pfx, se lo esporti) e non condividerlo.
#
#  COME SI USA:
#   - tasto destro su questo file -> "Esegui con PowerShell" COME AMMINISTRATORE
#     oppure, da un PowerShell amministratore:
#         powershell -ExecutionPolicy Bypass -File .\Installa_Certificato.ps1
#
#  PER ANNULLARE:
#   - certmgr.msc -> Autorita' di certificazione radice attendibili ->
#     Certificati -> elimina "Scansione Brother"
# ============================================================================

$ErrorActionPreference = "Stop"
$cer = Join-Path $PSScriptRoot "ScansioneBrother.cer"

if (-not (Test-Path $cer)) {
    Write-Host "[ERRORE] Certificato non trovato: $cer" -ForegroundColor Red
    Read-Host "Premi INVIO per uscire"
    exit 1
}

# Verifica privilegi di amministratore
$admin = ([Security.Principal.WindowsPrincipal] `
          [Security.Principal.WindowsIdentity]::GetCurrent()
         ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Write-Host "[ERRORE] Serve eseguire questo script COME AMMINISTRATORE." -ForegroundColor Red
    Write-Host "         Tasto destro su PowerShell -> Esegui come amministratore."
    Read-Host "Premi INVIO per uscire"
    exit 1
}

Write-Host "Installazione del certificato in corso..." -ForegroundColor Cyan
Import-Certificate -FilePath $cer -CertStoreLocation "Cert:\LocalMachine\Root" | Out-Null
Import-Certificate -FilePath $cer -CertStoreLocation "Cert:\LocalMachine\TrustedPublisher" | Out-Null

Write-Host ""
Write-Host "Certificato installato." -ForegroundColor Green

# Verifica: la firma dell'eseguibile ora deve risultare valida
$exe = Join-Path (Split-Path $PSScriptRoot -Parent) "ScanProgram\ScansioneBrother.exe"
if (Test-Path $exe) {
    $f = Get-AuthenticodeSignature $exe
    Write-Host "Stato firma di ScansioneBrother.exe: $($f.Status)"
    if ($f.Status -eq "Valid") {
        Write-Host "Windows non blocchera' piu' l'applicazione." -ForegroundColor Green
    }
}

Read-Host "`nPremi INVIO per chiudere"
