# 08 — K5: one-way tornado (societal cost), PSA, Dirichlet weight resampling.

if (!exists("ANALYSIS")) source(file.path("analysis", "R", "00_setup.R"))
st <- readRDS(file.path(RESULTS, "_state_07.rds")); list2env(st, environment())
message("[08] sensitivity ...")
set.seed(SEED)

LAMBDA_TOT <- sum(D$lambda)
societal_cost_mrd <- function(s, bmult = 1)
  LAMBDA_TOT * bmult * s$underreporting_multiplier * cost_per_case(s) / 1e9

base_cost_mrd <- societal_cost_mrd(base_scn)
macro("baseCostMrd", base_cost_mrd, digits = 2)

PARAM_HU <- c(
  hbcs_base_rate = "Fekvőbeteg alapdíj (Ft/súlyszám)",
  hbcs_weight_paed_gastroenteritis = "HBCs-súlyszám (gyermek GE)",
  hospitalisation_rate_notified = "Kórházi felvételi arány",
  underreporting_multiplier = "Aluljelentési szorzó",
  daily_gross_wage = "Napi bruttó bér",
  parental_work_loss_probability = "Szülői munkakiesés valószínűsége",
  mean_parental_workdays_lost = "Kiesett munkanapok / eset",
  outpatient_points_per_case = "Járóbeteg pont / eset",
  gp_visit_cost = "Háziorvosi vizit költsége")

tor <- rbindlist(lapply(names(PARAM_HU), function(pid) {
  lo <- modifyList(base_scn, setNames(list(as.numeric(P[[pid]]$low)), pid))
  hi <- modifyList(base_scn, setNames(list(as.numeric(P[[pid]]$high)), pid))
  data.table(param = PARAM_HU[[pid]], low = societal_cost_mrd(lo), high = societal_cost_mrd(hi))
}))
tor <- rbind(tor, data.table(param = "Betegségteher ±50% sáv",
             low = societal_cost_mrd(base_scn, 1 - CI_HW),
             high = societal_cost_mrd(base_scn, 1 + CI_HW)))
tor[, spread := abs(high - low)]
setorder(tor, spread)
fwrite(tor, file.path(RESULTS, "tornado.csv"))

p7 <- ggplot(tor, aes(y = factor(param, levels = param))) +
  geom_segment(aes(x = low, xend = high, yend = factor(param, levels = param)),
               linewidth = 3, colour = PAL["primary"], alpha = 0.75) +
  geom_vline(xintercept = base_cost_mrd, colour = PAL["accent"]) +
  labs(x = sprintf("Teljes társadalmi várható éves költség (Mrd Ft) — alap: %.2f", base_cost_mrd),
       y = NULL, title = "Egyváltozós érzékenység (tornádó)")
ggsave(file.path(FIGDIR, "fig7_tornado.pdf"), p7, width = 6.6, height = 3.2)

## eta scan (the s5 allocation share depends only on eta + weights)
etas <- rbindlist(lapply(c(0.10, 0.25, 0.50, 0.75, 1.00), function(e) {
  raw <- normalise_budget(D$expected_cost * (1 + e * D$need_score), BUDGET)
  data.table(eta = e, worst_q_share = sum(raw[q_need == 4]) / sum(raw),
             ci_need = concentration_index(raw, D$need_score))
}))
fwrite(etas, file.path(RESULTS, "eta_scan.csv"))
macro("etaLoShare", 100 * etas$worst_q_share[1], digits = 1)
macro("etaHiShare", 100 * etas$worst_q_share[nrow(etas)], digits = 1)

## PSA -----------------------------------------------------------------
sample_param <- function(pid) {
  b <- as.numeric(P[[pid]]$base); lo <- as.numeric(P[[pid]]$low); hi <- as.numeric(P[[pid]]$high)
  if (b <= 0) return(b)
  if (pid %in% c("hospitalisation_rate_notified", "parental_work_loss_probability",
                 "vaccine_efficacy", "employer_contribution_rate")) {
    s <- 40; a <- max(b * s, 1e-3); bb <- max((1 - b) * s, 1e-3)
    return(min(max(rbeta(1, a, bb), lo * 0.5), min(hi * 1.2, 0.999)))
  }
  cvv <- max((hi - lo) / (3.92 * b), 0.05); k <- 1 / cvv^2
  rgamma(1, shape = k, scale = b / k)
}
base_w <- DW[names(VARS)]
zmat <- sapply(names(VARS), function(d) zscore(D[[paste0("score_", d)]]))

