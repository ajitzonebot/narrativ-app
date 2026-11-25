package com.narrativ.app

import android.content.Context
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.serializer
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

const val REPO = "ajitzonebot/Narrativ"
const val RAW = "https://raw.githubusercontent.com/$REPO/main/docs"

val json = Json { ignoreUnknownKeys = true; coerceInputValues = true; explicitNulls = false; isLenient = true }

/**
 * Data comes from the Narrativ API (Cloudflare Worker that reads the private repo) when BuildConfig.API_URL is set,
 * otherwise from the public repo. Everything is cached on the phone for offline use.
 *
 * Speed (load latency audit): each file is also kept in memory (text plus its decoded copies, bounded LRU shared by every
 * Repo instance), concurrent downloads of one file share a single request, and the phone copy's ETag is sent as
 * If-None-Match so an unchanged file comes back as a body-less 304. Screens use [cacheFirst]: the memory / phone copy
 * at once, then the network copy only if it differs.
 */
class Repo(private val ctx: Context) {
    private fun cacheFile(path: String) = File(ctx.filesDir, "cache_" + path.replace('/', '_'))
    /** ETag of the phone copy, beside it; only ever describes the body currently in [cacheFile]. */
    private fun tagFile(f: File) = File(f.parentFile, f.name + ".etag")
    private val api = BuildConfig.API_URL.trimEnd('/')

    private fun open(url: String, etag: String? = null): HttpURLConnection = (URL(url).openConnection() as HttpURLConnection).apply {
        connectTimeout = 15000; readTimeout = 30000
        setRequestProperty("Cache-Control", "no-cache")
        if (etag != null) setRequestProperty("If-None-Match", etag)
        if (api.isNotEmpty() && url.startsWith(api)) setRequestProperty("X-App-Key", KeyGate.header())
    }

    /** Phone copy of [path] (also put in memory), or null. Blocking: call on IO. */
    private fun readDisk(path: String): String? {
        val f = cacheFile(path)
        if (!f.exists()) return null
        val t = tagFile(f)
        fun tag() = runCatching { if (t.exists()) t.readText().trim() else null }.getOrNull()?.takeIf { it.isNotEmpty() }
        val before = tag()
        val body = runCatching { f.readText() }.getOrNull() ?: return null
        // the tag read before and after the body agree: no download replaced the file in between, so it describes this body
        memPut(path, body, net = false, etag = before?.takeIf { it == tag() })
        return body
    }

    private fun writeDisk(path: String, body: String, etag: String?) {
        val f = cacheFile(path); val t = tagFile(f)
        runCatching {
            t.delete()  // a crash before the new tag is written leaves no tag (full download next time), never a wrong one
            // write beside, then rename: a download cut short never leaves a half-written cache file
            val tmp = File(f.parentFile, f.name + "." + System.nanoTime() + ".tmp")
            tmp.writeText(body)
            if (!tmp.renameTo(f)) { f.delete(); tmp.renameTo(f) }
            if (!etag.isNullOrBlank()) {
                val tt = File(t.parentFile, t.name + "." + System.nanoTime() + ".tmp")
                tt.writeText(etag)
                if (!tt.renameTo(t)) { t.delete(); tt.renameTo(t) }
            }
        }
    }

    /** Memory copy, else the phone copy; never the network. */
    suspend fun local(path: String): String? = memText(path) ?: withContext(Dispatchers.IO) { readDisk(path) }

    /** Network (sent with the phone copy's ETag; 304 = the phone copy is current), else the phone copy. Blocking: call on IO. */
    private fun fetch(path: String): Pair<String, Boolean>? {
        val f = cacheFile(path)
        val tag = if (f.exists()) runCatching { tagFile(f).readText().trim() }.getOrNull()?.takeIf { it.isNotEmpty() } else null
        val urls = buildList {
            if (api.isNotEmpty()) add("$api/data/$path")
            add("$RAW/$path?t=${System.currentTimeMillis() / 60000}")
        }
        for (u in urls) {
            try {
                var c = open(u, tag)
                var code = c.responseCode
                if (code == 304 && tag != null) {
                    runCatching { c.inputStream.close() }
                    val body = memText(path, tag) ?: run { readDisk(path); memText(path, tag) }
                    if (body != null) {
                        memPut(path, body, net = true, etag = tag)
                        return body to true
                    }
                    c = open(u); code = c.responseCode  // the phone copy changed meanwhile: ask for the whole file
                }
                // A refused key (wrong, or changed on the server): ask for it again instead of showing old data quietly.
                if (code == 401 && api.isNotEmpty() && u.startsWith(api)) KeyGate.rejected = true
                if (code == 200) {
                    val body = c.inputStream.bufferedReader().use { it.readText() }
                    val et = c.getHeaderField("ETag")
                    writeDisk(path, body, et)
                    memPut(path, body, net = true, etag = et)
                    return body to true
                }
            } catch (_: Exception) { }
        }
        return (memText(path) ?: readDisk(path))?.let { it to false }
    }

