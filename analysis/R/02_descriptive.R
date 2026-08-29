# 02 — K1: national weekly series, county-level inequality over time,
#      cross-section, burden vs socioeconomic correlation.

if (!exists("ANALYSIS")) source(file.path("analysis", "R", "00_setup.R"))
st <- readRDS(file.path(RESULTS, "_state_01.rds")); list2env(st, environment())
message("[02] descriptive ...")

natw <- fread(file.path(RESULTS, "nat_weekly.csv"))
partial <- as.integer(CFG$partial_years)

p1 <- ggplot(natw, aes(t, value)) +
  geom_area(fill = PAL["primary"], alpha = 0.15) +
  geom_line(colour = PAL["primary"], linewidth = 0.35) +
  { if (length(partial)) annotate("rect", xmin = partial, xmax = partial + 1,
        ymin = -Inf, ymax = Inf, alpha = 0.06) } +
  labs(x = "Év", y = "Heti bejelentett eset",
       title = "Bejelentett rotavírus-gastroenteritis, országos heti esetszám (2017–2026)")
ggsave(file.path(FIGDIR, "fig1_national_weekly.pdf"), p1, width = 7.2, height = 2.9)

## county population + jobseekers (YEAR) for rates
cbase <- fread(file.path(RESULTS, "district_base.csv"))
county_pop <- cbase[, .(wap = sum(pop), jobseekers = sum(jobseeker_rate * pop)), by = county_id]

## rate denominator: observed county child pop (0-14) by year, else WA proxy
.cty_denom <- function(cid, y) {
  if (!is.null(CHILD_BY_CY)) {
    v <- CHILD_BY_CY[county_id == cid & year == y, population]
    if (!length(v)) v <- CHILD_BY_CY[county_id == cid][which.max(year), population]
    if (length(v)) return(as.numeric(v))
  }
  w <- county_pop[county_id == cid, wap]
  if (length(w)) as.numeric(w) else NA_real_
}

ineq <- rbindlist(lapply(as.integer(CFG$trend_years), function(y) {
  cc <- merge(county_cases[year == y], county_pop, by = "county_id")
  if (!nrow(cc)) return(NULL)
  cc[, denom := vapply(county_id, .cty_denom, numeric(1), y = y)]
  cc[, rate := cases / denom * 1e5]
  data.table(year = y, gini_rate = gini(cc$rate), cv_rate = cv(cc$rate),
             total_cases = sum(cc$cases), partial = y %in% partial)
}))
fwrite(ineq, file.path(RESULTS, "county_inequality_by_year.csv"))

## formal trend test: OLS of annual Gini on year, complete years only
full <- ineq[partial == FALSE]
if (nrow(full) >= 4) {
  fm <- stats::lm(gini_rate ~ year, data = full)
  co <- summary(fm)$coefficients["year", ]
  macro("giniTrendSlope",   co["Estimate"], digits = 4, plus = TRUE)
  macro("giniTrendSlopeLo", co["Estimate"] - 1.96 * co["Std. Error"], digits = 4, plus = TRUE)
  macro("giniTrendSlopeHi", co["Estimate"] + 1.96 * co["Std. Error"], digits = 4, plus = TRUE)
  macro("giniTrendP", co["Pr(>|t|)"], digits = 3)
  macro("giniTrendNyears", nrow(full))
}

p2 <- ggplot(ineq, aes(year)) +
  geom_line(aes(y = gini_rate, colour = "Gini (eset-ráta)")) +
  geom_point(aes(y = gini_rate, colour = "Gini (eset-ráta)",
                 shape = partial)) +
  geom_line(aes(y = cv_rate / 3, colour = "Variációs koeff. (/3)"), linetype = 2) +
  scale_shape_manual(values = c(`FALSE` = 16, `TRUE` = 1), guide = "none") +
  scale_colour_manual(values = c("Gini (eset-ráta)" = PAL["primary"],
                                 "Variációs koeff. (/3)" = PAL["accent"]), name = NULL) +
  labs(x = "Év", y = "Érték",
       title = "Vármegyék közötti egyenlőtlenség a rotavírus eset-rátában")
ggsave(file.path(FIGDIR, "fig2_county_inequality.pdf"), p2, width = 7.0, height = 2.9)

county_xs <- function(y) {
  cc <- merge(county_cases[year == y], county_pop, by = "county_id")
  cc[, denom := vapply(county_id, .cty_denom, numeric(1), y = y)]
  cc[, rate := cases / denom * 1e5][]
}
x19 <- county_xs(PRE); x24 <- county_xs(YEAR)
desc <- data.table(
  stat = c("Összes bejelentett eset", "Átlagos vármegyei eset-ráta / 100e", "Szórás",
           "Minimum", "Maximum", "Max / min arány", "Gini (ráta)"),
  a = c(sum(x19$cases), mean(x19$rate), sd(x19$rate), min(x19$rate), max(x19$rate),
        max(x19$rate) / min(x19$rate), gini(x19$rate)),
  b = c(sum(x24$cases), mean(x24$rate), sd(x24$rate), min(x24$rate), max(x24$rate),
        max(x24$rate) / min(x24$rate), gini(x24$rate)))
setnames(desc, c("a", "b"), c(as.character(PRE), as.character(YEAR)))
fwrite(desc, file.path(RESULTS, "county_cross_section.csv"))

cc24 <- merge(county_xs(YEAR), county_pop[, .(county_id, jobseekers)], by = "county_id")
cc24[, jsr := jobseekers / wap * 100]
r_ps <- stats::cor.test(cc24$rate, cc24$jsr)
r_sp <- suppressWarnings(stats::cor.test(cc24$rate, cc24$jsr, method = "spearman"))

macro("epiYears", "2017--2026"); macro("nWeeksTotal", nrow(natw))
macro("casesPre", sum(x19$cases), big = TRUE); macro("casesXs", sum(x24$cases), big = TRUE)
macro("giniPre", gini(x19$rate), digits = 3); macro("giniXs", gini(x24$rate), digits = 3)
macro("maxminPre", max(x19$rate) / min(x19$rate), digits = 1)
macro("maxminXs", max(x24$rate) / min(x24$rate), digits = 1)
macro("csYear", as.character(YEAR)); macro("preYear", as.character(PRE))
gb <- boot_ci(function(c) gini(c[[1]]), x24$rate, reps = 3000)
macro("giniXsLo", gb["lo"], digits = 3); macro("giniXsHi", gb["hi"], digits = 3)

## independent cross-check: OSAP annual county counts vs NNGYK weekly sums
if (!is.null(OSAPC)) {
  o <- copy(OSAPC)
  o[, county_id := county_id_by_norm[norm_county(county_name)]]
  oy <- o$year[1]
  m <- merge(o[!is.na(county_id)], county_cases[year == oy], by = "county_id")
  if (nrow(m) > 5) {
    macro("osapWeeklyPearson", cor(m$rotavirus_cases_osap, m$cases), digits = 3)
    macro("osapYear", as.character(oy))
    macro("osapTotal", sum(m$rotavirus_cases_osap), big = TRUE)
    macro("weeklySumTotal", sum(m$cases), big = TRUE)
  }
}
macro("countyBurdenSocioPearson", unname(r_ps$estimate), digits = 2)
macro("countyBurdenSocioPearsonP", r_ps$p.value, digits = 3)
macro("countyBurdenSocioSpearman", unname(r_sp$estimate), digits = 2)
flush_macros(file.path(TABDIR, "_numbers.tex"))
message("    fig1, fig2, tables 3 written")
