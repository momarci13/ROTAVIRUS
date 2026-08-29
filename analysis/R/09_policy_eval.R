# 09 — K6: need-priority vs 290/2014(-proxy) eligibility, municipal support,
#      redistribution effect of epidemiological vs per-capita targeting.

if (!exists("ANALYSIS")) source(file.path("analysis", "R", "00_setup.R"))
st <- readRDS(file.path(RESULTS, "_state_08.rds")); list2env(st, environment())
message("[09] policy evaluation ...")

need_top_q <- A[order(-need_score)][seq_len(round(TOP_SHARE * nrow(A))), district_id]
elig <- D[eligible_290 == TRUE, district_id]
inter <- intersect(need_top_q, elig); uni <- union(need_top_q, elig)
macro("needTopQn", length(need_top_q))
macro("policyJaccard", length(inter) / length(uni), digits = 2)
macro("needTopInElig", 100 * length(inter) / length(need_top_q), digits = 0)

D[, muni_support := as.numeric(muni_map[district_id])][is.na(muni_support), muni_support := 0]
macro("ciMuni", if (sum(D$muni_support) > 0)
        concentration_index(D$muni_support, D$need_score) else NA_real_,
      digits = 3, plus = TRUE)
macro("nDistrictsMuni", sum(D$muni_support > 0))

red <- A[, .(s1 = sum(s1_percapita), s2 = sum(s2_epi)), by = county_name]
red[, delta := s2 - s1]
setorder(red, delta)
fwrite(red, file.path(RESULTS, "redistribution_s2_vs_s1.csv"))

p9 <- ggplot(red, aes(delta / 1e6, factor(county_name, levels = county_name),
                      fill = delta < 0)) +
  geom_col() +
  scale_fill_manual(values = c(`TRUE` = PAL["accent"], `FALSE` = "#4f81bd"), guide = "none") +
  geom_vline(xintercept = 0, colour = "grey50") +
  labs(x = "Változás (millió Ft): 2. (epidemiológiai) − 1. (fejkvóta)", y = NULL,
       title = "Újraelosztási hatás vármegyénként")
ggsave(file.path(FIGDIR, "fig9_redistribution.pdf"), p9, width = 6.4, height = 4.2)

D[, priority := district_id %in% need_top_q]
ct <- D[, .N, by = .(priority = ifelse(priority, "Prioritás", "Nem prioritás"),
                      elig = ifelse(eligible_290, "Jogosult", "Nem jogosult"))]
p9b <- ggplot(ct, aes(priority, N, fill = elig)) +
  geom_col() +
  scale_fill_manual(values = c("Jogosult" = "#1f4e79", "Nem jogosult" = "#c0504d"), name = NULL) +
  labs(x = NULL, y = "Járások száma",
       title = "Szükségleti prioritás vs. 290/2014(-proxy) jogosultság")
ggsave(file.path(FIGDIR, "fig9b_overlap.pdf"), p9b, width = 4.6, height = 3.2)

## external validation: composite need vs the official 290/2014 indicator
if (HAVE_290 && "komplex_mutato" %in% names(D) && !any(is.na(D$komplex_mutato))) {
  p10 <- ggplot(D, aes(komplex_mutato, need_score, colour = eligible_290)) +
    geom_point(size = 1.5, alpha = 0.75) +
    geom_smooth(method = "lm", se = FALSE, colour = "grey50", linetype = 2, linewidth = 0.6) +
    scale_colour_manual(values = c(`TRUE` = PAL["accent"], `FALSE` = "#4f81bd"),
                        labels = c(`TRUE` = "Kedvezményezett (290/2014)", `FALSE` = "Nem kedvezményezett"),
                        name = NULL) +
    labs(x = "290/2014 komplex fejlettségi mutató  (kisebb = deprivált)",
         y = "Összetett szükségletindex (MPI)",
         title = "Külső érvényesség: szükségletindex vs. hivatalos fejlettségi mutató") +
    theme(legend.position = "bottom")
  ggsave(file.path(FIGDIR, "fig10_external_validation.pdf"), p10, width = 5.2, height = 4.0)
}

saveRDS(list(D = D, A = A, EQ = EQ, red = red, ct = ct, need_top_q = need_top_q,
             base_cost_mrd = base_cost_mrd),
        file.path(RESULTS, "_state_09.rds"))
flush_macros(file.path(TABDIR, "_numbers.tex"))
message("    redistribution.csv, fig9, fig9b written")
