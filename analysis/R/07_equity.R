# 07 — K4: equity metrics per scenario; Spearman + Jaccard across scenarios.

if (!exists("ANALYSIS")) source(file.path("analysis", "R", "00_setup.R"))
st <- readRDS(file.path(RESULTS, "_state_06.rds")); list2env(st, environment())
message("[07] equity ...")

q_need <- as.integer(cut(frank(A$need_score, ties.method = "first"),
                         quantile(frank(A$need_score, ties.method = "first"),
                                  probs = seq(0, 1, 0.2)), include.lowest = TRUE)) - 1L

EQ <- rbindlist(lapply(SCN, function(s) {
  aid <- A[[s]]
  td <- theil_decomp(aid, A$county_id)
  data.table(
    scenario = s, label = SCN_LABELS[[s]],
    gini_aid = gini(aid),
    ci_need  = concentration_index(aid, A$need_score),
    ci_socio = concentration_index(aid, A$score_socioeconomic),
    kakwani_need = concentration_index(aid, A$need_score) - gini(A$need_score),
    theil_between = td$between, theil_within = td$within,
    theil_between_share = if (td$total != 0) td$between / td$total else NA_real_,
    worst_quintile_share = if (sum(aid) > 0) sum(aid[q_need == 4]) / sum(aid) else NA_real_)
}))
fwrite(EQ, file.path(RESULTS, "equity.csv"))

for (s in SCN) {
  tg <- TAGW[[s]]; r <- EQ[scenario == s]
  macro(paste0("ci", tg),   r$ci_need,   digits = 3, plus = TRUE)
  macro(paste0("kak", tg),  r$kakwani_need, digits = 3, plus = TRUE)
  macro(paste0("wq", tg),   100 * r$worst_quintile_share, digits = 1)
  macro(paste0("gini", tg), r$gini_aid,  digits = 3)
  macro(paste0("tb", tg),   100 * r$theil_between_share, digits = 0)
}

## 95% bootstrap CIs (resample districts) for the progressivity metrics
eqci <- rbindlist(lapply(c("s1_percapita", "s2_epi", "s5_fullneed", "s7_statutory"), function(s) {
  tg <- TAGW[[s]]
  ci <- boot_ci(function(c) concentration_index(c[[1]], c[[2]]),
                A[[s]], A$need_score, reps = 2000)
  kk <- boot_ci(function(c) concentration_index(c[[1]], c[[2]]) - gini(c[[2]]),
                A[[s]], A$need_score, reps = 2000)
  macro(paste0("ci", tg, "Lo"), ci["lo"], digits = 3, plus = TRUE)
  macro(paste0("ci", tg, "Hi"), ci["hi"], digits = 3, plus = TRUE)
  macro(paste0("kak", tg, "Lo"), kk["lo"], digits = 3, plus = TRUE)
  macro(paste0("kak", tg, "Hi"), kk["hi"], digits = 3, plus = TRUE)
  data.table(scenario = s, label = SCN_LABELS[[s]],
             ci_need = EQ[scenario == s, ci_need], ci_lo = ci["lo"], ci_hi = ci["hi"],
             kakwani = EQ[scenario == s, kakwani_need], kak_lo = kk["lo"], kak_hi = kk["hi"])
}))
fwrite(eqci, file.path(RESULTS, "equity_bootstrap.csv"))

sp <- cor(as.matrix(A[, ..NORMED]), method = "spearman")
fwrite(as.data.table(sp, keep.rownames = "rn"), file.path(RESULTS, "scenario_spearman.csv"))
K <- 20
tops <- lapply(NORMED, function(s) A[order(-get(s))][1:K, district_id]); names(tops) <- NORMED
jac <- outer(NORMED, NORMED, Vectorize(function(a, b) {
  u <- union(tops[[a]], tops[[b]]); length(intersect(tops[[a]], tops[[b]])) / length(u)
}))
dimnames(jac) <- list(NORMED, NORMED)
fwrite(as.data.table(jac, keep.rownames = "rn"), file.path(RESULTS, "scenario_jaccard.csv"))
macro("jaccardEpiFull", jac["s2_epi", "s5_fullneed"], digits = 2)
macro("spearmanEpiSocio", sp["s2_epi", "s3_socio"], digits = 2)

ord <- EQ[order(ci_need)]
p6 <- ggplot(ord, aes(ci_need, factor(label, levels = label))) +
  geom_vline(xintercept = 0, colour = "grey60") +
  geom_point(colour = PAL["primary"], size = 2) +
  labs(x = "Koncentrációs index (allokáció | szükséglet-rang) — pozitív = progresszív",
       y = NULL, title = "Az allokáció progresszivitása a szükséglethez képest")
ggsave(file.path(FIGDIR, "fig6_concentration.pdf"), p6, width = 6.6, height = 3.0)

saveRDS(list(D = D, A = A, EQ = EQ, q_need = q_need, base_scn = base_scn,
             low_scn = low_scn, high_scn = high_scn, cost_per_case = cost_per_case,
             P = P, DW = DW, VARS = VARS, N_DIST = N_DIST, muni_map = muni_map,
             proxy = proxy), file.path(RESULTS, "_state_07.rds"))
flush_macros(file.path(TABDIR, "_numbers.tex"))
message("    equity.csv, spearman, jaccard, fig6 written")
