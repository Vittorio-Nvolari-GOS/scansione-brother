package it.scansionebrother.telefono

import android.Manifest
import android.animation.ObjectAnimator
import android.animation.ValueAnimator
import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.view.Menu
import android.view.MenuItem
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import android.widget.ViewFlipper
import androidx.activity.result.IntentSenderRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.GridLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.documentscanner.GmsDocumentScannerOptions
import com.google.mlkit.vision.documentscanner.GmsDocumentScanning
import com.google.mlkit.vision.documentscanner.GmsDocumentScanningResult
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.File
import java.io.FileOutputStream
import java.util.UUID
import java.util.concurrent.TimeUnit

/**
 * App nativa (nessuna WebView): schermata di collegamento (con l'elenco dei
 * programmi gia' salvati, per passare da uno all'altro o disabbinarli) e
 * schermata di scansione, con viste proprie. Parla con il programma sul PC
 * chiamando direttamente le stesse API HTTP usate dalla pagina web
 * (telefono_scan.py).
 */
class MainActivity : AppCompatActivity() {

    private lateinit var prefs: SharedPreferences
    private lateinit var flipper: ViewFlipper
    private lateinit var testoStato: TextView
    private lateinit var adapter: PagineAdapter
    private val pagine = mutableListOf<Pagina>()

