package it.scansionebrother.telefono

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.Log
import android.widget.Toast
import androidx.core.app.NotificationCompat
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Servizio in primo piano che resta in ascolto (long-poll sulla rete
 * locale, nessun account esterno ne' Internet necessari) delle notifiche
 * che il programma invia quando l'operatore sceglie questo telefono dalla
 * finestra "Scansiona con il telefono".
 *
 * NB: da Android 14 i servizi in primo piano di tipo "dataSync" hanno un
 * limite di alcune ore di esecuzione continuativa nella giornata; se
 * scatta, riaprire l'app lo riavvia.
 */
class NotificaService : Service() {

    @Volatile private var attivo = false
    private var thread: Thread? = null

    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(35, TimeUnit.SECONDS)
        .build()

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val id = intent?.getStringExtra("id")
        val pin = intent?.getStringExtra("pin")
        val origine = intent?.getStringExtra("origine")
        if (id == null || pin == null || origine == null) {
            Log.e(TAG, "Avvio senza id/pin/origine: intent incompleto")
            return START_NOT_STICKY
        }

        try {
            creaCanali()
            aggiornaNotificaServizio("Connessione al programma in corso...")
        } catch (e: Exception) {
            // Su alcuni telefoni (es. risparmio energetico aggressivo) avviare
            // un servizio in primo piano puo' essere negato dal sistema: lo
            // segnaliamo subito invece di fallire in silenzio.
            Log.e(TAG, "Impossibile avviare il servizio in primo piano", e)
            avvisa("Impossibile restare in ascolto delle notifiche: $e")
            stopSelf()
            return START_NOT_STICKY
        }

        if (thread?.isAlive != true) {
            attivo = true
            thread = Thread { cicloAttesa(id, pin, origine) }.apply {
                isDaemon = true
                start()
            }
        }
        return START_STICKY
    }

    private fun aggiornaNotificaServizio(testo: String) {
        val notifica = NotificationCompat.Builder(this, CANALE_SERVIZIO)
            .setContentTitle("Scansione documenti")
            .setContentText(testo)
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(1, notifica, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            startForeground(1, notifica)
        }
    }

    private fun avvisa(messaggio: String) {
        Handler(Looper.getMainLooper()).post {
            Toast.makeText(this, messaggio, Toast.LENGTH_LONG).show()
        }
    }

    private fun cicloAttesa(id: String, pin: String, origine: String) {
        var erroriConsecutivi = 0
        var collegatoSegnalato = false
        while (attivo) {
            try {
                val richiesta = Request.Builder()
                    .url("$origine/attendi-notifica?id=$id&pin=$pin")
                    .build()
                client.newCall(richiesta).execute().use { risposta ->
                    if (risposta.isSuccessful) {
                        erroriConsecutivi = 0
                        if (!collegatoSegnalato) {
                            collegatoSegnalato = true
                            aggiornaNotificaServizio("Collegato: in attesa di richieste dal PC.")
                            Log.i(TAG, "Long-poll attivo verso $origine")
                        }
                        val corpo = risposta.body?.string() ?: "{}"
                        if (JSONObject(corpo).optBoolean("notifica", false)) {
                            mostraAvviso()
                        }
                    } else {
                        Log.w(TAG, "Risposta ${risposta.code} da $origine")
                        Thread.sleep(3000)
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Errore long-poll verso $origine", e)
                erroriConsecutivi++
                if (erroriConsecutivi == 3) {
                    collegatoSegnalato = false
                    aggiornaNotificaServizio("Programma non raggiungibile: verifica di essere " +
                        "sulla stessa rete Wi-Fi.")
                }
                Thread.sleep(3000)
            }
        }
    }

    private fun mostraAvviso() {
        val apri = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        val pendente = PendingIntent.getActivity(
            this, 0, apri,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val notifica = NotificationCompat.Builder(this, CANALE_AVVISO)
            .setContentTitle("Scansione documenti")
            .setContentText("Il programma ti chiede di scattare una pagina.")
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .setContentIntent(pendente)
            .setVibrate(longArrayOf(0, 300, 150, 300))
            .build()
        getSystemService(NotificationManager::class.java).notify(2, notifica)
    }

    private fun creaCanali() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val gestore = getSystemService(NotificationManager::class.java)
        gestore.createNotificationChannel(NotificationChannel(
            CANALE_SERVIZIO, "Collegamento attivo", NotificationManager.IMPORTANCE_LOW))
        gestore.createNotificationChannel(NotificationChannel(
            CANALE_AVVISO, "Richieste di scansione", NotificationManager.IMPORTANCE_HIGH))
    }

    override fun onDestroy() {
        attivo = false
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        private const val TAG = "NotificaService"
        private const val CANALE_SERVIZIO = "servizio"
        private const val CANALE_AVVISO = "avviso"
    }
}
