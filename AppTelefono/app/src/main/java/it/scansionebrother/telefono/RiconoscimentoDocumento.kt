package it.scansionebrother.telefono

/** Decide se la pagina appena scattata e' la facciata di un documento
 * d'identita' a due facciate (carta d'identita', tessera sanitaria,
 * patente) oppure qualcosa a facciata singola (foglio, SIM, ricevuta...).
 *
 * Euristica sul testo letto da ML Kit (nessuna chiamata al programma: gira
 * tutto sul telefono, e' solo per decidere se chiedere anche il retro):
 * - parole chiave tipiche dei documenti d'identita' italiani/europei;
 * - una riga in stile MRZ (zona a lettura ottica), fatta di lettere/cifre
 *   maiuscole intervallate da piu' '<' di riempimento.
 *
 * Non e' un OCR affidabile al 100% (lo fa gia' il programma sul PC): basta
 * che funzioni per la stragrande maggioranza dei casi, un falso negativo
 * costa solo un tocco in piu' su "Scatta il retro" quando serve davvero. */
fun sembraDocumentoIdentita(testo: String): Boolean {
    val maiuscolo = testo.uppercase()

    val paroleChiave = listOf(
        "REPUBBLICA ITALIANA", "CARTA D'IDENTITA", "CARTA DI IDENTITA",
        "IDENTITY CARD", "CARTE D'IDENTITE",
        "PATENTE DI GUIDA", "DRIVING LICENCE", "DRIVING LICENSE", "PERMIS DE CONDUIRE",
        "TESSERA SANITARIA", "HEALTH CARD", "CARTA SANITARIA",
        "PASSAPORTO", "PASSPORT", "REISEPASS",
    )
    if (paroleChiave.any { maiuscolo.contains(it) }) return true

    // Riga MRZ: sequenza lunga di lettere/cifre/'<' con almeno un po' di
    // riempimento '<', tipica del fondo di CI/patente/passaporto.
    return Regex("[A-Z0-9<]{20,}").findAll(maiuscolo)
        .any { risultato -> risultato.value.count { it == '<' } >= 3 }
}
