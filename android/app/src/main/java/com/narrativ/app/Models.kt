package com.narrativ.app

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

@Serializable data class Regime(val label: String? = null, @SerialName("breadth_pct") val breadthPct: Double? = null,
                                @SerialName("nifty_above_200dma") val niftyAbove: Boolean? = null)

@Serializable data class Bands(val pivot: Double? = null, @SerialName("buy_low") val buyLow: Double? = null,
                               @SerialName("buy_high") val buyHigh: Double? = null,
                               @SerialName("pullback_low") val pullbackLow: Double? = null,
                               @SerialName("pullback_high") val pullbackHigh: Double? = null,
                               val stop: Double? = null, @SerialName("stop_pct") val stopPct: Double? = null,
                               val target: Double? = null, val trail: Double? = null,
                               @SerialName("exit_below_sma50") val exitBelowSma50: Double? = null)

@Serializable data class EpsEst(val cur: Double? = null, val d30: Double? = null, val d90: Double? = null)
/** Yahoo consensus (third-party opinion). Present only when at least one analyst has a target. */
@Serializable data class Analyst(val mean: Double = 0.0, val low: Double? = null, val high: Double? = null, val n: Int? = null,
                                 val upside: Double? = null, val fresh: String? = null, val mix: String? = null,
                                 @SerialName("eps_est") val epsEst: EpsEst? = null,
                                 @SerialName("first_tracked") val firstTracked: String? = null,
                                 @SerialName("last_change") val lastChange: String? = null, val src: String? = null)
@Serializable data class Rot(val ratio: Double = 100.0, val mom: Double = 100.0, val q: String = "", val r1w: Double? = null,
                             val r1m: Double? = null, val r3m: Double? = null, val asof: String? = null, val n: Int? = null,
                             val ticker: String? = null)
@Serializable data class RotationFile(val date: String? = null, val bench: String? = null, val sectors: Map<String, Rot> = emptyMap(),
                                      val industries: Map<String, Rot> = emptyMap(), val best: Map<String, List<String>> = emptyMap())

@Serializable data class QItem(val symbol: String = "", val name: String? = null, val reason: String? = null, val task: String? = null)
@Serializable data class QueueFile(val date: String? = null, val items: List<QItem> = emptyList())

/** One computed value with its formula, inputs and source. */
@Serializable data class Metric(val v: Double? = null, val f: String = "", @SerialName("in") val inputs: Map<String, kotlinx.serialization.json.JsonPrimitive> = emptyMap(),
                                val src: String = "", val url: String? = null, val u: String? = null, val nm: Boolean = false)

@Serializable data class Credibility(val pct: Int = 0, val due: Int = 0, val delivered: Int = 0, val partly: Int = 0,
                                     val missed: Int = 0, val delayed: Int = 0)

@Serializable data class ResearchBrief(val has: Boolean = false, val updated: String? = null, val thesis: String? = null,
                                       val credibility: Credibility? = null,
                                       @SerialName("no_concall") val noConcall: String? = null, val health: String? = null)

@Serializable data class Checkpoint(val id: String = "", val type: String = "", val due: String = "", val what: String = "",
                                    val expected: String? = null, val source: String? = null, val status: String = "open",
                                    val outcome: String? = null, val evidence: String? = null,
                                    val resolved: String? = null)

@Serializable data class NextResults(val date: String? = null, val purpose: String? = null, val source: String? = null)
@Serializable data class BulkDeal(val date: String? = null, val client: String? = null, val side: String? = null,
                                  val qty: Double? = null, val price: Double? = null)
@Serializable data class Filing(val date: String? = null, val text: String? = null, val category: String? = null, val url: String? = null)
@Serializable data class PromoterPoint(val date: String = "", @SerialName("promoter_pct") val pct: Double = 0.0)
@Serializable data class Exchange(val filings: List<Filing> = emptyList(), val promoter: List<PromoterPoint> = emptyList(),
                                  @SerialName("promoter_chg_qoq") val promoterChg: Double? = null,
                                  @SerialName("delivery_pct_1m") val delivery1m: Double? = null,
                                  @SerialName("delivery_pct_last") val deliveryLast: Double? = null)

@Serializable data class Update(val date: String = "", val call: String = "", val type: String = "", val text: String = "",
                                val quote: String = "", val source: String = "")
