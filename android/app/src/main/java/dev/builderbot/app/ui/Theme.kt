// The app's colors, as the dashboard's schemes: the same twelve the
// gear offers there, by the same names and the same hexes (the design
// record's themes, which docs/design-language.md is written from), chosen
// under More and kept on the device. Every screen reads the tokens below,
// which read the scheme in front, so choosing one repaints the app.
//
// Two tokens are made rather than named, as the stylesheet makes them: the
// sunk ground is the panel darkened by 12%, and what a filled accent
// surface is, is the accent darkened by 40% with its lightness capped, so
// ink on it stays readable under the bright accents.
package dev.builderbot.app.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.lerp

class Scheme(val name: String, bg: Long, panel: Long, ink: Long, dim: Long, line: Long,
             accent: Long, warn: Long, bad: Long, note: Long) {
    val bg = Color(bg)
    val panel = Color(panel)
    val ink = Color(ink)
    val dim = Color(dim)
    val line = Color(line)
    val accent = Color(accent)
    val warn = Color(warn)
    val bad = Color(bad)
    val note = Color(note)
    val sunk = lerp(this.panel, Color.Black, .12f)
    val accentDeep = deep(this.accent)
}

private fun deep(c: Color): Color {
    val d = lerp(c, Color.Black, .40f)
    val light = 0.2126f * d.red + 0.7152f * d.green + 0.0722f * d.blue
    val cap = .22f
    return if (light <= cap) d else Color(d.red * cap / light, d.green * cap / light, d.blue * cap / light)
}

object Schemes {
    val all = listOf(
        Scheme("Default", 0xFF1A1F26, 0xFF212730, 0xFFE6EDF3, 0xFF9FA9B4, 0xFF4D5C6F, 0xFF3FB950, 0xFFD29922, 0xFFF8524A, 0xFF58A6FF),
        Scheme("Abyss", 0xFF111D20, 0xFF18262A, 0xFFDCECEE, 0xFF93A9AC, 0xFF3E5E66, 0xFF2FB8C6, 0xFFD7AB4C, 0xFFEF6A63, 0xFF6FB3E0),
        Scheme("Carbon", 0xFF141417, 0xFF1C1C1F, 0xFFE8E8EA, 0xFF9D9DA4, 0xFF53535B, 0xFFE64E53, 0xFFD9A441, 0xFFFF6B6B, 0xFF7AA2F7),
        Scheme("Ember", 0xFF1F1814, 0xFF271F1A, 0xFFF0E4D8, 0xFFAF9F90, 0xFF67533E, 0xFFF0873F, 0xFFE8BB50, 0xFFEF5F52, 0xFF8FB4D9),
        Scheme("Ice", 0xFF151C21, 0xFF1C252C, 0xFFE3EDF5, 0xFF9AA8AE, 0xFF465B6C, 0xFF58C7E8, 0xFFD3AB52, 0xFFEE6A68, 0xFF7CC0FF),
        Scheme("Moss", 0xFF161F1B, 0xFF1D2920, 0xFFDFE9DF, 0xFF9DABA0, 0xFF48604F, 0xFF63C98A, 0xFFD6AD4E, 0xFFE8695F, 0xFF74B3D8),
        Scheme("Nocturne", 0xFF181825, 0xFF202031, 0xFFE4E2F5, 0xFFA2A0C1, 0xFF53537B, 0xFF9D7CFF, 0xFFE0B24D, 0xFFF2637B, 0xFF7CB0FF),
        Scheme("Nostromo", 0xFF0B0F13, 0xFF121920, 0xFFD3DBE3, 0xFF8B98A5, 0xFF33404C, 0xFFFFB000, 0xFFE0913A, 0xFFFF5F45, 0xFF6FA8DC),
        Scheme("Plum", 0xFF1E1623, 0xFF261D2D, 0xFFEDDFF2, 0xFFAE9CB7, 0xFF654D73, 0xFFC874D8, 0xFFDFAE52, 0xFFEE6183, 0xFF83AEE8),
        Scheme("Rust", 0xFF1E1614, 0xFF261D1A, 0xFFECDEDB, 0xFFAE9D99, 0xFF6A4E4A, 0xFFCF6A4C, 0xFFD9A441, 0xFFE8544A, 0xFF7FA8C9),
        Scheme("Sepia", 0xFF1F1B14, 0xFF272219, 0xFFECE0CB, 0xFFB0A28C, 0xFF63563E, 0xFFD3A94F, 0xFFE3C069, 0xFFE0705F, 0xFF9DB98C),
        Scheme("Slate", 0xFF181C23, 0xFF1F242D, 0xFFDFE5EC, 0xFF9FA6AE, 0xFF4F5A68, 0xFF6EA8FE, 0xFFD9A441, 0xFFEF6F6C, 0xFF7FB8FF),
    )
    var current by mutableStateOf(all[0])
        private set

    // A kept "Fern" is Nostromo, whose colors it was.
    fun pick(name: String) {
        val want = if (name == "Fern") "Nostromo" else name
        current = all.firstOrNull { it.name == want } ?: all[0]
    }
}

// ---- the tokens, read from the scheme in front ------------------------------
val Bg: Color get() = Schemes.current.bg
val Panel: Color get() = Schemes.current.panel
val Sunk: Color get() = Schemes.current.sunk
val Line: Color get() = Schemes.current.line
val Ink: Color get() = Schemes.current.ink
val Dim: Color get() = Schemes.current.dim
val Accent: Color get() = Schemes.current.accent      // the scheme's one color
val AccentDeep: Color get() = Schemes.current.accentDeep    // what a filled accent surface is
val Warn: Color get() = Schemes.current.warn
val Bad: Color get() = Schemes.current.bad
val Note: Color get() = Schemes.current.note
val Ok: Color get() = Accent

// The badge palette, the same on every scheme (the design's rule badges).
val Purple = Color(0xFFB79AE0)
val Green2 = Color(0xFF7FC08A)
val Blue2 = Color(0xFF77B7E8)
val Gold = Color(0xFFD8B25C)
val Red2 = Color(0xFFE0796F)
