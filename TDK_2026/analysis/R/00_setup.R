# 00 — configuration, paths, seed. Sourced first by every step and by run_all.R.
#
# Run either from the repository root (`Rscript analysis/R/run_all.R`) or from
# inside analysis/R/. The block below resolves the analysis root in both cases.

.find_analysis_root <- function() {
  cands <- c("analysis", ".", "..", file.path("..", ".."))
  for (c in cands) if (file.exists(file.path(c, "config", "analysis.yaml")))
    return(normalizePath(c))
  stop("cannot locate analysis/config/analysis.yaml — run from the repo root or analysis/R/")
}
ANALYSIS <- .find_analysis_root()
ROOT     <- normalizePath(file.path(ANALYSIS, ".."))

if (!exists("gini")) source(file.path(ANALYSIS, "R", "_helpers.R"))

CFG    <- yaml::read_yaml(file.path(ANALYSIS, "config", "analysis.yaml"))
COSTS  <- yaml::read_yaml(file.path(ANALYSIS, "config", "cost_parameters_analysis.yaml"))
NEEDC  <- yaml::read_yaml(file.path(ANALYSIS, "config", "need_index_analysis.yaml"))

PROC    <- file.path(ROOT, "data", "processed")
INTER   <- file.path(ROOT, "data", "intermediate")
RESULTS <- file.path(ANALYSIS, "results")
FIGDIR  <- file.path(ANALYSIS, "paper", "figures")
TABDIR  <- file.path(ANALYSIS, "paper", "tables")
for (d in c(RESULTS, FIGDIR, TABDIR)) dir.create(d, showWarnings = FALSE, recursive = TRUE)

YEAR   <- as.integer(CFG$cross_section_year)
PRE    <- as.integer(CFG$pre_covid_year)
BUDGET <- as.numeric(CFG$budget_huf)
CI_HW  <- as.numeric(CFG$burden_ci_halfwidth)
TOP_SHARE <- as.numeric(CFG$need_top_share)
TOP_DEC   <- as.numeric(CFG$need_top_decile)
ETA       <- as.numeric(CFG$allocation_eta)
WAGE_DEFL <- as.numeric(CFG$wage_growth_2024_2025 %||% 1.09)
SEED      <- as.integer(CFG$sensitivity$seed)
PSA_DRAWS <- as.integer(CFG$sensitivity$psa_draws)
W_DRAWS   <- as.integer(CFG$sensitivity$weight_draws)
DIR_CONC  <- as.numeric(CFG$sensitivity$dirichlet_concentration)
ROBUST_T  <- as.numeric(CFG$sensitivity$robust_threshold)

UPTAKE_GAIN <- as.numeric(CFG$subsidy_uptake_gain %||% 0.60)

## analysis-layer enrichments (analysis/data/, produced by acquire_extra.py) ----
ADATA <- file.path(ANALYSIS, "data")
.opt_csv <- function(name) {
  p <- file.path(ADATA, name)
  if (file.exists(p)) as.data.table(fread(p)) else NULL
}
POP290  <- .opt_csv("kedvezmenyezett_jaras_290_2014.csv")
POPAGE  <- .opt_csv("ksh_county_population_by_age.csv")
PRICE   <- .opt_csv("ksh_price_indices.csv")
ANN_DIS <- .opt_csv("ksh_national_annual_diseases.csv")
MON_DIS <- .opt_csv("ksh_national_monthly.csv")
OSAPC   <- .opt_csv("osap_county_annual_rotavirus.csv")
if (!is.null(POP290)) POP290[, district_id := sprintf("%03d", as.integer(district_id))]
HAVE_290    <- !is.null(POP290) && nrow(POP290) >= 150
HAVE_POPAGE <- !is.null(POPAGE) && nrow(POPAGE) > 0

DEFL_MED <- 1.0
if (!is.null(PRICE) && all(c("year", "health_cpi_idx2025") %in% names(PRICE))) {
  p24 <- PRICE[year == 2024, health_cpi_idx2025]
  p25 <- PRICE[year == 2025, health_cpi_idx2025]
  if (length(p24) && length(p25) && !is.na(p24) && p24 != 0) DEFL_MED <- p25 / p24
}

set.seed(SEED)

theme_set(theme_minimal(base_size = 9) +
          theme(panel.grid.minor = element_blank(),
                plot.title = element_text(size = 9, face = "bold")))
PAL <- c(disease = "#c0504d", socioeconomic = "#1f4e79", healthcare = "#4f81bd",
         primary = "#1f4e79", accent = "#c0504d")

SCN_LABELS <- c(
  s0_statusquo = "0 · Status quo", s1_percapita = "1 · Egyenlő fejkvóta",
  s2_epi = "2 · Epidemiológiai", s3_socio = "3 · Szocioökonómiai",
  s4_capacity = "4 · Kapacitásalapú", s5_fullneed = "5 · Teljes szükségletalapú",
  s6_costgap = "6 · Költségrés", s7_statutory = "7 · Jogszabályi küszöb")
SCN <- names(SCN_LABELS)
NORMED <- setdiff(SCN, "s6_costgap")
TAGW <- c(s0_statusquo="Sq", s1_percapita="Pc", s2_epi="Epi", s3_socio="Soc",
          s4_capacity="Cap", s5_fullneed="Full", s6_costgap="Gap", s7_statutory="Stat")

message(sprintf("[00] setup: analysis year %d, pre-COVID %d, budget %.0f HUF, seed %d",
                YEAR, PRE, BUDGET, SEED))