    /** [fetch], with concurrent calls for one path sharing a single request (startup, Home and a sheet often ask together). */
    private suspend fun fetchShared(path: String): Pair<String, Boolean>? {
        val d = synchronized(inflight) {
            inflight[path]?.takeIf { it.isActive } ?: io.async { runCatching { fetch(path) }.getOrNull() }.also { inflight[path] = it }
        }
        try {
            return d.await()
        } finally {
            synchronized(inflight) { if (inflight[path] === d && d.isCompleted) inflight.remove(path) }
        }
    }

    /** Text of [path] and whether it came from the network (true) or only from the phone cache (false); null when neither has it. */
    suspend fun textSrc(path: String, fresh: Boolean = true): Pair<String, Boolean>? =
        if (fresh) fetchShared(path) else local(path)?.let { it to false }

    suspend fun text(path: String, fresh: Boolean = true): String? = textSrc(path, fresh)?.first

    /** A decoded file plus where it came from ([net] false = phone cache, i.e. possibly old). */
    class Loaded<T>(val value: T, val net: Boolean)

    /** Decodes on a background thread (picks.json is 1.3 MB); the decoded copy is reused while the text is unchanged. */
    suspend inline fun <reified T : Any> getSrc(path: String, fresh: Boolean = true): Loaded<T>? {
        val (body, net) = textSrc(path, fresh) ?: return null
        val v = decodeOff<T>(path, body) ?: return null
        return Loaded(v, net)
    }

    suspend inline fun <reified T : Any> get(path: String, fresh: Boolean = true): T? = getSrc<T>(path, fresh)?.value

    suspend inline fun <reified T : Any> decodeOff(path: String, body: String): T? {
        val ser = serializer<T>()
        return decodeBy(path, ser.descriptor.serialName, body) { json.decodeFromString(ser, it) } as? T
    }

    /** Decoded [body] of [path] under [key] (the type), from memory when this exact text was decoded before; else decoded off Main. */
    suspend fun decodeBy(path: String, key: String, body: String, decode: (String) -> Any?): Any? = withContext(Dispatchers.Default) {
        memoGet(path, key, body) ?: runCatching { decode(body) }.getOrNull()?.also { memoPut(path, key, body, it) }
    }

    /**
     * Cache-first read for screens: [emit] gets the memory or phone copy at once, then the network copy when it differs
     * (the network is not asked again within [RECHECK_MS] of the last check). emit(null) only when no copy exists anywhere,
     * so callers keep their "loading" / "offline" states. [emit] runs in the caller's context.
     */
    @Suppress("UNCHECKED_CAST")
    suspend fun <T : Any> cacheFirstBy(path: String, key: String, decode: (String) -> T?, emit: (T?) -> Unit) {
        var shown: Any? = null
        local(path)?.let { body -> decodeBy(path, key, body, decode)?.let { shown = it; emit(it as T) } }
        if (shown != null && checkedRecently(path)) return
        val body = fetchShared(path)?.first
        val v = body?.let { decodeBy(path, key, it, decode) }
        if (v == null) { if (shown == null) emit(null); return }
        if (v !== shown) emit(v as T)  // same text gives the same decoded instance
    }

    suspend inline fun <reified T : Any> cacheFirst(path: String, noinline emit: (T?) -> Unit) {
        val ser = serializer<T>()
        cacheFirstBy(path, ser.descriptor.serialName, { json.decodeFromString(ser, it) }, emit)
    }

    /** The decoded copy already in memory (no I/O, safe on Main): the first frame of a screen opened before shows data, not placeholders. */
    inline fun <reified T : Any> peek(path: String): T? = memoPeek(path, serializer<T>().descriptor.serialName) as? T

    /** GET a small JSON object from the API (not cached), e.g. feedback/stats. */
    suspend fun apiGet(endpoint: String): JsonObject? = withContext(Dispatchers.IO) {
        if (api.isEmpty()) return@withContext null
        try {
            val c = open("$api/$endpoint")
            if (c.responseCode != 200) return@withContext null
            runCatching { json.parseToJsonElement(c.inputStream.bufferedReader().use { it.readText() }) as JsonObject }.getOrNull()
        } catch (e: Exception) { null }
    }

