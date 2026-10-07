package it.scansionebrother.telefono

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color

private const val SEPARATORE_PX = 12

/** Mette fronte e retro di un documento in un'unica immagine, uno sopra
 * l'altro (stessa larghezza, con una sottile riga di separazione bianca),
 * cosi' il programma riceve una sola pagina per il documento invece di
 * doverle abbinare a mano. */
fun componiFronteRetro(fronte: Bitmap, retro: Bitmap): Bitmap {
    val larghezza = maxOf(fronte.width, retro.width)
    val f = scalaAllaLarghezza(fronte, larghezza)
    val r = scalaAllaLarghezza(retro, larghezza)
    val risultato = Bitmap.createBitmap(
        larghezza, f.height + SEPARATORE_PX + r.height, Bitmap.Config.ARGB_8888)
    val canvas = Canvas(risultato)
    canvas.drawColor(Color.WHITE)
    canvas.drawBitmap(f, 0f, 0f, null)
    canvas.drawBitmap(r, 0f, (f.height + SEPARATORE_PX).toFloat(), null)
    return risultato
}

private fun scalaAllaLarghezza(bitmap: Bitmap, larghezza: Int): Bitmap {
    if (bitmap.width == larghezza) return bitmap
    val altezza = (bitmap.height.toFloat() * larghezza / bitmap.width).toInt()
    return Bitmap.createScaledBitmap(bitmap, larghezza, altezza, true)
}
