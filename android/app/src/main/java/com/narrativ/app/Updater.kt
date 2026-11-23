package com.narrativ.app

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

/** In-app update: download the release APK with progress, check it is complete, then hand it to the system installer. */
object Updater {
    private fun file(ctx: Context) = File(ctx.cacheDir, "updates").apply { mkdirs() }.resolve("narrativ-update.apk")

    /** Returns the downloaded file, or throws with a readable message. [onProgress] gets 0..1 (or -1 when the size is unknown).
     *  When [sha256] (hex, from version.json) is given the file must match it; without it only the size is checked. */
    suspend fun download(ctx: Context, url: String, sha256: String? = null, onProgress: (Float) -> Unit): File = withContext(Dispatchers.IO) {
        val out = file(ctx)
        out.delete()
        var u = url
        var c: HttpURLConnection
        var hops = 0
        while (true) {  // GitHub release links redirect to a storage host; follow by hand so https -> https always works
            c = (URL(u).openConnection() as HttpURLConnection).apply {
                connectTimeout = 20000; readTimeout = 60000; instanceFollowRedirects = false
                setRequestProperty("Accept", "application/octet-stream")
            }
            val code = c.responseCode
            if (code in 300..399 && hops < 5) { u = c.getHeaderField("Location") ?: break; c.disconnect(); hops++; continue }
            if (code != 200) throw Exception("Download failed (HTTP $code)")
            break
        }
        val total = c.contentLengthLong
        var got = 0L
        val md = java.security.MessageDigest.getInstance("SHA-256")
        c.inputStream.use { inp ->
            out.outputStream().use { o ->
                val buf = ByteArray(64 * 1024)
                while (true) {
                    val n = inp.read(buf)
                    if (n < 0) break
                    o.write(buf, 0, n)
                    md.update(buf, 0, n)
                    got += n
                    onProgress(if (total > 0) got.toFloat() / total else -1f)
                }
            }
        }
        c.disconnect()
        if (total > 0 && got != total) throw Exception("Download stopped early (${got / 1048576} of ${total / 1048576} MB). Try again.")
        if (got < 1_000_000) throw Exception("Downloaded file is too small to be the app. Try again.")
        val want = sha256?.trim()?.lowercase()?.takeIf { it.isNotEmpty() }
        if (want != null) {
            val have = md.digest().joinToString("") { "%02x".format(it) }
            if (have != want) { out.delete(); throw Exception("The downloaded file does not match the published checksum, so it was not installed. Try again.") }
        }
        out
    }

    /** True when Android allows this app to install updates; otherwise opens the setting for it. */
    fun canInstall(ctx: Context): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O || ctx.packageManager.canRequestPackageInstalls()) return true
        runCatching {
            ctx.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${ctx.packageName}"))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        }
        return false
    }

    fun install(ctx: Context, apk: File) {
        val uri = FileProvider.getUriForFile(ctx, "${ctx.packageName}.updates", apk)
        ctx.startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/vnd.android.package-archive")
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK))
    }
}