@Serializable data class Promise(val id: String = "", @SerialName("made_on") val madeOn: String = "", val call: String = "",
                                 val kind: String = "other", val promise: String = "", val due: String? = null,
                                 @SerialName("due_verified") val dueVerified: Boolean? = null,
                                 val quote: String = "", val source: String = "", val status: String = "pending",
                                 val updates: List<Update> = emptyList())
/** Quoted research item; drivers also carry a kind (capacity, product, ...) and a due date. */
@Serializable data class QuotedItem(val text: String = "", val quote: String = "", val source: String = "", val kind: String? = null, val due: String? = null)
/** Claude's review of a flagged check (research.json flag_reviews, e.g. G1 exchange action: "dismissed"). */
@Serializable data class FlagReview(val verdict: String? = null, val note: String? = null, val quote: String? = null, val source: String? = null, val date: String? = null)
@Serializable data class Research(val updated: String? = null, val quarter: String? = null,
                                  @SerialName("source_type") val sourceType: String? = null, val thesis: String? = null,
                                  val promises: List<Promise> = emptyList(), val catalysts: List<QuotedItem> = emptyList(),
                                  @SerialName("red_flags") val redFlags: List<QuotedItem> = emptyList(),
                                  val credibility: Credibility? = null, @SerialName("outlook_score") val outlookScore: Int? = null,
                                  @SerialName("no_concall") val noConcall: String? = null,
                                  val scan: Scan? = null, val audit: AuditV? = null, val drivers: List<QuotedItem> = emptyList(),
                                  @SerialName("data_issues") val dataIssues: List<JsonElement> = emptyList(),
                                  @SerialName("flag_reviews") val flagReviews: Map<String, FlagReview> = emptyMap())
/** Claude's full review of a stock (verified checks only). */
@Serializable data class AuditV(val date: String? = null, val verdict: String? = null, val summary: String? = null,
                                val checks: List<JsonObject> = emptyList(), val issues: List<JsonElement> = emptyList()) {
    val failed: Int get() = checks.count { (it["ok"] as? JsonPrimitive)?.content == "false" }
}

/** multibagger-scan output. Marks need a verified quote (else "unproven"); label, legs and scenario prices are rule-computed. */
@Serializable data class Mark(val id: String = "", val name: String = "", val mark: String = "u", val note: String = "",
                              val quote: String = "", val source: String = "")
@Serializable data class Scenario(val name: String = "", val price: Double? = null, val pct: Double? = null, val theory: String = "",
                                  val formula: String = "", val src: String = "")
@Serializable data class Watch(val text: String = "", val check: String = "", val due: String? = null, val quote: String = "", val source: String = "")
@Serializable data class DerivedMetric(val name: String = "", val value: String = "", val formula: String = "", val src: String = "",
                                       val good: Boolean? = null)
@Serializable data class Scan(val date: String? = null, val label: String? = null, val legs: Map<String, String> = emptyMap(),
                              val arc: String? = null, val checklist: Map<String, List<Mark>> = emptyMap(),
                              val scenarios: List<Scenario> = emptyList(), @SerialName("settles") val settles: String? = null,
                              @SerialName("must_go_right") val mustGoRight: List<Watch> = emptyList(),
                              @SerialName("kill_switches") val killSwitches: List<Watch> = emptyList(),
                              val derived: List<DerivedMetric> = emptyList(), val levers: List<QuotedItem> = emptyList())

@Serializable data class Snapshot(val d: String = "", val score: Double? = null, val status: String? = null, val price: Double? = null)
@Serializable data class StockHistory(val symbol: String = "", val snapshots: List<Snapshot> = emptyList(),
                                      val checkpoints: List<Checkpoint> = emptyList())

@Serializable data class Chart(val c: List<Double> = emptyList(), val ohlc: List<List<kotlinx.serialization.json.JsonPrimitive>> = emptyList(),
                               val sma50: List<Double?> = emptyList(), val sma200: List<Double?> = emptyList(),
                               val d0: String? = null)

@Serializable data class Change(val type: String = "new", val text: String = "")
@Serializable data class Release(val version: String = "", val date: String = "", val changes: List<Change> = emptyList())
@Serializable data class VersionInfo(val versionCode: Int = 0, val versionName: String = "", val date: String = "",
                                     val apkUrl: String = "", val sizeMb: Double? = null, val sha256: String? = null, val changelog: List<Release> = emptyList())