    /** POST to the API (feedback, scan). Returns the GitHub issue number or an error message. */
    suspend fun post(endpoint: String, body: JsonObject): Result<Int> = withContext(Dispatchers.IO) {
        if (api.isEmpty()) return@withContext Result.failure(Exception("The Narrativ server is not set up yet"))
        try {
            val c = open("$api/$endpoint")
            c.requestMethod = "POST"; c.doOutput = true
            c.setRequestProperty("Content-Type", "application/json")
            c.outputStream.use { it.write(body.toString().toByteArray()) }
            val code = c.responseCode
            val txt = (if (code in 200..299) c.inputStream else c.errorStream)?.bufferedReader()?.use { it.readText() } ?: ""
            val o = runCatching { json.parseToJsonElement(txt) as JsonObject }.getOrNull()
            if (code in 200..299) Result.success(o?.get("number")?.jsonPrimitive?.content?.toIntOrNull() ?: 0)
            else Result.failure(Exception(o?.get("error")?.jsonPrimitive?.content ?: "HTTP $code"))
        } catch (e: Exception) {
            Result.failure(Exception("No connection"))
        }
    }

    companion object {
        fun enc(s: String): String = URLEncoder.encode(s, "UTF-8")

        /** One path segment (a stock symbol such as M&M.NS) made safe for a URL; the phone cache file name is made from the same text. */
        fun seg(s: String): String = URLEncoder.encode(s, "UTF-8").replace("+", "%20")

        /** Screens do not re-ask the network for a file checked this recently (AppState.load always re-checks). */
        const val RECHECK_MS = 60_000L
        /** Memory budget, in characters of file text (decoded copies are of similar size): picks, research, memory and the rest fit. */
        const val MEM_BUDGET = 8_000_000L

        private val io = CoroutineScope(SupervisorJob() + Dispatchers.IO)
        private val inflight = HashMap<String, Deferred<Pair<String, Boolean>?>>()

        /** One file in memory: its text, ETag, when the network last confirmed it (0 = phone copy only) and decoded copies by type. */
        private class Mem(val body: String, @Volatile var etag: String?, @Volatile var netAt: Long) {
            val values = java.util.concurrent.ConcurrentHashMap<String, Any>()
        }
        private val mem = object : LinkedHashMap<String, Mem>(64, 0.75f, true) {}
        private var memChars = 0L

        /** Text in memory; with [etag], only when it is that version. */
        fun memText(path: String, etag: String? = null): String? = synchronized(mem) {
            mem[path]?.takeIf { etag == null || it.etag == etag }?.body
        }

        /** Network copies replace what is held; a phone copy is only added when nothing is held (it may be older). */
        fun memPut(path: String, body: String, net: Boolean, etag: String? = null) = synchronized(mem) {
            val old = mem[path]
            if (old != null && (old.body === body || old.body == body)) {
                if (net) { old.netAt = System.currentTimeMillis(); old.etag = etag ?: old.etag }
                else if (old.etag == null) old.etag = etag
                return@synchronized
            }
            if (old != null && !net) return@synchronized
            old?.let { memChars -= it.body.length }
            mem[path] = Mem(body, etag, if (net) System.currentTimeMillis() else 0L)
            memChars += body.length
            trim()
        }

        private fun trim() {
            val it = mem.entries.iterator()
            while (memChars > MEM_BUDGET && mem.size > 1 && it.hasNext()) {
                val e = it.next(); memChars -= e.value.body.length; it.remove()
            }
        }

        fun checkedRecently(path: String): Boolean = synchronized(mem) {
            mem[path]?.let { it.netAt > 0 && System.currentTimeMillis() - it.netAt < RECHECK_MS } ?: false
        }

        fun memoGet(path: String, key: String, body: String): Any? {
            val m = synchronized(mem) { mem[path] } ?: return null
            return if (m.body === body || m.body == body) m.values[key] else null
        }

        /** Keeps a decoded copy only beside the same text (a slower decode of older text never replaces newer text). */
        fun memoPut(path: String, key: String, body: String, v: Any) {
            val m = synchronized(mem) {
                mem[path] ?: run { memPut(path, body, net = false); mem[path] }
            } ?: return
            if (m.body === body || m.body == body) m.values[key] = v
        }

        fun memoPeek(path: String, key: String): Any? = synchronized(mem) { mem[path] }?.values?.get(key)

        /** Tests only. */
        internal fun memClear() = synchronized(mem) { mem.clear(); memChars = 0 }
    }
}
