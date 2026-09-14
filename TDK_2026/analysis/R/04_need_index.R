# 04 — K2: composite need index. z-score standardisation + Mazziotta-Pareto
#      aggregation (non-compensatory); weighted-sum and rank variants for robustness.

if (!exists("ANALYSIS")) source(file.path("analysis", "R", "00_setup.R"))
st <- readRDS(file.path(RESULTS, "_state_03.rds")); list2env(st, environment())
message("[04] need index ...")

DIMS <- NEEDC$dimensions
DW   <- vapply(DIMS, function(x) x$weight, numeric(1))
VARS <- lapply(DIMS, function(x) x$variables)

for (d in names(VARS)) {
  z <- rowMeans(sapply(VARS[[d]], function(v) zscore(D[[v]])), na.rm = TRUE)
  D[[paste0("score_", d)]] <- z
}

## Mazziotta-Pareto: rescale each dim to mean 100 / sd 10, then
## M = weighted mean - weighted sd * cv   (negative penalty)
R <- sapply(names(VARS), function(d) 100 + 10 * D[[paste0("score_", d)]])
w <- DW[names(VARS)]
Mbar <- as.numeric(R %*% w) / sum(w)
Msd  <- sqrt(((R - Mbar)^2 %*% w) / sum(w))
Mcv  <- Msd / Mbar
D[, need_mpi   := Mbar - Msd * Mcv]
D[, need_score := minmax(need_mpi)]
D[, need_wsum  := minmax(Reduce(`+`, lapply(names(VARS),
                     function(d) DW[[d]] * minmax(D[[paste0("score_", d)]]))))]
D[, need_rank  := frank(-need_score, ties.method = "first")]

fwrite(D[order(need_rank)], file.path(RESULTS, "need_index.csv"))
top10 <- D[order(need_rank)][1:10, .(district_name, county_name, need_score,
            score_disease, score_socioeconomic, score_healthcare, lambda,
            jobseeker_rate, vacant_paed)]
fwrite(top10, file.path(RESULTS, "need_top10.csv"))

srtN <- D[order(-need_score)][1:30]
comp <- rbindlist(lapply(names(VARS), function(d) data.table(
  district = factor(paste0(srtN$district_name, " (", srtN$county_name, ")"),
                    levels = rev(paste0(srtN$district_name, " (", srtN$county_name, ")"))),
  dim = d, contrib = DW[[d]] * (srtN[[paste0("score_", d)]] - min(D[[paste0("score_", d)]])))))
dim_hu <- c(disease = "Betegségteher", socioeconomic = "Szocioökonómiai", healthcare = "Kapacitáshiány")
comp[, dim := factor(dim_hu[dim], levels = dim_hu)]
p4 <- ggplot(comp, aes(contrib, district, fill = dim)) +
  geom_col() +
  scale_fill_manual(values = setNames(unname(PAL[c("disease", "socioeconomic", "healthcare")]),
                                      dim_hu), name = NULL) +
  labs(x = "Súlyozott dimenzió-hozzájárulás (z-score, eltolva)", y = NULL,
       title = "A 30 legmagasabb szükségletindexű járás összetétele") +
  theme(axis.text.y = element_text(size = 6.5), legend.position = "bottom")
ggsave(file.path(FIGDIR, "fig4_need_composition.pdf"), p4, width = 6.6, height = 5.2)

macro("needMpiWsumSpearman",
      suppressWarnings(cor(D$need_score, D$need_wsum, method = "spearman")), digits = 3)

## ---- external validation + specification robustness -------------------
zbase <- setNames(lapply(names(VARS), function(d) zscore(D[[paste0("score_", d)]])), names(VARS))

if (HAVE_290 && !any(is.na(D$komplex_mutato))) {
  macro("needVsOfficialSpearman",
        suppressWarnings(cor(D$need_score, -D$komplex_mutato, method = "spearman")), digits = 2)
  macro("needVsOfficialSpearmanP",
        suppressWarnings(cor.test(D$need_score, -D$komplex_mutato, method = "spearman")$p.value),
        digits = 3)
  macro("needVsOfficialPearson", cor(D$need_score, D$deprivation_290), digits = 2)
  z290 <- zbase; z290[["socioeconomic"]] <- zscore_np(D$deprivation_290)
  D[, need_score_290 := mpi_from_z(z290, as.list(DW))]
  macro("needSwapSpearman",
        suppressWarnings(cor(D$need_score, D$need_score_290, method = "spearman")), digits = 3)
}

k_dec_spec <- max(round(TOP_DEC * N_DIST), 1)
spec_scores <- list(mpi_z = D$need_score, wsum_minmax = D$need_wsum,
                    rank_ws = minmax(Reduce(`+`, lapply(names(VARS),
                       function(d) DW[[d]] * frank(D[[paste0("score_", d)]])))))
for (drop in names(VARS)) {
  keep <- zbase[setdiff(names(VARS), drop)]
  spec_scores[[paste0("drop_", drop)]] <- mpi_from_z(keep, as.list(DW[setdiff(names(VARS), drop)]))
}
if ("need_score_290" %in% names(D)) spec_scores[["socio_290"]] <- D$need_score_290
spec_top <- integer(N_DIST)
for (v in spec_scores) spec_top[order(-v)[seq_len(k_dec_spec)]] <-
  spec_top[order(-v)[seq_len(k_dec_spec)]] + 1L
D[, spec_top_count := spec_top][, spec_n_specs := length(spec_scores)]
macro("nSpecs", length(spec_scores))
macro("nSpecRobust", sum(spec_top == length(spec_scores)))
fwrite(D[order(-spec_top_count), .(district_name, county_name, need_score,
        spec_top_count, spec_n_specs)], file.path(RESULTS, "spec_robust.csv"))

saveRDS(list(D = D, epi = epi, county_cases = county_cases, ksh = ksh, DW = DW,
             VARS = VARS, county_id_by_norm = county_id_by_norm, N_DIST = N_DIST),
        file.path(RESULTS, "_state_04.rds"))
flush_macros(file.path(TABDIR, "_numbers.tex"))
message("    need_index.csv, need_top10.csv, fig4 written")