@Serializable data class MemStock(val symbol: String, val name: String = "", val status: String = "",
                                  @SerialName("first_seen") val firstSeen: String? = null,
                                  @SerialName("drop_reason") val dropReason: String? = null, val health: String? = null,
                                  val checkpoints: List<Checkpoint> = emptyList(), val verdicts: List<VLog> = emptyList())
@Serializable data class MemoryFile(val date: String? = null, val stocks: List<MemStock> = emptyList())

// ---------------------------------------------------------------- v2 list file (docs/data/picks.json)
@Serializable data class MoodInput(val k: String = "", val name: String = "", val value: Double? = null, val unit: String? = null,
                                   val asof: String? = null, val src: String? = null, val pct: Int? = null, val score: Int? = null,
                                   val note: String? = null, @SerialName("chg_1m") val chg1m: Int? = null,
                                   @SerialName("fear_when") val fearWhen: String? = null)
@Serializable data class Mood(val score: Int? = null, val zone: String? = null, val hint: String? = null,
                              @SerialName("n_inputs") val nInputs: Int? = null, val inputs: List<MoodInput> = emptyList(),
                              val series: List<List<JsonPrimitive>> = emptyList(), @SerialName("chg_1m") val chg1m: Int? = null,
                              val movers: List<String> = emptyList(), val method: String? = null)
@Serializable data class FunnelV2(val listed: Int? = null, val companies: Int? = null, val levels: List<Int> = emptyList(),
                                  val researched: Int? = null, val queue: Int? = null, val verdicts: Map<String, Int> = emptyMap(),
                                  val decisions: Map<String, Int> = emptyMap())
/** missing: why the stock is not (yet) a verified Buy, most specific reason first ("Not rated" reasons). */
@Serializable data class Decision(val d: String = "Not rated", val why: List<String> = emptyList(), val missing: List<String> = emptyList(),
                                  val verified: String? = null, val candidate: String? = null)
@Serializable data class Cp2(val type: String? = null, val due: String? = null, val what: String? = null, val status: String? = null)
@Serializable data class Out(val l: Int = 0, val w: String? = null)

/** One company in the funnel. t = tier per level (1 dark green .. 5 red, 0 grey), sc = level score (0..100, null = not scored;
 *  index 5 Discovery is filled since the data-gaps change). cv = rule-built conviction ("High" / "Medium" / "Low") of a
 *  verified Buy, null otherwise (narrativ/conviction.py). */
@Serializable data class P(
    val s: String, val c: String = "", val x: String = "", val n: String = "", val i: String? = null, val sec: String? = null,
    val p: Double? = null, val d1: Double? = null, val mc: Double? = null, val t: List<Int> = emptyList(), val sc: List<Int?> = emptyList(),
    val vd: String = "", val pr: Double = 0.0, val turn: Boolean = false, val ext: Boolean = false, val gn: Map<String, String> = emptyMap(),
    val out: Out? = null, val why: String? = null, val su: String? = null, val bt: String? = null, val up: Double? = null, val na: Int? = null,
    val sp: List<Double> = emptyList(), val r: Boolean = false, val ss: String? = null, val cp: List<Cp2> = emptyList(),
    val tags: List<String> = emptyList(), val bq: Int? = null, val dc: String? = null, val ld: String? = null, val vf: String? = null, val af: Int? = null,
    val cand: String? = null, val rk: Int? = null, val mb: Boolean = false, val cv: String? = null, val tb: Int? = null,
) {
    fun tier(level: Int): Int = t.getOrElse(level) { 0 }
}
@Serializable data class PicksFile(val v: Int = 0, val top10: List<String> = emptyList(), val updated: String? = null, val date: String? = null, val mood: Mood? = null,
                                   val regime: Regime = Regime(), val funnel: FunnelV2 = FunnelV2(),
                                   val tiers: Map<String, List<String>> = emptyMap(),
                                   @SerialName("level_names") val levelNames: Map<String, String> = emptyMap(), val picks: List<P> = emptyList(),
                                   @SerialName("research_updated") val researchUpdated: String? = null)

// ---------------------------------------------------------------- v2 per-stock file (docs/data/fin/<symbol>.json)
@Serializable data class Item(val id: String = "", val n: String = "", val m: Int? = null, val v: String? = null, val k: String? = null,
                              val note: String? = null, val pts: List<Double> = emptyList(), val u: String? = null)