psa <- rbindlist(lapply(seq_len(PSA_DRAWS), function(i) {
  scn <- setNames(lapply(names(P), sample_param), names(P))
  bmult <- rlnorm(1, 0, 0.20)
  e <- runif(1, 0.2, 1.0)
  w <- as.numeric(rdirichlet1(base_w / sum(base_w) * DIR_CONC))
  nd <- as.numeric(zmat %*% w); nd <- (nd - min(nd)) / (max(nd) - min(nd))
  lam <- D$lambda * rlnorm(nrow(D), 0, 0.35)
  raw <- normalise_budget(lam * cost_per_case(scn) * (1 + e * nd), BUDGET)
  data.table(cost_mrd = societal_cost_mrd(scn, bmult),
             worst_q_share = sum(raw[q_need == 4]) / sum(raw),
             ci_need = concentration_index(raw, D$need_score))
}))
fwrite(psa, file.path(RESULTS, "psa.csv"))
macro("psaCostMean", mean(psa$cost_mrd), digits = 2)
macro("psaCostLo", quantile(psa$cost_mrd, 0.025), digits = 2)
macro("psaCostHi", quantile(psa$cost_mrd, 0.975), digits = 2)
macro("psaWorstQMean", 100 * mean(psa$worst_q_share), digits = 1)
macro("psaWorstQLo", 100 * quantile(psa$worst_q_share, 0.025), digits = 1)
macro("psaWorstQHi", 100 * quantile(psa$worst_q_share, 0.975), digits = 1)
macro("psaCiMean", mean(psa$ci_need), digits = 3, plus = TRUE)
macro("psaCiLo", quantile(psa$ci_need, 0.025), digits = 3, plus = TRUE)
macro("psaCiHi", quantile(psa$ci_need, 0.975), digits = 3, plus = TRUE)

p7b <- gridExtra::arrangeGrob(
  ggplot(psa, aes(cost_mrd)) + geom_histogram(bins = 40, fill = PAL["primary"]) +
    geom_vline(xintercept = base_cost_mrd, colour = PAL["accent"]) +
    labs(x = "Teljes társadalmi várható költség (Mrd Ft)", y = "Húzások",
         title = "PSA: költségbizonytalanság"),
  ggplot(psa, aes(ci_need)) + geom_histogram(bins = 40, fill = PAL["primary"]) +
    geom_vline(xintercept = 0, colour = "grey50") +
    labs(x = "Koncentrációs index (allokáció | szükséglet)", y = NULL,
         title = "PSA: progresszivitás (5. forgatókönyv)"),
  ncol = 2)
ggsave(file.path(FIGDIR, "fig7b_psa.pdf"), p7b, width = 7.2, height = 2.9)

## Dirichlet weight resampling -> P(top decile need) -----------------
k_dec <- max(round(TOP_DEC * N_DIST), 1)
counts <- numeric(N_DIST)
for (i in seq_len(W_DRAWS)) {
  w <- as.numeric(rdirichlet1(base_w / sum(base_w) * DIR_CONC))
  score <- as.numeric(zmat %*% w)
  counts[order(-score)[seq_len(k_dec)]] <- counts[order(-score)[seq_len(k_dec)]] + 1
}
D[, p_top_decile := counts / W_DRAWS]
robust <- D[p_top_decile >= ROBUST_T][order(-p_top_decile)]
fwrite(robust[, .(district_name, county_name, p_top_decile, need_score, lambda,
                  jobseeker_rate, vacant_paed)], file.path(RESULTS, "robust_priority.csv"))
macro("nRobustPriority", nrow(robust))
macro("robustThreshold", as.integer(ROBUST_T * 100))
macro("topDecileK", k_dec)
macro("psaDraws", PSA_DRAWS); macro("wDraws", W_DRAWS); macro("seed", as.character(SEED))
macro("nScenarios", 8)

