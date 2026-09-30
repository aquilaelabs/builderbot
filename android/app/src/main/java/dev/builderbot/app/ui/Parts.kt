// The app's look, in one place: the few shapes every screen is built from,
// painted in the dashboard's own tokens (Theme.kt, the scheme in front).
// A pill, a tag, a panel with a hairline and an optional color bar, a
// section head in the card-title voice, and the robot mark. The dashboard's
// design language (docs/design-language.md) is the reference: a filled
// accent surface is the deep accent with ink on it, a hairline is the line
// token, corners are 8dp for a surface and 6dp for a control, and severity
// colors agree with the site: high red, medium amber, low blue.
package dev.builderbot.app.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

// ---- the tokens ---------------------------------------------------------------
// In Theme.kt, read from the scheme in front: the app wears the dashboard's
// thirteen schemes now, not the default one alone.

// A project's color, the eight the dashboard offers, by the name it stores.
private val TONES = mapOf(
    "red" to Color(0xFFE5534B), "orange" to Color(0xFFE8883A), "yellow" to Color(0xFFD4B33A),
    "green" to Color(0xFF57AB5A), "teal" to Color(0xFF39B5B0), "blue" to Color(0xFF539BF5),
    "violet" to Color(0xFFA371F7), "pink" to Color(0xFFE0669E))
fun projectTone(name: String): Color? = TONES[name]
val TONE_NAMES: List<String> get() = TONES.keys.toList()

// Severity and level agree with the site: error and high are red, warning
// and medium amber, note and low blue.
fun severityColor(s: String): Color = when (s) { "high" -> Bad; "medium" -> Warn; else -> Note }

// ---- the pieces ---------------------------------------------------------------

/** A pill: the site's badge, a hairline box in the tag voice. The color is
 *  the text and the edge; the ground stays the surface's. */
@Composable
fun Pill(text: String, color: Color = Dim, modifier: Modifier = Modifier) {
    Text(text.uppercase(), color = color, fontSize = 10.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.6.sp,
        lineHeight = 12.sp,
        modifier = modifier
            .border(1.dp, color.copy(alpha = .55f), RoundedCornerShape(99.dp))
            .padding(horizontal = 7.dp, vertical = 2.dp))
}

/** A tag: a row's number (R12, B7) in the data voice, dim when the row is
 *  done, so the eye finds the words and the number stays findable. */
@Composable
fun Tag(text: String, color: Color = Ink, modifier: Modifier = Modifier) {
    Text(text, color = color, fontFamily = FontFamily.Monospace, fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
        modifier = modifier
            .background(Sunk, RoundedCornerShape(4.dp))
            .padding(horizontal = 6.dp, vertical = 2.dp))
}

/** A panel: the site's card. A hairline in the line token on the panel
 *  color, 8dp corners, and, where the thing has a color of its own (a
 *  project, a kind of ask), a 3dp bar down the left, the way the notebook
 *  tab wears it. */
@Composable
fun Panel(modifier: Modifier = Modifier, bar: Color? = null, content: @Composable () -> Unit) {
    // IntrinsicSize.Min: the bar fills the row's height, and a row's height
    // is only known to its children once it is measured to its content.
    Row(modifier
        .border(1.dp, Line, RoundedCornerShape(8.dp))
        .background(Panel, RoundedCornerShape(8.dp))
        .height(IntrinsicSize.Min)) {
        if (bar != null) Box(Modifier.width(3.dp).fillMaxHeight().background(bar, RoundedCornerShape(topStart = 8.dp, bottomStart = 8.dp)))
        Column(Modifier.padding(12.dp)) { content() }
    }
}

/** A quiet button: words alone, in the scheme's accent. Material paints
 *  one in its primary, which here is the deep accent a filled surface
 *  wears, and that on the page's ground is too dark to read; so every
 *  screen takes its buttons from here. */
@Composable
fun TextButton(onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true,
               content: @Composable androidx.compose.foundation.layout.RowScope.() -> Unit) {
    androidx.compose.material3.TextButton(onClick = onClick, modifier = modifier, enabled = enabled,
        colors = androidx.compose.material3.ButtonDefaults.textButtonColors(contentColor = Accent),
        content = content)
}

/** A control: the site's button, ink on the ground with a hairline. */
@Composable
fun OutlinedButton(onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true,
                   content: @Composable androidx.compose.foundation.layout.RowScope.() -> Unit) {
    androidx.compose.material3.OutlinedButton(onClick = onClick, modifier = modifier, enabled = enabled,
        shape = RoundedCornerShape(6.dp),
        border = androidx.compose.foundation.BorderStroke(1.dp, Line),
        colors = androidx.compose.material3.ButtonDefaults.outlinedButtonColors(contentColor = Ink),
        content = content)
}

/** A section head, in the card title's voice: small, uppercase, spaced. */
@Composable
fun SectionHead(text: String, inset: Boolean = true) {
    Text(text.uppercase(), color = Dim, fontSize = 11.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.6.sp,
        modifier = Modifier.padding(if (inset) 16.dp else 0.dp, 14.dp, if (inset) 16.dp else 0.dp, 4.dp))
}

/** The one line between rows: the line token, one pixel. */
@Composable
fun Hairline() { HorizontalDivider(thickness = 1.dp, color = Line) }

/** A small filled dot beside a state word. */
@Composable
fun Dot(color: Color) {
    Box(Modifier.size(8.dp).background(color, RoundedCornerShape(99.dp)))
    Spacer(Modifier.width(6.dp))
}

/** The dashboard's mark (index.html's #bb-mask, static/favicon.svg): a
 *  rounded head, an antenna, two eyes and a mouth cut out of it. Drawn in
 *  code rather than shipped as an image, the way the site draws it. */
@Composable
fun Mark(size: Dp = 22.dp, color: Color = Accent) {
    Canvas(Modifier.size(size)) {
        val u = this.size.width / 32f
        val bg = Bg
        drawRoundRect(color, Offset(4 * u, 8.5f * u), Size(24 * u, 17 * u), CornerRadius(5.5f * u))
        drawRoundRect(color, Offset(15 * u, 3.5f * u), Size(2 * u, 6 * u), CornerRadius(u))
        drawCircle(color, 2.3f * u, Offset(16 * u, 3 * u))
        drawCircle(bg, 2.1f * u, Offset(11.4f * u, 15.4f * u))
        drawCircle(bg, 2.1f * u, Offset(20.6f * u, 15.4f * u))
        drawRoundRect(bg, Offset(10.6f * u, 19.6f * u), Size(10.8f * u, 2.6f * u), CornerRadius(1.3f * u))
    }
}
