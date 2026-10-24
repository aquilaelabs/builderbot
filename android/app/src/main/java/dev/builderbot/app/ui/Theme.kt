// The app's colors, as the dashboard's schemes: the same twelve the
// gear offers there, by the same names and the same hexes, both halves (the
// design record's themes, which docs/design-language.md is written from;
// tools/app-schemes.py writes the table below from it), chosen under More
// and kept on the device. Every screen reads the tokens below,
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

// One half of a scheme: its nine named colors and the two it makes. The
// dark half darkens the panel for the sunk ground and fills an accent
// surface with the second color darkened (capped, so ink stays readable);
// the light half darkens the panel less and tints it with the second color,
// the ink on it, as the stylesheet's light half does (R216).
class Half(bg: Long, panel: Long, ink: Long, dim: Long, line: Long,
           accent: Long, warn: Long, bad: Long, note: Long, val light: Boolean = false) {
    val bg = Color(bg)
    val panel = Color(panel)
    val ink = Color(ink)
    val dim = Color(dim)
    val line = Color(line)
    val accent = Color(accent)
    val warn = Color(warn)
    val bad = Color(bad)
    val note = Color(note)
    val sunk = lerp(this.panel, Color.Black, if (light) .05f else .12f)
    val accentDeep = if (light) lerp(this.panel, this.note, .16f) else deep(this.note)
}

class Scheme(val name: String, val dark: Half, val light: Half)

private fun deep(c: Color): Color {
    val d = lerp(c, Color.Black, .40f)
    val light = 0.2126f * d.red + 0.7152f * d.green + 0.0722f * d.blue
    val cap = .22f
    return if (light <= cap) d else Color(d.red * cap / light, d.green * cap / light, d.blue * cap / light)
}