@Serializable data class Trig(val id: String = "", val n: String = "", val v: String? = null, val strong: Boolean = false)
@Serializable data class Risk(val text: String = "", val src: String? = null, val k: String? = null, val quote: String? = null)
@Serializable data class Level(val t: Int = 0, val name: String = "", val s: Int? = null, val cov: List<Int> = emptyList(), val why: String? = null,
                               val items: List<Item> = emptyList(), val out: Boolean = false, val rm: String? = null, val turn: Boolean = false,
                               val extended: Boolean = false, @SerialName("cov_pct") val covPct: Int? = null, val flags: List<String> = emptyList(),
                               val quarters: Int? = null, val type: String? = null, val metric: String? = null, val mval: Double? = null, val mkey: String? = null,
                               val cheap: Int? = null, val exp: Int? = null, val wind: String? = null, val nlive: Int? = null,
                               val triggers: List<Trig> = emptyList(), val risks: List<Risk> = emptyList(), val researched: Boolean = false,
                               @SerialName("vol_ratio") val volRatio: Double? = null)
@Serializable data class Setup(val type: String = "", val lo: Double? = null, val hi: Double? = null, val add: Double? = null, val stop: Double? = null,
                               val note: String? = null, val rr: Double? = null, @SerialName("rr_note") val rrNote: String? = null,
                               @SerialName("size_10l") val size10l: Int? = null, val trail: Double? = null, val sma50: Double? = null,
                               @SerialName("watch_lo") val watchLo: Double? = null, @SerialName("watch_hi") val watchHi: Double? = null,
                               val atr: Double? = null, val price: Double? = null, val h55: Double? = null, val ref: Double? = null,
                               @SerialName("stop_basis") val stopBasis: String? = null)
@Serializable data class Stand(val lv: String = "", val n: String = "", val v: String = "", val k: String? = null)
@Serializable data class Standouts(val good: List<Stand> = emptyList(), val watch: List<Stand> = emptyList())
@Serializable data class ScanState(val state: String = "never", val date: String? = null, val reopen: String? = null, val next: String? = null)
@Serializable data class RLog(val date: String = "", val kind: String = "", val text: String = "", val verdict: String? = null)
@Serializable data class VLog(val d: String = "", val v: String = "", val from: String? = null, val cause: String? = null)
@Serializable data class StockInfo(val stage: String? = null, val status: String? = null, val bands: Bands? = null,
                                   @SerialName("ret_3m") val ret3m: Double? = null, @SerialName("ret_6m") val ret6m: Double? = null,
                                   val hi52: Double? = null, val lo52: Double? = null, val dist200: Double? = null,
                                   @SerialName("rs_pct") val rsPct: Int? = null, @SerialName("traded_value_cr") val tradedValueCr: Double? = null,
                                   @SerialName("ind_pe") val indPe: Double? = null, val kind: String? = null,
                                   val promoter: List<PromoterPoint> = emptyList(), @SerialName("inst_pct") val instPct: Double? = null,
                                   val analysts: Int? = null, val summary: String? = null, val website: String? = null,
                                   @SerialName("next_results") val nextResults: NextResults? = null,
                                   @SerialName("bulk_deals") val bulkDeals: List<BulkDeal> = emptyList(), val exchange: Exchange = Exchange(),
                                   val tags: List<String> = emptyList(), val industry: String? = null, val rotation: String? = null,
                                   val events: List<Ev> = emptyList())
/** Exchange announcement typed by rule: sev red (can break a thesis), watch (inspection observations, court / tax / pollution
 *  board orders: needs a look), green (possible trigger), info. Colour: sevColor(sev). */
@Serializable data class Ev(val date: String? = null, val type: String = "", val sev: String = "info", val text: String = "",
                            val category: String? = null, val url: String? = null)
/** Rule-built conviction of a verified Buy (narrativ/conviction.py assess(); fin/<SYM>.json "conviction", null for any
 *  other decision). level High / Medium / Low; met of [of] checks C1..C7; never changes the decision. */
@Serializable data class Conviction(val level: String? = null, val met: Int? = null, val of: Int? = null, val why: String? = null,
                                    val rule: String? = null, val date: String? = null, val checks: List<ConvCheck> = emptyList())