srt <- D[order(-p_top_decile)]
p8 <- gridExtra::arrangeGrob(
  ggplot(data.table(x = seq_len(N_DIST), p = srt$p_top_decile), aes(x, p)) +
    geom_area(data = ~ subset(.x, p >= ROBUST_T), fill = PAL["accent"], alpha = 0.3) +
    geom_line(colour = PAL["primary"]) +
    geom_hline(yintercept = ROBUST_T, linetype = 2, colour = PAL["accent"]) +
    labs(x = "Járások (P szerint rendezve)", y = "P(felső decilis a szükségletben)",
         title = "Dirichlet-súlyújramintavétel"),
  ggplot(robust[1:min(12, .N)][order(p_top_decile)],
         aes(p_top_decile, factor(district_name, levels = district_name))) +
    geom_col(fill = PAL["primary"]) +
    labs(x = "P", y = NULL, title = "Robusztus prioritás") +
    theme(axis.text.y = element_text(size = 7)),
  ncol = 2, widths = c(2, 1))
ggsave(file.path(FIGDIR, "fig8_dirichlet.pdf"), p8, width = 7.4, height = 3.1)

## ---- two-way sensitivity: eta x under-reporting ---------------------
C_CASE <- cost_per_case(base_scn)
eta_grid <- c(0.10, 0.25, 0.50, 0.75, 1.00, 1.50)
ur_grid  <- c(3.0, 5.0, 8.0, 12.0, 15.0)
pc <- normalise_budget(D$pop, BUDGET)
tw <- outer(ur_grid, eta_grid, Vectorize(function(ur, e) {
  raw <- normalise_budget(D$lambda * ur * C_CASE * (1 + e * D$need_score), BUDGET)
  sum(abs(raw - pc)) / BUDGET / 2
}))
twci <- outer(ur_grid, eta_grid, Vectorize(function(ur, e) {
  raw <- normalise_budget(D$lambda * ur * C_CASE * (1 + e * D$need_score), BUDGET)
  concentration_index(raw, D$need_score)
}))
dimnames(tw) <- dimnames(twci) <- list(sprintf("UR=%g", ur_grid), sprintf("eta=%g", eta_grid))
fwrite(as.data.table(tw, keep.rownames = "row"), file.path(RESULTS, "twoway_reshuffle.csv"))
fwrite(as.data.table(twci, keep.rownames = "row"), file.path(RESULTS, "twoway_ci.csv"))
macro("twoWayCiMin", min(twci), digits = 3, plus = TRUE)
macro("twoWayCiMax", max(twci), digits = 3, plus = TRUE)
macro("twoWayReshufMin", 100 * min(tw), digits = 1)
macro("twoWayReshufMax", 100 * max(tw), digits = 1)

twlong <- rbind(
  data.table(expand.grid(ur = ur_grid, eta = eta_grid), val = as.vector(tw) * 100,
             panel = "Átcsoportosított keret (%)"),
  data.table(expand.grid(ur = ur_grid, eta = eta_grid), val = as.vector(twci),
             panel = "Koncentrációs index"))
p11 <- ggplot(twlong, aes(factor(eta), factor(ur), fill = val)) +
  geom_tile() + geom_text(aes(label = sprintf("%.2f", val)), size = 2) +
  facet_wrap(~ panel, scales = "free") +
  scale_fill_distiller(palette = "YlGnBu", direction = 1, guide = "none") +
  labs(x = expression(paste("szükségleti rugalmasság ", eta)),
       y = "aluljelentési szorzó", title = NULL)
ggsave(file.path(FIGDIR, "fig11_twoway.pdf"), p11, width = 7.6, height = 3.1)

