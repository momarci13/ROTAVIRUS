# 06 — K3: the eight allocation scenarios (one generic rule, parameterised).

if (!exists("ANALYSIS")) source(file.path("analysis", "R", "00_setup.R"))
st <- readRDS(file.path(RESULTS, "_state_05.rds")); list2env(st, environment())
message("[06] allocation ...")

## existing local (municipal) funding -> district envelope
muni <- fromJSON(file.path(INTER, "jogtar", "municipal_vaccination_support.json"))
muni_map <- setNames(numeric(0), character(0))
if (length(muni)) {
  for (i in seq_len(nrow(muni))) {
    key <- muni$municipality_key[i]; amt <- muni$support_amount_huf[i]
    m <- regmatches(key, regexec("budapest_(\\d{2})", key))[[1]]
    if (length(m) == 2 && !is.na(amt)) {
      dn <- sprintf("budapest %02d", as.integer(m[2]))
      row <- which(norm_settlement(D$district_name) == dn)
      if (length(row)) muni_map[D$district_id[row[1]]] <- amt
    }
  }
}
D[, existing_local_funding := as.numeric(muni_map[district_id])]
D[is.na(existing_local_funding), existing_local_funding := 0]
D[, L_envelope := existing_local_funding * pmax(lambda, 1)]

## scenario 7 eligibility: the REAL 290/2014 Annex 3 beneficiary districts
if (HAVE_290 && "kedvezmenyezett_290" %in% names(D)) {
  proxy <- FALSE
  D[, eligible_290 := kedvezmenyezett_290 == 1]
} else {
  proxy <- TRUE
  D[, eligible_290 := score_socioeconomic >= quantile(score_socioeconomic, 2/3)]
}

A <- data.table(district_id = D$district_id)
A[, s0_statusquo := D$L_envelope]
A[, s1_percapita := normalise_budget(D$pop, BUDGET)]
A[, s2_epi       := normalise_budget(D$lambda, BUDGET)]
A[, s3_socio     := normalise_budget(D$pop * (D$score_socioeconomic - min(D$score_socioeconomic) + 0.01), BUDGET)]
A[, s4_capacity  := normalise_budget(D$pop * (D$score_healthcare   - min(D$score_healthcare)   + 0.01), BUDGET)]
A[, s5_fullneed  := normalise_budget(D$expected_cost * (1 + ETA * D$need_score), BUDGET)]
A[, s6_costgap   := pmax(D$expected_cost - D$L_envelope, 0)]
A[, s7_statutory := normalise_budget(ifelse(D$eligible_290, D$pop, 0), BUDGET)]

A <- merge(A, D[, .(district_id, district_name, county_id, county_name, nuts3_code,
                    need_score, need_rank, score_socioeconomic, pop, lambda,
                    eligible_290)], by = "district_id")
fwrite(A, file.path(RESULTS, "allocation.csv"))

lz <- function(x) { l <- lorenz_points(x); data.table(p = l$p, L = l$L) }
lor <- rbindlist(lapply(c("s1_percapita","s2_epi","s3_socio","s5_fullneed","s7_statutory"),
                        function(s) cbind(lz(A[[s]]), scn = SCN_LABELS[[s]])))
p5 <- ggplot(lor, aes(p, L, colour = scn)) +
  geom_abline(slope = 1, linetype = 3, colour = "grey50") +
  geom_line(linewidth = 0.5) +
  labs(x = "Járások kumulált hányada (allokáció szerint rendezve)",
       y = "A keret kumulált hányada", colour = NULL,
       title = "Az allokáció Lorenz-görbéi forgatókönyvenként") +
  theme(legend.position = c(0.02, 0.98), legend.justification = c(0, 1),
        legend.text = element_text(size = 6.5))
ggsave(file.path(FIGDIR, "fig5_lorenz.pdf"), p5, width = 4.6, height = 4.4)

macro("budgetHuf", BUDGET, big = TRUE)
macro("statusQuoTotal", sum(A$s0_statusquo), big = TRUE)
macro("costGapTotal", sum(A$s6_costgap), big = TRUE)
macro("nDistrictsMuni", sum(D$existing_local_funding > 0))
macro("nMuniSupport", sum(!is.na(muni$support_amount_huf)))
macro("nEligibleProxy", sum(D$eligible_290))
macro("statusQuoNonZero", sum(A$s0_statusquo > 0))
macro("statProxy", if (proxy) "igen (proxy: a szocioökonómiai depriváltság legrosszabb harmada)"
                    else "nem (a 290/2014.~Korm.~r.\\ 3.~melléklete betöltve)")
if (!proxy) macro("nKomplexProgram", sum(D$komplex_program_290 == 1))

saveRDS(list(D = D, A = A, muni = muni, muni_map = muni_map, proxy = proxy,
             base_scn = base_scn, low_scn = low_scn, high_scn = high_scn,
             cost_per_case = cost_per_case, P = P, DW = DW, VARS = VARS,
             N_DIST = N_DIST, C_CASE = C_CASE), file.path(RESULTS, "_state_06.rds"))
flush_macros(file.path(TABDIR, "_numbers.tex"))
message("    allocation.csv, fig5 written")