/** One conviction check: id (C1..C7), name, met, the figure or reason (v). */
@Serializable data class ConvCheck(val id: String = "", val n: String = "", val ok: Boolean? = null, val v: String? = null, val why: String? = null)
/** The latest earnings call in brief (AlphaStreet's AlphaBrief): metrics are [label, value, direction]. */
@Serializable data class CallCard(val call: String = "", val date: String = "", val headline: String? = null,
                                  val metrics: List<List<String>> = emptyList(), val bullets: List<String> = emptyList(), val url: String? = null)
/** A news headline matched by company name (last 30 days, newest first). time: ISO with offset. */
@Serializable data class NewsItem(val title: String = "", val url: String? = null, val time: String? = null, val source: String? = null)
/** Detail.narrativ: the one-screen story behind the "Narrativ" button on the stock page. Every field optional so older files parse. */
@Serializable data class NarrativGoing(val text: String = "", val tone: String = "good")
@Serializable data class NarrativPlan(val text: String = "", val due: String? = null)
@Serializable data class NarrativSheet(val what: String? = null, val money: String? = null, val going: NarrativGoing? = null,
                                       val plans: List<NarrativPlan> = emptyList(), val risks: List<String> = emptyList(),
                                       @SerialName("one_line") val oneLine: String? = null, val written: String? = null,
                                       val plain: Boolean = false)

@Serializable data class Detail(val metrics: Map<String, JsonElement> = emptyMap(), val analyst: Analyst? = null,
                                val levels: Map<String, Level> = emptyMap(), val verdict: String = "", val statement: String = "",
                                val standouts: Standouts = Standouts(), val setup: Setup = Setup(),
                                val hist: List<Map<String, JsonPrimitive>> = emptyList(), val scan: ScanState = ScanState(),
                                @SerialName("verdict_log") val verdictLog: List<VLog> = emptyList(), val stock: StockInfo = StockInfo(),
                                val decision: Decision? = null, @SerialName("audit_flags") val auditFlags: List<String> = emptyList(),
                                @SerialName("research_log") val researchLog: List<RLog> = emptyList(),
                                val conviction: Conviction? = null,
                                @SerialName("latest_call_card") val callCard: CallCard? = null,
                                val news: List<NewsItem> = emptyList(),
                                val narrativ: NarrativSheet? = null) {
    fun m(key: String): Metric? = (metrics[key] as? JsonObject)?.let { runCatching { json.decodeFromJsonElement(Metric.serializer(), it) }.getOrNull() }
    fun v(key: String): Double? = m(key)?.takeIf { !it.nm }?.v
    fun str(key: String): String? = (metrics[key] as? JsonPrimitive)?.takeIf { it.isString }?.content
    /** [quarter end, revenue cr, profit cr, EBITDA margin %] for the last 16 quarters. */
    val quarterly: List<List<Double?>> get() = (metrics["quarterly"] as? JsonArray)?.mapNotNull { r ->
        (r as? JsonArray)?.let { a -> listOf(null) + a.drop(1).map { (it as? JsonPrimitive)?.content?.toDoubleOrNull() } }
    }.orEmpty()
    val quarterNames: List<String> get() = (metrics["quarterly"] as? JsonArray)?.mapNotNull { ((it as? JsonArray)?.getOrNull(0) as? JsonPrimitive)?.content }.orEmpty()
    val roceFy: List<Pair<Int, Double>> get() = (metrics["roce_fy"] as? JsonArray)?.mapNotNull { r ->
        (r as? JsonArray)?.let { a -> val y = (a[0] as? JsonPrimitive)?.content?.toIntOrNull(); val v = (a[1] as? JsonPrimitive)?.content?.toDoubleOrNull(); if (y != null && v != null) y to v else null }
    }.orEmpty()
}


/** docs/data/holidays.json: NSE trading holidays ("YYYY-MM-DD"); the live-quote poll treats them as closed. The file may be missing. */
@Serializable data class Holidays(val source: String? = null, val updated: String? = null,
                                  @SerialName("trading_holidays") val tradingHolidays: List<String> = emptyList())

/** docs/data/health.json: Data pipeline screen (feedback #41). */
@Serializable data class CheckCov(val level: String = "", val id: String = "", val name: String = "", val data: Int = 0,
                                  @SerialName("no_data") val noData: Int = 0, val pending: Int = 0, val na: Int = 0)
