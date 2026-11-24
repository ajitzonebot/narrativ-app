package com.narrativ.app

import android.content.Context
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.URL

/**
 * The key the app sends to the Narrativ API (X-App-Key). Release builds carry no key: the APK is public, so the owner
 * types the key once and it stays on the phone. Debug builds fall back to the dummy key in BuildConfig.
 */
object KeyGate {
    private const val PREF = "appKey"
    /** The key saved on this phone ("" = none yet). */
    var key by mutableStateOf("")
    /** The API refused the key (wrong, or changed on the server). */
    var rejected by mutableStateOf(false)
    /** Settings > Access key > Change. */
    var editing by mutableStateOf(false)

    /** True when the key screen must cover the app. */
    val showing: Boolean get() = (BuildConfig.APP_KEY.isBlank() && key.isBlank()) || rejected || editing

    fun init(ctx: Context) {
        key = ctx.getSharedPreferences("narrativ", Context.MODE_PRIVATE).getString(PREF, "") ?: ""
    }

    fun header(): String = key.ifBlank { BuildConfig.APP_KEY }

    fun save(ctx: Context, k: String) {
        ctx.getSharedPreferences("narrativ", Context.MODE_PRIVATE).edit().putString(PREF, k).apply()
        key = k; rejected = false; editing = false
    }

    /** HTTP status of a small keyed request with [k]: 200 = good, 401 = wrong key, -1 = no connection. */
    suspend fun check(k: String): Int = withContext(Dispatchers.IO) {
        val api = BuildConfig.API_URL.trimEnd('/')
        if (api.isEmpty()) return@withContext 200
        try {
            val c = URL("$api/data/app/version.json").openConnection() as HttpURLConnection
            c.connectTimeout = 15000; c.readTimeout = 15000
            c.setRequestProperty("X-App-Key", k)
            c.setRequestProperty("Cache-Control", "no-cache")
            c.responseCode.also { c.disconnect() }
        } catch (e: Exception) { -1 }
    }
}

/** Covers the app until a working access key is saved. All a stranger with the APK ever sees. */
@Composable
fun KeyScreen(onDone: () -> Unit) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var text by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var err by remember {
        mutableStateOf(if (KeyGate.rejected && KeyGate.key.isNotBlank()) "That key didn't work. Check it and try again." else null)
    }
    val canCancel = KeyGate.editing && !KeyGate.rejected
    BackHandler(enabled = canCancel) { KeyGate.editing = false }

    Column(Modifier.fillMaxSize().background(C.bg).systemBarsPadding().imePadding().padding(horizontal = 20.dp, vertical = 16.dp)) {
        Box(Modifier.fillMaxWidth().height(40.dp), contentAlignment = Alignment.CenterEnd) {
            if (canCancel) T("Cancel", 15.sp, C.blue, modifier = Modifier.clip(RoundedCornerShape(12.dp)).clickable { KeyGate.editing = false }
                .padding(horizontal = 8.dp, vertical = 6.dp))
        }
        Spacer(Modifier.height(24.dp))
        AppLogo(46.dp)
        Spacer(Modifier.height(16.dp))
        T("Enter your access key", 24.sp, weight = FontWeight.Bold)
        T("Narrativ is private. You only need the key once on this phone.", 14.sp, C.dim, lineHeight = 20.sp,
            modifier = Modifier.padding(top = 6.dp))
        Box(Modifier.padding(top = 20.dp).fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(Color(0xFF0B0C0D))
            .border(1.dp, if (err != null) C.red else C.teal.copy(alpha = 0.33f), RoundedCornerShape(16.dp)).padding(14.dp)) {
            BasicTextField(text, { text = it.trim(); err = null }, singleLine = true,
                textStyle = TextStyle(color = C.white, fontSize = 16.sp, letterSpacing = 1.sp), cursorBrush = SolidColor(C.blue),
                visualTransformation = PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                modifier = Modifier.fillMaxWidth(),
                decorationBox = { inner -> if (text.isEmpty()) T("Paste your key", 16.sp, C.dim); inner() })
        }
        err?.let { T(it, 13.sp, C.red, modifier = Modifier.padding(top = 8.dp)) }
        Spacer(Modifier.weight(1f))
        val ready = text.isNotBlank() && !busy
        Box(Modifier.fillMaxWidth().height(50.dp).clip(RoundedCornerShape(25.dp)).background(if (ready) C.teal else C.chip)
            .clickable(enabled = ready) {
                busy = true
                scope.launch {
                    val code = KeyGate.check(text)
                    busy = false
                    when (code) {
                        in 200..299 -> { KeyGate.save(ctx, text); onDone() }
                        401, 403 -> err = "That key didn't work. Check it and try again."
                        else -> err = "Couldn't reach Narrativ. Check your internet and try again."
                    }
                }
            }, contentAlignment = Alignment.Center) {
            T(if (busy) "Checking…" else "Open Narrativ", 16.sp, if (ready) Color.White else C.dim, FontWeight.SemiBold)
        }
    }
}
