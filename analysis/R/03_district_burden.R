# 03 — K2: small-area district burden. Population-weighted apportionment of the
#      observed county case totals, with a +/-50% credible interval.

if (!exists("ANALYSIS")) source(file.path("analysis", "R", "00_setup.R"))
st <- readRDS(file.path(RESULTS, "_state_01.rds")); list2env(st, environment())
message("[03] district burden ...")

cty_y <- county_cases[year == YEAR, .(county_id, county_cases = cases)]
D <- merge(D, cty_y, by = "county_id", all.x = TRUE)
D[, pop_share := pop / sum(pop), by = county_id]
D[, lambda    := county_cases * pop_share]
D[, lambda_lo := lambda * (1 - CI_HW)]
D[, lambda_hi := lambda * (1 + CI_HW)]

## real child-population denominator (KSH county 0-14 apportioned by WA share)
POP_DENOM <- "working-age proxy"
if (!is.null(CHILD_BY_CY)) {
  c014 <- CHILD_BY_CY[year == YEAR, .(county_id, county_child_pop = population)]
  D <- merge(D, c014, by = "county_id", all.x = TRUE)
  D[, pop_child := county_child_pop * pop_share]
  D[, pop_u5 := pop_child * 0.34]           # documented national 0-4:0-14 ratio
  if (!any(is.na(D$pop_child))) POP_DENOM <- "KSH county 0-14 (apportioned)"
}
if (startsWith(POP_DENOM, "KSH")) {
  D[, burden_rate    := lambda / pop_child * 1e5]
  D[, burden_rate_u5 := lambda / pop_u5 * 1e3]
} else {
  D[, pop_child := pop][, pop_u5 := pop]
  D[, burden_rate := lambda / pop * 1e5][, burden_rate_u5 := burden_rate]
}
macro("popDenom", if (startsWith(POP_DENOM, "KSH"))
        "KSH vármegyei 0--14 éves népesség, járásra arányosítva"
      else "járási munkavállalási korú népesség (proxy)")

## 290/2014 official complex development indicator + statutory beneficiary set
if (HAVE_290) {
  D <- merge(D, POP290[, .(district_id, komplex_mutato, kedvezmenyezett,
                           komplex_program)], by = "district_id", all.x = TRUE)
  setnames(D, c("kedvezmenyezett", "komplex_program"),
           c("kedvezmenyezett_290", "komplex_program_290"))
  D[is.na(kedvezmenyezett_290), kedvezmenyezett_290 := 0L]
  D[is.na(komplex_program_290), komplex_program_290 := 0L]
  D[, deprivation_290 := -zscore_np(komplex_mutato)]
}
D[, evidence_class := "estimated"][, confidence := "low"]

fwrite(D, file.path(RESULTS, "district_burden.csv"))
saveRDS(list(D = D, epi = epi, county_cases = county_cases, ksh = ksh,
             county_id_by_norm = county_id_by_norm, N_DIST = N_DIST),
        file.path(RESULTS, "_state_03.rds"))

macro("nDistricts", N_DIST)
macro("burdenRateGini", gini(D$burden_rate), digits = 3)
macro("jobseekerRateGini", gini(D$jobseeker_rate), digits = 3)
macro("okfoVacantPaed", sum(D$vacant_paed))
macro("okfoDistrictsWithVacant", sum(D$vacant_paed > 0))
flush_macros(file.path(TABDIR, "_numbers.tex"))
message(sprintf("    lambda total = %.0f (year %d), burden-rate Gini = %.3f",
                sum(D$lambda), YEAR, gini(D$burden_rate)))