@Serializable data class Health(val date: String? = null, val finished: String? = null, val minutes: Double? = null,
                                val stages: List<List<kotlinx.serialization.json.JsonPrimitive>> = emptyList(), val problems: List<String> = emptyList(),
                                val sources: Map<String, Map<String, kotlinx.serialization.json.JsonPrimitive>> = emptyMap(),
                                @SerialName("coverage_pct") val coveragePct: Double? = null, val stocks: Int = 0, val checks: List<CheckCov> = emptyList())

@Serializable data class DataIssue(val symbol: String = "", val field: String = "", val app: String? = null, val found: String? = null,
                                   val cause: String? = null, val scope: String = "", val status: String = "open", val source: String? = null,
                                   @SerialName("first_seen") val firstSeen: String = "", @SerialName("fixed_on") val fixedOn: String? = null)
@Serializable data class IssuesFile(val date: String? = null, val open: Int = 0, @SerialName("open_systemic") val openSystemic: Int = 0,
                                    val fixed: Int = 0, val issues: Map<String, DataIssue> = emptyMap())

/** docs/data/ipo_today.json: the 08:30 IST open-IPO check (IPO.md). */
@Serializable data class IpoSub(@SerialName("as_of") val asOf: String? = null, val qib: Double? = null, val nii: Double? = null,
                                val retail: Double? = null, val overall: Double? = null, val source: String? = null)
@Serializable data class IpoPm(@SerialName("as_of") val asOf: String? = null, @SerialName("call_before") val callBefore: String? = null,
                               @SerialName("call_after") val callAfter: String? = null)
@Serializable data class IpoOpen(val name: String = "", val symbol: String? = null, val board: String = "", @SerialName("price_low") val priceLow: Double? = null,
    @SerialName("price_high") val priceHigh: Double? = null, val lot: Int? = null, @SerialName("issue_cr") val issueCr: Double? = null,
    @SerialName("open_date") val openDate: String = "", @SerialName("last_date") val lastDate: String = "", @SerialName("close_time") val closeTime: String? = null,
    val day: Int? = null, val days: Int? = null, @SerialName("final_day") val finalDay: Boolean = false,
    @SerialName("gmp_low") val gmpLow: Double? = null, @SerialName("gmp_high") val gmpHigh: Double? = null, @SerialName("gmp_observed") val gmpObserved: String? = null,
    @SerialName("gmp_stale") val gmpStale: Boolean = false, @SerialName("gmp_trend") val gmpTrend: String? = null, @SerialName("gmp_note") val gmpNote: String? = null,
    @SerialName("implied_low") val impliedLow: Double? = null, @SerialName("implied_high") val impliedHigh: Double? = null,
    @SerialName("gmp_pct_low") val gmpPctLow: Double? = null, @SerialName("gmp_pct_high") val gmpPctHigh: Double? = null,
    val subscription: IpoSub? = null, @SerialName("key_risk") val keyRisk: String = "", val missing: List<String> = emptyList(),
    val rating: String = "", val action: String = "", val why: String? = null, val top10: Boolean = false,
    @SerialName("gmp_sources") val gmpSources: List<String> = emptyList(), val sources: List<String> = emptyList(),
    @SerialName("pm_update") val pmUpdate: IpoPm? = null, val upcoming: Boolean = false,
    // code-only check (rules v2, 2026-11-23)
    val rules: List<IpoRule> = emptyList(), @SerialName("listing_date") val listingDate: String? = null,
    @SerialName("trading_days") val tradingDays: List<String> = emptyList(), @SerialName("fresh_cr") val freshCr: Double? = null,
    @SerialName("ofs_cr") val ofsCr: Double? = null, @SerialName("profit_lot") val profitLot: Double? = null,
    @SerialName("gmp_peak") val gmpPeak: Double? = null, @SerialName("gmp_pct") val gmpPct: Double? = null,
    @SerialName("gmp_by_source") val gmpBySource: Map<String, Double?> = emptyMap(),
    @SerialName("gmp_history") val gmpHistory: List<List<kotlinx.serialization.json.JsonPrimitive>> = emptyList(),
    @SerialName("sub_days") val subDays: List<List<kotlinx.serialization.json.JsonPrimitive>> = emptyList())
