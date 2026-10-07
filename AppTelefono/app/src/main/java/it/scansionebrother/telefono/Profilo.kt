package it.scansionebrother.telefono

import android.content.SharedPreferences
import org.json.JSONArray
import org.json.JSONObject

/** Un programma a cui il telefono si e' collegato almeno una volta.
 * L'app ne ricorda piu' di uno (uno per PC/postazione): l'operatore sceglie
 * a quale collegarsi (con un soprannome a piacere, es. "PC Sportello"),
 * puo' "disabbinare" (rimuovere) quelli che non servono piu', e li vede
 * ordinati dal piu' recente. Il PIN si aggiorna ad ogni nuovo collegamento
 * riuscito, perche' cambia a ogni riavvio del server sul PC. */
data class Profilo(
    val etichetta: String,          // host:porta, ricavato dal link
    val nome: String,               // nome di questo telefono inviato al programma
    val origine: String,
    val pin: String,
    val soprannome: String = etichetta,
    val ultimoUso: Long = System.currentTimeMillis(),
) {
    fun aJson(): JSONObject = JSONObject().apply {
        put("etichetta", etichetta)
        put("nome", nome)
        put("origine", origine)
        put("pin", pin)
        put("soprannome", soprannome)
        put("ultimoUso", ultimoUso)
    }

    companion object {
        fun daJson(j: JSONObject): Profilo {
            val etichetta = j.getString("etichetta")
            return Profilo(
                etichetta = etichetta,
                nome = j.getString("nome"),
                origine = j.getString("origine"),
                pin = j.getString("pin"),
                soprannome = j.optString("soprannome", etichetta),
                ultimoUso = j.optLong("ultimoUso", 0L))
        }
    }
}

private const val CHIAVE_PROFILI = "profili"

/** Ordinati dal piu' recente: e' l'ordine in cui vanno mostrati in elenco. */
fun caricaProfili(prefs: SharedPreferences): MutableList<Profilo> {
    val grezzo = prefs.getString(CHIAVE_PROFILI, null) ?: return mutableListOf()
    val lista = try {
        val array = JSONArray(grezzo)
        MutableList(array.length()) { Profilo.daJson(array.getJSONObject(it)) }
    } catch (e: Exception) {
        mutableListOf()
    }
    lista.sortByDescending { it.ultimoUso }
    return lista
}

fun salvaProfili(prefs: SharedPreferences, profili: List<Profilo>) {
    val array = JSONArray()
    profili.forEach { array.put(it.aJson()) }
    prefs.edit().putString(CHIAVE_PROFILI, array.toString()).apply()
}

/** Aggiunge il profilo, oppure aggiorna quello con la stessa origine se
 * gia' presente: mantiene il soprannome scelto in precedenza e segna il
 * momento del collegamento (per l'ordine "piu' recenti prima"). Ritorna il
 * profilo effettivamente salvato. */
fun salvaOAggiornaProfilo(prefs: SharedPreferences, nuovo: Profilo): Profilo {
    val profili = caricaProfili(prefs)
    val indice = profili.indexOfFirst { it.origine == nuovo.origine }
    val soprannome = if (indice >= 0) profili[indice].soprannome else nuovo.soprannome
    val daSalvare = nuovo.copy(soprannome = soprannome, ultimoUso = System.currentTimeMillis())
    if (indice >= 0) profili[indice] = daSalvare else profili.add(daSalvare)
    salvaProfili(prefs, profili)
    return daSalvare
}

fun rinominaProfilo(prefs: SharedPreferences, profilo: Profilo, nuovoSoprannome: String) {
    val profili = caricaProfili(prefs)
    val indice = profili.indexOfFirst { it.origine == profilo.origine }
    if (indice >= 0) {
        profili[indice] = profili[indice].copy(soprannome = nuovoSoprannome)
        salvaProfili(prefs, profili)
    }
}

fun rimuoviProfilo(prefs: SharedPreferences, profilo: Profilo) {
    val profili = caricaProfili(prefs)
    profili.removeAll { it.origine == profilo.origine }
    salvaProfili(prefs, profili)
}
