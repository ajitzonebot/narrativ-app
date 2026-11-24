package com.narrativ.app

import androidx.compose.ui.graphics.Color

// ---------------------------------------------------------------- sector / industry rotation
/** Industry (as in the app) -> NSE sector index tracked in rotation.json. Industries without a matching index show the industry only. */
val SECTOR_OF = mapOf(
    "IT - Software" to "IT", "IT - Services" to "IT", "IT - Hardware" to "IT",
    "Auto Components" to "Auto", "Automobiles" to "Auto", "Agricultural, Commercial & Construction Vehicles" to "Auto",
    "Pharmaceuticals & Biotechnology" to "Pharma",
    "Food Products" to "FMCG", "Beverages" to "FMCG", "Personal Products" to "FMCG", "Household Products" to "FMCG",
    "Diversified FMCG" to "FMCG", "Agricultural Food & other Products" to "FMCG",
    "Ferrous Metals" to "Metal", "Non - Ferrous Metals" to "Metal", "Minerals & Mining" to "Metal", "Metals & Minerals Trading" to "Metal",
    "Realty" to "Realty",
    "Oil" to "Energy", "Gas" to "Energy", "Petroleum Products" to "Energy", "Power" to "Energy",
    "Banks" to "Bank",
    "Construction" to "Infra", "Cement & Cement Products" to "Infra", "Transport Infrastructure" to "Infra", "Telecom - Services" to "Infra",
    "Finance" to "Fin Services", "Capital Markets" to "Fin Services", "Insurance" to "Fin Services", "Financial Technology (Fintech)" to "Fin Services",
    "Consumer Durables" to "Consumption", "Retailing" to "Consumption", "Leisure Services" to "Consumption", "Entertainment" to "Consumption",
)

/** Rotation colour: one palette everywhere (Look.kt quadC). */
fun quadColor(q: String?): Color = quadC(q)