    private var origine: String = ""
    private var pin: String = ""
    private var id: String = ""
    private var contatorePagine = 0
    private var uriFronteInAttesa: Uri? = null
    private var animazioneGirare: ObjectAnimator? = null
    private val riconoscitoreTesto by lazy { TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS) }

    private val client = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .build()

    // Scanner ML Kit: riconosce da solo il documento nell'inquadratura, lo
    // ritaglia e corregge la prospettiva sul telefono, prima ancora che la
    // foto venga inviata al programma.
    private val opzioniScanner = GmsDocumentScannerOptions.Builder()
        .setGalleryImportAllowed(false)
        .setPageLimit(1)
        .setResultFormats(GmsDocumentScannerOptions.RESULT_FORMAT_JPEG)
        .setScannerMode(GmsDocumentScannerOptions.SCANNER_MODE_FULL)
        .build()
    private val scanner by lazy { GmsDocumentScanning.getClient(opzioniScanner) }

    // Scanner di codici QR "pronto all'uso" (stessa famiglia ML Kit): apre
    // da solo una fotocamera dedicata e ritorna il testo del QR, senza
    // bisogno di gestire noi l'anteprima della fotocamera.
    private val opzioniScannerQr = GmsBarcodeScannerOptions.Builder()
        .setBarcodeFormats(Barcode.FORMAT_QR_CODE)
        .build()
    private val scannerQr by lazy { GmsBarcodeScanning.getClient(this, opzioniScannerQr) }

    private val scannerLauncher = registerForActivityResult(
        ActivityResultContracts.StartIntentSenderForResult()
    ) { risultato ->
        if (risultato.resultCode != Activity.RESULT_OK) return@registerForActivityResult
        val esito = GmsDocumentScanningResult.fromActivityResultIntent(risultato.data)
        val uri = esito?.pages?.firstOrNull()?.imageUri
        if (uri == null) {
            Toast.makeText(this, "Nessuna pagina rilevata.", Toast.LENGTH_SHORT).show()
            return@registerForActivityResult
        }
        val fronte = uriFronteInAttesa
        if (fronte != null) {
            // Era lo scatto del retro, richiesto dopo aver riconosciuto un
            // documento a due facciate.
            uriFronteInAttesa = null
            componiEInvia(fronte, uri)
        } else {
            analizzaEProsegui(uri)
        }
    }

    private val permessi = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { /* si prosegue comunque: senza permesso fotocamera/notifiche l'app
          segnala il problema al momento giusto (scatto o notifiche) */ }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        prefs = getSharedPreferences("scansione_telefono", Context.MODE_PRIVATE)

        val richieste = mutableListOf(Manifest.permission.CAMERA)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            richieste.add(Manifest.permission.POST_NOTIFICATIONS)
        }
        permessi.launch(richieste.toTypedArray())

        flipper = findViewById(R.id.flipper)
        testoStato = findViewById(R.id.testo_stato)

        val griglia = findViewById<RecyclerView>(R.id.griglia_pagine)
        adapter = PagineAdapter(pagine)
        griglia.layoutManager = GridLayoutManager(this, 3)
        griglia.adapter = adapter

        findViewById<Button>(R.id.bottone_connetti).setOnClickListener { connettiDaCampi() }
        findViewById<Button>(R.id.bottone_scansiona_qr).setOnClickListener { scansionaQr() }
        findViewById<Button>(R.id.bottone_scatta).setOnClickListener { scattaPagina() }
        findViewById<Button>(R.id.bottone_scatta_retro).setOnClickListener { avviaScannerMlKit() }
        findViewById<Button>(R.id.bottone_solo_fronte).setOnClickListener { inviaSoloFronte() }
        findViewById<Button>(R.id.bottone_menu).setOnClickListener { apriGestioneConnessioni() }

        id = prefs.getString("tel_id", null) ?: UUID.randomUUID().toString().also {
            prefs.edit().putString("tel_id", it).apply()
        }

        ricostruisciListaProfili()

        val ultimaOrigine = prefs.getString("ultima_origine", null)
        val profiloAttivo = caricaProfili(prefs).firstOrNull { it.origine == ultimaOrigine }
        if (profiloAttivo != null) {
            connettiConProfilo(profiloAttivo, silenzioso = true)
        }
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menu.add(0, 1, 0, "Cambia programma")
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        if (item.itemId == 1) {
            apriGestioneConnessioni()
            return true
        }
        return super.onOptionsItemSelected(item)
    }

    /** Richiamata dal pulsante ☰ nella schermata di scansione (o dal menu
     * di sistema): torna all'elenco dei collegamenti senza perdere quelli
     * gia' salvati, cosi' si passa da un PC all'altro senza dover
     * "resettare" l'app. Il servizio di notifiche del PC precedente viene
     * fermato; quello nuovo riparte al momento del collegamento. */
    private fun apriGestioneConnessioni() {
        prefs.edit().remove("ultima_origine").apply()
        stopService(Intent(this, NotificaService::class.java))
        fermaAnimazioneGirare()
        uriFronteInAttesa = null
        pagine.clear()
        adapter.notifyDataSetChanged()
        ricostruisciListaProfili()
        flipper.displayedChild = 0
    }

    // -------------------------------------------------- Elenco collegamenti
    private fun ricostruisciListaProfili() {
        val contenitore = findViewById<LinearLayout>(R.id.lista_profili)
        contenitore.removeAllViews()
        caricaProfili(prefs).forEach { profilo ->
            val riga = layoutInflater.inflate(R.layout.item_profilo, contenitore, false)
            riga.findViewById<TextView>(R.id.testo_soprannome).text = profilo.soprannome
            riga.findViewById<TextView>(R.id.testo_etichetta).text =
                "${profilo.etichetta} · ${profilo.nome}"
            riga.findViewById<Button>(R.id.bottone_connetti_profilo).setOnClickListener {
                connettiConProfilo(profilo)
            }
            riga.findViewById<Button>(R.id.bottone_rinomina_profilo).setOnClickListener {
                chiediSoprannome(profilo)
            }
            riga.findViewById<Button>(R.id.bottone_rimuovi_profilo).setOnClickListener {
                rimuoviProfilo(prefs, profilo)
                if (prefs.getString("ultima_origine", null) == profilo.origine) {
                    prefs.edit().remove("ultima_origine").apply()
                }
                ricostruisciListaProfili()
            }
            contenitore.addView(riga)
        }
    }

    private fun chiediSoprannome(profilo: Profilo) {
        val campo = EditText(this).apply { setText(profilo.soprannome) }
        AlertDialog.Builder(this)
            .setTitle("Soprannome per questo PC")
            .setView(campo)
            .setPositiveButton("Salva") { _, _ ->
                val nuovo = campo.text.toString().trim()
                if (nuovo.isNotEmpty()) {
                    rinominaProfilo(prefs, profilo, nuovo)
                    ricostruisciListaProfili()
                }
            }
            .setNegativeButton("Annulla", null)
            .show()
    }

    /** Apre lo scanner QR "pronto all'uso" di ML Kit e, se il codice letto
     * e' un link valido, lo mette nel campo URL e collega subito: cosi' non
     * serve mai incollare il link a mano. */
    private fun scansionaQr() {
        scannerQr.startScan()
            .addOnSuccessListener { codice ->
                val valore = codice.rawValue
                if (valore == null || (!valore.startsWith("http://") &&
                                       !valore.startsWith("https://"))) {
                    Toast.makeText(this, "Il QR inquadrato non contiene un link valido.",
                        Toast.LENGTH_LONG).show()
                    return@addOnSuccessListener
                }
                findViewById<EditText>(R.id.campo_url).setText(valore)
                connettiDaCampi()
            }
            .addOnCanceledListener { /* l'utente ha chiuso lo scanner: nessuna azione */ }
            .addOnFailureListener { e ->
                Toast.makeText(this,
                    "Scanner QR non disponibile: ${e.message}", Toast.LENGTH_LONG).show()
            }
    }

    private fun connettiDaCampi() {
        val testo = findViewById<EditText>(R.id.campo_url).text.toString().trim()
        val nome = findViewById<EditText>(R.id.campo_nome).text.toString().trim()
            .ifEmpty { "Telefono" }
        val soprannomeScelto = findViewById<EditText>(R.id.campo_soprannome).text.toString().trim()
        val errore = findViewById<TextView>(R.id.testo_errore_collegamento)
        errore.visibility = View.GONE
        if (!testo.startsWith("http://") && !testo.startsWith("https://")) {
            errore.text = "Incolla il link completo mostrato dal programma."
            errore.visibility = View.VISIBLE
            return
        }
        val uri = try { Uri.parse(testo) } catch (e: Exception) { null }
        val pinEstratto = uri?.getQueryParameter("pin")
        if (uri == null || pinEstratto == null || uri.host == null) {
            mostraErroreCollegamento("Link non valido: copialo di nuovo dal programma.")
            return
        }
        val nuovaOrigine = buildString {
            append(uri.scheme ?: "http").append("://").append(uri.host)
            if (uri.port != -1) append(":").append(uri.port)
        }
        val etichetta = nuovaOrigine.removePrefix("http://").removePrefix("https://")
        val soprannome = soprannomeScelto.ifEmpty { etichetta }
        registra(Profilo(etichetta, nome, nuovaOrigine, pinEstratto, soprannome),
            silenzioso = false)
    }

    private fun connettiConProfilo(profilo: Profilo, silenzioso: Boolean = false) {
        registra(profilo, silenzioso)
    }

    private fun registra(profilo: Profilo, silenzioso: Boolean) {
        Thread {
            try {
                val richiesta = Request.Builder()
                    .url("${profilo.origine}/registra?id=$id&nome=${Uri.encode(profilo.nome)}" +
                        "&pin=${profilo.pin}")
                    .post(ByteArray(0).toRequestBody(null))
                    .build()
                client.newCall(richiesta).execute().use { risposta ->
                    runOnUiThread {
                        if (risposta.isSuccessful) {
                            origine = profilo.origine
                            pin = profilo.pin
                            val salvato = salvaOAggiornaProfilo(prefs, profilo)
                            prefs.edit().putString("ultima_origine", profilo.origine).apply()
                            avviaSchermataScansione(salvato.nome)
                        } else if (!silenzioso) {
                            mostraErroreCollegamento(
                                "PIN errato o scaduto: incolla un link aggiornato dal programma.")
                        }
                    }
                }
            } catch (e: Exception) {
                if (!silenzioso) {
                    runOnUiThread {
                        mostraErroreCollegamento("Programma non raggiungibile: controlla di " +
                            "essere sulla stessa rete Wi-Fi del PC.")
                    }
                }
            }
        }.start()
    }

    private fun mostraErroreCollegamento(messaggio: String) {
        val errore = findViewById<TextView>(R.id.testo_errore_collegamento)
        errore.text = messaggio
        errore.visibility = View.VISIBLE
    }

    private fun avviaSchermataScansione(nome: String) {
        flipper.displayedChild = 1
        testoStato.text = "Collegato come «$nome». Pronto a scansionare."

        val intent = Intent(this, NotificaService::class.java).apply {
            putExtra("id", id)
            putExtra("pin", pin)
            putExtra("origine", origine)
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent)
        } else {
            startService(intent)
        }
        chiediEsclusioneRisparmioEnergetico()
    }

    /** Su molti telefoni (soprattutto Xiaomi/Poco/HyperOS-MIUI) il sistema
     * puo' fermare il servizio delle notifiche poco dopo l'avvio se l'app
     * non e' esclusa dal risparmio energetico: lo chiediamo una volta sola,
     * subito dopo il collegamento. */
    private fun chiediEsclusioneRisparmioEnergetico() {
        val gestore = getSystemService(Context.POWER_SERVICE) as? PowerManager ?: return
        if (gestore.isIgnoringBatteryOptimizations(packageName)) return
        try {
            startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).apply {
                data = Uri.parse("package:$packageName")
            })
        } catch (e: Exception) {
            // Alcuni produttori bloccano questo intent: si procede comunque.
        }
    }

    // ------------------------------------------------------------ Scatto
    private fun scattaPagina() {
        uriFronteInAttesa = null
        avviaScannerMlKit()
    }

    private fun avviaScannerMlKit() {
        scanner.getStartScanIntent(this)
            .addOnSuccessListener { intentSender ->
                scannerLauncher.launch(IntentSenderRequest.Builder(intentSender).build())
            }
            .addOnFailureListener { e ->
                Toast.makeText(this,
                    "Scanner non disponibile: ${e.message}\n" +
                    "Verifica che Google Play Services sia aggiornato.",
                    Toast.LENGTH_LONG).show()
            }
    }

    /** Dopo il primo scatto: se il testo letto sembra quello di un
     * documento d'identita' (carta d'identita', tessera sanitaria,
     * patente...) chiede anche il retro, altrimenti (foglio, SIM, ricevuta)
     * invia subito la pagina singola. Il riconoscimento gira sul telefono,
     * non serve la rete. */
    private fun analizzaEProsegui(uri: Uri) {
        val immagine = try {
            InputImage.fromFilePath(this, uri)
        } catch (e: Exception) {
            null
        }
        if (immagine == null) {
            inviaPagina(uri)
            return
        }
        riconoscitoreTesto.process(immagine)
            .addOnSuccessListener { testo ->
                if (sembraDocumentoIdentita(testo.text)) {
                    mostraRichiestaRetro(uri)
                } else {
                    inviaPagina(uri)
                }
            }
            .addOnFailureListener {
                // Se il riconoscimento fallisce non blocchiamo la scansione:
                // si invia il fronte come pagina singola.
                inviaPagina(uri)
            }
    }

    private fun mostraRichiestaRetro(uriFronte: Uri) {
        uriFronteInAttesa = uriFronte
        flipper.displayedChild = 2
        avviaAnimazioneGirare()
    }

    private fun avviaAnimazioneGirare() {
        fermaAnimazioneGirare()
        val icona = findViewById<TextView>(R.id.icona_girare)
        animazioneGirare = ObjectAnimator.ofFloat(icona, View.ROTATION_Y, 0f, 180f, 360f).apply {
            duration = 1400
            repeatCount = ValueAnimator.INFINITE
            start()
        }
    }

    private fun fermaAnimazioneGirare() {
        animazioneGirare?.cancel()
        animazioneGirare = null
    }

    private fun inviaSoloFronte() {
        val fronte = uriFronteInAttesa ?: return
        uriFronteInAttesa = null
        fermaAnimazioneGirare()
        flipper.displayedChild = 1
        inviaPagina(fronte)
    }

    /** La pagina arriva gia' riconosciuta, ritagliata e con la prospettiva
     * corretta dallo scanner: qui la si invia soltanto al programma. */
    private fun inviaPagina(uri: Uri) {
        val pagina = Pagina(uri, "Invio...")
        adapter.aggiungi(pagina)
        contatorePagine++
        val numeroPagina = contatorePagine

        Thread {
            try {
                val dati = contentResolver.openInputStream(uri)?.use { it.readBytes() }
                    ?: throw IllegalStateException("pagina non leggibile")
                inviaBytes(pagina, numeroPagina, dati)
            } catch (e: Exception) {
                runOnUiThread { adapter.aggiornaStato(pagina, "Errore") }
            }
        }.start()
    }

    /** Fronte e retro riconosciuti come un documento d'identita': li
     * compone in un'unica immagine (una sopra l'altra) e invia quella,
     * cosi' il programma riceve una sola pagina per il documento. */
    private fun componiEInvia(fronte: Uri, retro: Uri) {
        fermaAnimazioneGirare()
        flipper.displayedChild = 1
        val pagina = Pagina(fronte, "Composizione...")
        adapter.aggiungi(pagina)
        contatorePagine++
        val numeroPagina = contatorePagine

        Thread {
            try {
                val bitmapFronte = caricaBitmap(fronte)
                val bitmapRetro = caricaBitmap(retro)
                val combinato = componiFronteRetro(bitmapFronte, bitmapRetro)
                val buffer = java.io.ByteArrayOutputStream()
                combinato.compress(Bitmap.CompressFormat.JPEG, 90, buffer)
                val dati = buffer.toByteArray()

                val fileCombinato = File(cacheDir, "pagina_$numeroPagina.jpg")
                FileOutputStream(fileCombinato).use { it.write(dati) }
                runOnUiThread { adapter.aggiornaUri(pagina, Uri.fromFile(fileCombinato)) }
                inviaBytes(pagina, numeroPagina, dati)
            } catch (e: Exception) {
                runOnUiThread { adapter.aggiornaStato(pagina, "Errore") }
            }
        }.start()
    }

    override fun onDestroy() {
        fermaAnimazioneGirare()
        riconoscitoreTesto.close()
        super.onDestroy()
    }

    private fun caricaBitmap(uri: Uri): Bitmap =
        contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it) }
            ?: throw IllegalStateException("immagine non leggibile")

    /** Invio HTTP condiviso da pagina singola e pagina fronte/retro
     * composta: gira gia' su un thread in background quando viene
     * chiamata. */
    private fun inviaBytes(pagina: Pagina, numeroPagina: Int, dati: ByteArray) {
        runOnUiThread { adapter.aggiornaStato(pagina, "Invio...") }
        try {
            val corpo = dati.toRequestBody("image/jpeg".toMediaType())
            val richiesta = Request.Builder()
                .url("$origine/carica?id=$id&pin=$pin&pagina=$numeroPagina")
                .post(corpo)
                .build()
            client.newCall(richiesta).execute().use { risposta ->
                runOnUiThread {
                    adapter.aggiornaStato(pagina,
                        if (risposta.isSuccessful) "Inviata ✓" else "Errore")
                }
            }
        } catch (e: Exception) {
            runOnUiThread { adapter.aggiornaStato(pagina, "Errore") }
        }
    }
}
