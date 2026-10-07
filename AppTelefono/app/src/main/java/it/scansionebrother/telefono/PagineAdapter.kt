package it.scansionebrother.telefono

import android.net.Uri
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView

/** Una pagina scattata: l'anteprima e lo stato dell'invio al programma.
 * 'uri' e' var perche' per un documento fronte/retro l'anteprima passa
 * dalla sola foto del fronte all'immagine composta una volta pronta. */
data class Pagina(var uri: Uri, var stato: String = "Invio...")

/** Griglia delle pagine scattate in questa sessione, con lo stato di invio
 * di ciascuna (stessa idea della pagina web, ma con viste native). */
class PagineAdapter(private val pagine: MutableList<Pagina>) :
    RecyclerView.Adapter<PagineAdapter.ViewHolder>() {

    class ViewHolder(vista: View) : RecyclerView.ViewHolder(vista) {
        val immagine: ImageView = vista.findViewById(R.id.immagine_pagina)
        val stato: TextView = vista.findViewById(R.id.stato_pagina)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val vista = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_pagina, parent, false)
        return ViewHolder(vista)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val pagina = pagine[position]
        holder.immagine.setImageURI(pagina.uri)
        holder.stato.text = pagina.stato
    }

    override fun getItemCount() = pagine.size

    fun aggiungi(pagina: Pagina) {
        pagine.add(0, pagina)
        notifyItemInserted(0)
    }

    fun aggiornaStato(pagina: Pagina, nuovoStato: String) {
        val indice = pagine.indexOf(pagina)
        if (indice >= 0) {
            pagine[indice].stato = nuovoStato
            notifyItemChanged(indice)
        }
    }

    fun aggiornaUri(pagina: Pagina, nuovoUri: Uri) {
        val indice = pagine.indexOf(pagina)
        if (indice >= 0) {
            pagine[indice].uri = nuovoUri
            notifyItemChanged(indice)
        }
    }
}
