package com.narrativ.app

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonPrimitive
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
 */
class Repo(private val ctx: Context) {
    private fun cacheFile(path: String) = File(ctx.filesDir, "cache_" + path.replace('/', '_'))
    private val api = BuildConfig.API_URL.trimEnd('/')

    private fun open(url: String): HttpURLConnection = (URL(url).openConnection() as HttpURLConnection).apply {
        connectTimeout = 15000; readTimeout = 30000
        setRequestProperty("Cache-Control", "no-cache")
        if (api.isNotEmpty() && url.startsWith(api)) setRequestProperty("X-App-Key", KeyGate.header())
    }

    /** Text of [path] and whether it came from the network (true) or only from the phone cache (false); null when neither has it. */
    suspend fun textSrc(path: String, fresh: Boolean = true): Pair<String, Boolean>? = withContext(Dispatchers.IO) {
        val f = cacheFile(path)
        if (fresh) {
            val urls = buildList {
                if (api.isNotEmpty()) add("$api/data/$path")
                add("$RAW/$path?t=${System.currentTimeMillis() / 60000}")
            }
            for (u in urls) {
                try {
                    val c = open(u)
                    // A refused key (wrong, or changed on the server): ask for it again instead of showing old data quietly.
                    if (c.responseCode == 401 && api.isNotEmpty() && u.startsWith(api)) KeyGate.rejected = true
                    if (c.responseCode == 200) {
                        val body = c.inputStream.bufferedReader().use { it.readText() }
                        // write beside, then rename: a download cut short never leaves a half-written cache file
                        runCatching {
                            val tmp = File(f.parentFile, f.name + "." + System.nanoTime() + ".tmp")
                            tmp.writeText(body)
                            if (!tmp.renameTo(f)) { f.delete(); tmp.renameTo(f) }
                        }
                        return@withContext body to true
                    }
                } catch (_: Exception) { }
            }
        }
        if (f.exists()) runCatching { f.readText() }.getOrNull()?.let { it to false } else null
    }

    suspend fun text(path: String, fresh: Boolean = true): String? = textSrc(path, fresh)?.first

    /** A decoded file plus where it came from ([net] false = phone cache, i.e. possibly old). */
    class Loaded<T>(val value: T, val net: Boolean)

    /** Decodes on a background thread (picks.json is 1.3 MB). With [memo] the last decoded result of [path] is reused when the text is unchanged. */
    suspend inline fun <reified T : Any> getSrc(path: String, fresh: Boolean = true, memo: Boolean = false): Loaded<T>? {
        val (body, net) = textSrc(path, fresh) ?: return null
        val v = decodeOff<T>(path, body, memo) ?: return null
        return Loaded(v, net)
    }

    suspend inline fun <reified T : Any> get(path: String, fresh: Boolean = true, memo: Boolean = false): T? =
        getSrc<T>(path, fresh, memo)?.value

    suspend inline fun <reified T : Any> decodeOff(path: String, body: String, memo: Boolean): T? = withContext(Dispatchers.Default) {
        if (memo) memoGet(path, body)?.let { if (it is T) return@withContext it }
        val v = runCatching { json.decodeFromString<T>(body) }.getOrNull()
        if (memo && v != null) memoPut(path, body, v)
        v
    }

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

        private val memoMap = java.util.concurrent.ConcurrentHashMap<String, Pair<String, Any>>()
        fun memoGet(path: String, body: String): Any? = memoMap[path]?.takeIf { it.first == body }?.second
        fun memoPut(path: String, body: String, v: Any) { memoMap[path] = body to v }
    }
}
