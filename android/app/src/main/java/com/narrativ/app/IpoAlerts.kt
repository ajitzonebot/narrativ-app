package com.narrativ.app

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import java.time.Duration
import java.time.LocalTime
import java.time.ZoneId
import java.time.ZonedDateTime
import java.util.concurrent.TimeUnit

/** IPO alerts on this phone: 09:15 IST (market open) and 15:00 IST (2 hours before the 17:00 close) on an IPO's last day,
 *  only when the call is APPLY, or at 15:00 when the 14:10 NSE update changed an APPLY. Reads docs/data/ipo_today.json. */
object IpoAlerts {
    private val IST: ZoneId = ZoneId.of("Asia/Kolkata")
    private val SLOTS = mapOf("am" to LocalTime.of(9, 15), "pm" to LocalTime.of(15, 0))
    private const val CHANNEL = "ipo"

    private fun request(slot: String) = OneTimeWorkRequestBuilder<IpoWorker>()
        .setInitialDelay(delayTo(SLOTS.getValue(slot)).toMillis(), TimeUnit.MILLISECONDS)
        .setInputData(workDataOf("slot" to slot)).addTag("ipo-alert").build()

    private fun delayTo(t: LocalTime): Duration {
        val now = ZonedDateTime.now(IST)
        var at = now.with(t).withSecond(0).withNano(0)
        if (!at.isAfter(now.plusMinutes(1))) at = at.plusDays(1)
        return Duration.between(now, at)
    }

    /** Called on app start: keeps one pending alert check per slot. */
    fun schedule(ctx: Context) {
        SLOTS.keys.forEach { WorkManager.getInstance(ctx).enqueueUniqueWork("ipo-$it", ExistingWorkPolicy.KEEP, request(it)) }
    }

    /** The 09:15 check found no report for today yet (the 08:30 report publishes a little late): look once more in 30 minutes. */
    fun retryLater(ctx: Context) {
        val req = OneTimeWorkRequestBuilder<IpoWorker>().setInitialDelay(30, TimeUnit.MINUTES)
            .setInputData(workDataOf("slot" to "am", "retry" to true)).addTag("ipo-alert").build()
        WorkManager.getInstance(ctx).enqueueUniqueWork("ipo-am-retry", ExistingWorkPolicy.REPLACE, req)
    }

    /** Called by the worker when it finishes: the next day's check for the same slot. */
    fun next(ctx: Context, slot: String) {
        WorkManager.getInstance(ctx).enqueueUniqueWork("ipo-$slot", ExistingWorkPolicy.APPEND_OR_REPLACE, request(slot))
    }

    fun cancel(ctx: Context) { WorkManager.getInstance(ctx).cancelAllWorkByTag("ipo-alert") }

    /** Bidding close of an IPO today ("5:00 PM" in the report); 17:00 when missing or unreadable. */
    private fun closeAt(i: IpoOpen): LocalTime = runCatching {
        LocalTime.parse(i.closeTime!!.trim().uppercase(), java.time.format.DateTimeFormatter.ofPattern("h:mm a", java.util.Locale.ENGLISH))
    }.getOrDefault(LocalTime.of(17, 0))

    /** Alerts due for [slot] from today's report at time [now] (pure, so it is easy to check). Nothing once bidding has closed. */
    fun due(x: IpoToday, slot: String, today: String, now: LocalTime = LocalTime.now(IST)): List<Pair<String, String>> {
        if (x.date != today) return emptyList()
        return x.actionable.filter { it.finalDay && it.lastDate == today }.mapNotNull { i ->
            val close = closeAt(i)
            if (!now.isBefore(close)) return@mapNotNull null  // a late job must not say "2 hours left" after bids closed
            val left = Duration.between(now, close).toMinutes()
            val leftTxt = if (left >= 105) "2 hours left" else "$left min left"
            val pm = i.pmUpdate
            val sub = i.subscription?.overall?.let { "${fmt(it, 1)}× subscribed" } ?: "subscription –"
            val gmp = i.gmpHigh?.let { "GMP ₹${fmt(it, 0)}" + (i.gmpPctHigh?.let { p -> " (${fmt(p, 1)}%)" } ?: "") } ?: "GMP –"
            when {
                slot == "pm" && pm?.callBefore == "APPLY" && pm.callAfter != "APPLY" ->
                    "Call changed: ${i.name} · now ${pm.callAfter}" to "Updated ${pm.asOf?.substringAfter('T')?.take(5) ?: "–"}: $sub. ${i.missing.lastOrNull() ?: ""}".trim()
                i.action != "APPLY" -> null
                slot == "am" -> "Last day: ${i.name} · APPLY" to "${i.rating} · $gmp · $sub. Bids close today."
                else -> "$leftTxt: ${i.name} · APPLY" to (if (pm != null) "Updated ${pm.asOf?.substringAfter('T')?.take(5) ?: "–"}: " else "") +
                    i.subscription.let { s -> if (s == null) sub else "${fmt(s.overall, 1)}× (QIB ${fmt(s.qib, 1)}×, NII ${fmt(s.nii, 1)}×, Retail ${fmt(s.retail, 1)}×)" } + ". $gmp."
            }
        }
    }

    fun notify(ctx: Context, id: Int, title: String, text: String) {
        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(ctx, android.Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return
        val nm = ctx.getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26) nm.createNotificationChannel(NotificationChannel(CHANNEL, "IPO alerts", NotificationManager.IMPORTANCE_HIGH))
        val open = PendingIntent.getActivity(ctx, 0, Intent(ctx, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val n = NotificationCompat.Builder(ctx, CHANNEL).setSmallIcon(android.R.drawable.ic_popup_reminder)
            .setContentTitle(title).setContentText(text).setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setContentIntent(open).setAutoCancel(true).setPriority(NotificationCompat.PRIORITY_HIGH).build()
        runCatching { NotificationManagerCompat.from(ctx).notify(id, n) }
    }
}

class IpoWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result {
        val slot = inputData.getString("slot") ?: "am"
        val retry = inputData.getBoolean("retry", false)
        try {
            val today = java.time.LocalDate.now(ZoneId.of("Asia/Kolkata")).toString()
            val prefs = applicationContext.getSharedPreferences("narrativ", Context.MODE_PRIVATE)
            val x = Repo(applicationContext).get<IpoToday>("data/ipo_today.json")
            if ((x == null || x.date != today) && slot == "am" && !retry) IpoAlerts.retryLater(applicationContext)
            if (x != null && prefs.getBoolean("ipoAlerts", true)) {
                IpoAlerts.due(x, slot, today).forEach { (title, text) ->
                    val key = "ipoN-$today-$slot-$title"
                    if (!prefs.getBoolean(key, false)) {
                        IpoAlerts.notify(applicationContext, key.hashCode(), title, text)
                        prefs.edit().putBoolean(key, true).apply()
                    }
                }
            }
        } finally {
            if (!retry) IpoAlerts.next(applicationContext, slot)  // the one-off retry must not start another daily chain
        }
        return Result.success()
    }
}