object Schemes {
    val all = listOf(
        Scheme("Default",
            Half(0xFF1A1F26, 0xFF212730, 0xFFE6EDF3, 0xFF9FA9B4, 0xFF4D5C6F, 0xFF3FB950, 0xFFD29922, 0xFFF8524A, 0xFF58A6FF),
            Half(0xFFF1F4F7, 0xFFFCFEFF, 0xFF242729, 0xFF5E646A, 0xFFC9D2DD, 0xFF007C05, 0xFF996200, 0xFFC3131B, 0xFF0069E0, light = true)),
        Scheme("Abyss",
            Half(0xFF111D20, 0xFF18262A, 0xFFDCECEE, 0xFF93A9AC, 0xFF3E5E66, 0xFF2FB8C6, 0xFFD7AB4C, 0xFFEF6A63, 0xFFE391D9),
            Half(0xFFEFF5F6, 0xFFFBFEFF, 0xFF212829, 0xFF5A6667, 0xFFC3D5D9, 0xFF007480, 0xFF906700, 0xFFB53433, 0xFFBB30AA, light = true)),
        Scheme("Carbon",
            Half(0xFF141417, 0xFF1C1C1F, 0xFFE8E8EA, 0xFF9D9DA4, 0xFF53535B, 0xFFE64E53, 0xFFD9A441, 0xFFFF6B6B, 0xFF3CC6B5),
            Half(0xFFF3F3F5, 0xFFFDFDFE, 0xFF262627, 0xFF636367, 0xFFD0D0D5, 0xFFB6192C, 0xFF905E00, 0xFFBB2933, 0xFF22776C, light = true)),
        Scheme("Ember",
            Half(0xFF1F1814, 0xFF271F1A, 0xFFF0E4D8, 0xFFAF9F90, 0xFF67533E, 0xFFF0873F, 0xFFE8BB50, 0xFFEF5F52, 0xFF4CC9D0),
            Half(0xFFF6F3F1, 0xFFFFFDFB, 0xFF2B2520, 0xFF6A6159, 0xFFDBCFC3, 0xFFA34100, 0xFF8B6100, 0xFFBA2C25, 0xFF21787D, light = true)),
        Scheme("Ice",
            Half(0xFF151C21, 0xFF1C252C, 0xFFE3EDF5, 0xFF9AA8AE, 0xFF465B6C, 0xFF58C7E8, 0xFFD3AB52, 0xFFEE6A68, 0xFFB8A2FF),
            Half(0xFFF0F4F6, 0xFFFBFEFF, 0xFF23272B, 0xFF5D6568, 0xFFC7D3DD, 0xFF00708F, 0xFF886200, 0xFFB43439, 0xFF7347FF, light = true)),
        Scheme("Moss",
            Half(0xFF161F1B, 0xFF1D2920, 0xFFDFE9DF, 0xFF9DABA0, 0xFF48604F, 0xFF63C98A, 0xFFD6AD4E, 0xFFE8695F, 0xFFB49CF0),
            Half(0xFFF0F5F3, 0xFFFBFEFC, 0xFF232823, 0xFF5E6660, 0xFFC8D5CB, 0xFF00783F, 0xFF8E6800, 0xFFB33833, 0xFF794EE4, light = true)),
        Scheme("Nocturne",
            Half(0xFF181825, 0xFF202031, 0xFFE4E2F5, 0xFFA2A0C1, 0xFF53537B, 0xFF9D7CFF, 0xFFE0B24D, 0xFFF2637B, 0xFF5FDCB4),
            Half(0xFFF2F3F9, 0xFFFDFDFF, 0xFF26252E, 0xFF626173, 0xFFCECFE6, 0xFF6A44C2, 0xFF916600, 0xFFB72B4C, 0xFF1B795B, light = true)),
        Scheme("Nostromo",
            Half(0xFF0B0F13, 0xFF121920, 0xFFD3DBE3, 0xFF8B98A5, 0xFF33404C, 0xFFFFB000, 0xFFE0913A, 0xFFFF5F45, 0xFF6FA8DC),
            Half(0xFFE4E5E2, 0xFFF6F6F3, 0xFF232628, 0xFF595D60, 0xFFBFC1BC, 0xFFB23A0A, 0xFF8B6100, 0xFFA8002A, 0xFF3D7322, light = true)),
        Scheme("Plum",
            Half(0xFF1E1623, 0xFF261D2D, 0xFFEDDFF2, 0xFFAE9CB7, 0xFF654D73, 0xFFC874D8, 0xFFDFAE52, 0xFFEE6183, 0xFF7DD8A0),
            Half(0xFFF6F2F8, 0xFFFFFCFF, 0xFF2A242C, 0xFF695F6E, 0xFFD9CBE1, 0xFF8C3A9B, 0xFF936500, 0xFFB62B55, 0xFF247B45, light = true)),
        Scheme("Rust",
            Half(0xFF1E1614, 0xFF261D1A, 0xFFECDEDB, 0xFFAE9D99, 0xFF6A4E4A, 0xFFCF6A4C, 0xFFD9A441, 0xFFE8544A, 0xFF6CC2A8),
            Half(0xFFF7F2F1, 0xFFFFFDFC, 0xFF2B2523, 0xFF6A615F, 0xFFDDCDCA, 0xFFA14123, 0xFF905E00, 0xFFBC2825, 0xFF247B60, light = true)),
        Scheme("Sepia",
            Half(0xFF1F1B14, 0xFF272219, 0xFFECE0CB, 0xFFB0A28C, 0xFF63563E, 0xFFD3A94F, 0xFFE3C069, 0xFFE0705F, 0xFF5FBDB0),
            Half(0xFFF5F3F0, 0xFFFFFDFB, 0xFF2B261C, 0xFF6A6256, 0xFFD7D0C3, 0xFF835C00, 0xFF8A6900, 0xFFAC4133, 0xFF22776B, light = true)),
        Scheme("Slate",
            Half(0xFF181C23, 0xFF1F242D, 0xFFDFE5EC, 0xFF9FA6AE, 0xFF4F5A68, 0xFF6EA8FE, 0xFFD9A441, 0xFFEF6F6C, 0xFFA6D96A),
            Half(0xFFF1F3F7, 0xFFFCFDFF, 0xFF24272A, 0xFF606468, 0xFFCBD2DA, 0xFF2A61B1, 0xFF905E00, 0xFFB2373A, 0xFF4E761E, light = true)),
    )
    var current by mutableStateOf(all[0])
        private set
    // Dark, Light or System, as the dashboard's gear offers beside the scheme;
    // System follows the phone, told by the theme as it composes.
    val modes = listOf("Dark", "Light", "System")
    var mode by mutableStateOf("Dark")
        private set
    var systemDark by mutableStateOf(true)
    val half: Half get() = if (mode == "Light" || (mode == "System" && !systemDark)) current.light else current.dark

    // A kept "Fern" is Nostromo, whose colors it was.
    fun pick(name: String) {
        val want = if (name == "Fern") "Nostromo" else name
        current = all.firstOrNull { it.name == want } ?: all[0]
    }

    fun pickMode(name: String) {
        mode = if (name in modes) name else "Dark"
    }
}

// ---- the tokens, read from the scheme in front ------------------------------
val Bg: Color get() = Schemes.half.bg
val Panel: Color get() = Schemes.half.panel
val Sunk: Color get() = Schemes.half.sunk
val Line: Color get() = Schemes.half.line
val Ink: Color get() = Schemes.half.ink
val Dim: Color get() = Schemes.half.dim
val Accent: Color get() = Schemes.half.accent      // the scheme's one color
val AccentDeep: Color get() = Schemes.half.accentDeep    // what a filled accent surface is
val Warn: Color get() = Schemes.half.warn
val Bad: Color get() = Schemes.half.bad
val Note: Color get() = Schemes.half.note
val Ok: Color get() = Accent

// The badge palette, the same on every scheme (the design's rule badges).
val Purple = Color(0xFFB79AE0)
val Green2 = Color(0xFF7FC08A)
val Blue2 = Color(0xFF77B7E8)
val Gold = Color(0xFFD8B25C)
val Red2 = Color(0xFFE0796F)
