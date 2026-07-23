# ============================================================================
#  Firma_Exe.ps1
#  Rifirma ScansioneBrother.exe dopo una ricompilazione.
#  (PyInstaller produce un exe non firmato: va rifirmato ogni volta.)
#
#  Uso:  powershell -ExecutionPolicy Bypass -File .\Firma_Exe.ps1
# ============================================================================

$ErrorActionPreference = "Stop"
$exe = Join-Path (Split-Path $PSScriptRoot -Parent) "ScanProgram\ScansioneBrother.exe"

if (-not (Test-Path $exe)) {
    Write-Host "[ERRORE] Eseguibile non trovato: $exe" -ForegroundColor Red
    Read-Host "Premi INVIO per uscire"
    exit 1
}

# Cerca il certificato di firma nell'archivio personale dell'utente
$cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
        Where-Object { $_.Subject -like "*Scansione Brother*" } |
        Sort-Object NotAfter -Descending | Select-Object -First 1

if (-not $cert) {
    Write-Host "[ERRORE] Certificato 'Scansione Brother' non trovato." -ForegroundColor Red
    Write-Host "         Va creato una sola volta con:"
    Write-Host '         New-SelfSignedCertificate -Type CodeSigningCert -Subject "CN=Scansione Brother, O=Uso Interno" -CertStoreLocation "Cert:\CurrentUser\My" -NotAfter (Get-Date).AddYears(5)'
    Read-Host "Premi INVIO per uscire"
    exit 1
}

# Chiude l'app se in esecuzione (l'exe non sarebbe scrivibile)
Get-Process ScansioneBrother -ErrorAction SilentlyContinue |
    Stop-Process -Force -Confirm:$false
Start-Sleep -Seconds 1

$r = Set-AuthenticodeSignature -FilePath $exe -Certificate $cert `
        -TimestampServer "http://timestamp.digicert.com" -HashAlgorithm SHA256

Write-Host "Firmato: $exe"
Write-Host "Stato  : $($r.Status)"
Read-Host "`nPremi INVIO per chiudere"