## ---- cost-effectiveness / break-even (steady-state annual) ----------
vp   <- base_scn$vaccine_course_price + base_scn$vaccine_administration_cost
veff <- base_scn$vaccine_efficacy
UR   <- base_scn$underreporting_multiplier
D[, birth_cohort := pop_child / 15]
D[, subsidy_cost := birth_cohort * UPTAKE_GAIN * vp]
D[, averted_societal := (lambda * UR * C_CASE) * UPTAKE_GAIN * veff]
D[, net_benefit := averted_societal - subsidy_cost]
D[, benefit_cost_ratio := averted_societal / pmax(subsidy_cost, 1)]
ce <- D[order(-need_score), .(district_name, county_name, need_score, birth_cohort,
        subsidy_cost, averted_societal, net_benefit, benefit_cost_ratio)]
fwrite(ce, file.path(RESULTS, "cost_effectiveness.csv"))
macro("ceUptakeGain", 100 * UPTAKE_GAIN, digits = 0)
macro("ceBcrMedian", median(D$benefit_cost_ratio), digits = 2)
macro("ceNPositive", sum(D$net_benefit > 0))
topn <- D[order(-need_score)][seq_len(round(TOP_SHARE * N_DIST))]
macro("ceBcrTopNeed", median(topn$benefit_cost_ratio), digits = 2)
macro("ceNetTopNeedMrd", sum(topn$net_benefit) / 1e9, digits = 2)

p12 <- ggplot(D, aes(need_score, benefit_cost_ratio, colour = eligible_290)) +
  geom_hline(yintercept = 1, linetype = 2, colour = "grey50") +
  geom_point(size = 1.4, alpha = 0.75) +
  scale_colour_manual(values = c(`TRUE` = PAL["accent"], `FALSE` = "#4f81bd"), guide = "none") +
  labs(x = "Összetett szükségletindex", y = "Haszon/költség arány",
       title = "Egy szükségletarányos oltástámogatás megtérülése járásonként")
ggsave(file.path(FIGDIR, "fig12_costeffectiveness.pdf"), p12, width = 6.2, height = 3.4)

## ---- national context: rotavirus vs a vaccine-preventable comparator
if (!is.null(ANN_DIS) && all(c("rotavirus", "varicella") %in% names(ANN_DIS))) {
  a <- ANN_DIS[!is.na(rotavirus)][order(year)]
  sc <- max(a$rotavirus) / max(a$varicella, na.rm = TRUE)
  p13 <- ggplot(a, aes(year)) +
    geom_line(aes(y = rotavirus, colour = "Rotavírus (nem támogatott oltás)")) +
    geom_point(aes(y = rotavirus, colour = "Rotavírus (nem támogatott oltás)")) +
    geom_line(aes(y = varicella * sc, colour = "Bárányhimlő (2019-től kötelező)"), linetype = 2) +
    geom_vline(xintercept = 2019, linetype = 3, colour = "grey40") +
    scale_y_continuous(sec.axis = sec_axis(~ . / sc, name = "Bárányhimlő, bejelentett eset")) +
    scale_colour_manual(values = c("Rotavírus (nem támogatott oltás)" = PAL["accent"],
                                   "Bárányhimlő (2019-től kötelező)" = PAL["primary"]), name = NULL) +
    labs(x = "Év", y = "Rotavírus, bejelentett eset",
         title = "Országos bejelentett esetszám: rotavírus vs. bárányhimlő, 2012–2025") +
    theme(legend.position = "top", legend.text = element_text(size = 7))
  ggsave(file.path(FIGDIR, "fig13_national_context.pdf"), p13, width = 7.0, height = 2.9)
  macro("rotaAnnPre", a[year == 2019, rotavirus], big = TRUE)
  macro("rotaAnnXs",  a[year == 2024, rotavirus], big = TRUE)
  macro("variAnnPre", a[year == 2019, varicella], big = TRUE)
  macro("variAnnXs",  a[year == 2024, varicella], big = TRUE)
  macro("annYearMin", as.character(min(a$year)))
}

saveRDS(list(D = D, A = A, EQ = EQ, tor = tor, psa = psa, etas = etas, robust = robust,
             q_need = q_need, muni_map = muni_map, proxy = proxy, base_cost_mrd = base_cost_mrd,
             ce = ce), file.path(RESULTS, "_state_08.rds"))
flush_macros(file.path(TABDIR, "_numbers.tex"))
message("    tornado/psa/robust/twoway/costeff + fig7/7b/8/11/12/13 written")
