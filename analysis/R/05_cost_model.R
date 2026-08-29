# 05 — K3: cost per notified case and expected cost per district.
#      Every parameter is an explicit assumed/estimated level (analysis config).

if (!exists("ANALYSIS")) source(file.path("analysis", "R", "00_setup.R"))
st <- readRDS(file.path(RESULTS, "_state_04.rds")); list2env(st, environment())
message("[05] cost model ...")

P <- COSTS$parameters
pv <- function(id, which = "base") as.numeric(P[[id]][[which]])

cost_per_case <- function(s) {
  c_inp <- s$hbcs_base_rate * s$hbcs_weight_paed_gastroenteritis
  c_out <- s$outpatient_point_value * s$outpatient_points_per_case + s$gp_visit_cost
  h <- s$hospitalisation_rate_notified
  c_direct <- h * c_inp + (1 - h) * c_out
  wage <- s$daily_gross_wage * WAGE_DEFL
  prod <- s$parental_work_loss_probability *
          pmin(s$mean_parental_workdays_lost, s$working_days_per_year) *
          wage * (1 + s$employer_contribution_rate)
  c_direct + prod
}

base_scn <- setNames(lapply(names(P), function(k) pv(k, "base")), names(P))
low_scn  <- setNames(lapply(names(P), function(k) pv(k, "low")),  names(P))
high_scn <- setNames(lapply(names(P), function(k) pv(k, "high")), names(P))

C_CASE    <- cost_per_case(base_scn)
D[, expected_cost := lambda * C_CASE]
D[, expected_cost_societal := lambda * base_scn$underreporting_multiplier * C_CASE]

cp <- rbindlist(lapply(names(P), function(id) {
  p <- P[[id]]
  data.table(param = id, desc = p$description, base = p$base, low = p$low, high = p$high,
             unit = p$unit %||% "", evidence = p$evidence_class, confidence = p$confidence)
}))
fwrite(cp, file.path(RESULTS, "cost_parameters.csv"))

macro("costPerCase", C_CASE, big = TRUE)
macro("costPerCaseLo", cost_per_case(low_scn), big = TRUE)
macro("costPerCaseHi", cost_per_case(high_scn), big = TRUE)
macro("totalExpectedCost", sum(D$expected_cost), big = TRUE)
macro("baseCostMrd", sum(D$expected_cost_societal) / 1e9, digits = 2)
macro("earningsDefl", WAGE_DEFL, digits = 3)
macro("deflMed", DEFL_MED, digits = 3)

saveRDS(list(D = D, base_scn = base_scn, low_scn = low_scn, high_scn = high_scn,
             cost_per_case = cost_per_case, P = P, DW = DW, VARS = VARS,
             epi = epi, county_id_by_norm = county_id_by_norm, N_DIST = N_DIST,
             C_CASE = C_CASE), file.path(RESULTS, "_state_05.rds"))
flush_macros(file.path(TABDIR, "_numbers.tex"))
message(sprintf("    cost per case = %.0f HUF ; societal annual = %.2f Mrd",
                C_CASE, sum(D$expected_cost_societal) / 1e9))