@Serializable data class IpoRule(val id: String = "", val n: String = "", val ok: Boolean? = null, val v: String? = null)
@Serializable data class IpoLater(val name: String = "", val board: String = "", val opens: String? = null, @SerialName("last_date") val lastDate: String? = null)
@Serializable data class IpoUp(val name: String = "", val board: String = "", @SerialName("open_date") val openDate: String? = null,
    @SerialName("last_date") val lastDate: String? = null, @SerialName("price_low") val priceLow: Double? = null, @SerialName("price_high") val priceHigh: Double? = null,
    val gmp: String? = null, @SerialName("gmp_observed") val gmpObserved: String? = null, val note: String? = null, val source: String? = null)
@Serializable data class IpoToday(val date: String? = null, @SerialName("checked_at") val checkedAt: String? = null, val summary: String? = null,
    val actionable: List<IpoOpen> = emptyList(), @SerialName("later_today") val laterToday: List<IpoLater> = emptyList(),
    val upcoming: List<IpoUp> = emptyList(), val top: List<String> = emptyList())

/** docs/data/schedule.json: scheduled jobs (IST) for the Data pipeline screen. */
@Serializable data class SchedJob(val time: String = "", val days: String = "", val name: String = "", val by: String = "")
@Serializable data class Schedule(val note: String? = null, val jobs: List<SchedJob> = emptyList())

/** docs/data/calls.json: every verified Buy (and rule candidate) from the day it was rated. */
@Serializable data class CallRec(val symbol: String = "", val kind: String = "", val decision: String? = null, val date: String = "",
                                 val price: Double? = null, val now: Double? = null, @SerialName("now_vs_nifty") val nowVsNifty: Double? = null,
                                 @SerialName("price_now") val priceNow: Double? = null, val ended: String? = null,
                                 @SerialName("end_decision") val endDecision: String? = null, @SerialName("to_end") val toEnd: Double? = null,
                                 @SerialName("to_end_vs_nifty") val toEndVsNifty: Double? = null, val stop: Double? = null)
@Serializable data class CallMix(val multibagger: Int = 0, @SerialName("on_track") val onTrack: Int = 0, val beat: Int = 0, val near: Int = 0,
                                 val loser: Int = 0, val n: Int = 0)
@Serializable data class CallNow(val n: Int = 0, @SerialName("avg_pct") val avgPct: Double? = null, @SerialName("avg_vs_nifty") val avgVsNifty: Double? = null,
                                 @SerialName("beat_pct") val beatPct: Int? = null, val mix: CallMix = CallMix())
@Serializable data class CallPortfolio(val since: String? = null, val days: Int = 0, @SerialName("min_days") val minDays: Int = 20,
                                       @SerialName("return_pct") val returnPct: Double? = null, @SerialName("nifty_pct") val niftyPct: Double? = null,
                                       @SerialName("excess_pct") val excessPct: Double? = null, @SerialName("max_dd_pct") val maxDdPct: Double? = null,
                                       @SerialName("nifty_max_dd_pct") val niftyMaxDdPct: Double? = null,
                                       @SerialName("days_ahead_pct") val daysAheadPct: Double? = null, val sharpe: Double? = null,
                                       @SerialName("nifty_sharpe") val niftySharpe: Double? = null,
                                       val curve: List<List<kotlinx.serialization.json.JsonPrimitive>> = emptyList())
@Serializable data class ReplayStat(val n: Int = 0, val months: Int? = null, @SerialName("win_pct") val winPct: Int? = null,
                                    @SerialName("avg_return_pct") val avgReturnPct: Double? = null, @SerialName("avg_vs_nifty") val avgVsNifty: Double? = null)
@Serializable data class ReplayVar(@SerialName("avg_top10") val avgTop10: Double? = null, @SerialName("3m") val m3: ReplayStat = ReplayStat(),
                                   @SerialName("6m") val m6: ReplayStat = ReplayStat(), @SerialName("12m") val m12: ReplayStat = ReplayStat())
@Serializable data class ReplayFile(val dates: List<String> = emptyList(), val months: Int = 0, val variants: Map<String, ReplayVar> = emptyMap(),
                                    val baselines: Map<String, ReplayVar> = emptyMap())
@Serializable data class CallSummary(val now: CallNow? = null, val portfolio: CallPortfolio? = null)
@Serializable data class CallsFile(val date: String? = null, val open: Int = 0, val summary: CallSummary = CallSummary(), val calls: List<CallRec> = emptyList())
