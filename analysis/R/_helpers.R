# Shared helpers for the analysis pipeline. Sourced by every numbered script.
# Mirrors analysis/python/run_analysis.py so the two implementations agree.

suppressPackageStartupMessages({
  library(arrow)      # read_parquet
  library(data.table)
  library(jsonlite)
  library(yaml)
  library(ggplot2)
  library(stringi)
  library(gridExtra)   # grid.arrange for the two-panel figures
})

`%||%` <- function(a, b) if (is.null(a) || length(a) == 0) b else a

## ---- inequality / concentration statistics -------------------------------

gini <- function(x) {
  x <- sort(x[is.finite(x)])
  n <- length(x)
  if (n == 0 || sum(x) == 0) return(NA_real_)
  idx <- seq_len(n)
  (2 * sum(idx * x) - (n + 1) * sum(x)) / (n * sum(x))
}

cv <- function(x) {
  x <- x[is.finite(x)]
  if (length(x) < 2 || mean(x) == 0) return(NA_real_)
  stats::sd(x) / mean(x)
}

# Concentration index of `aid` ordered by ascending `rank_var` (need).
# +1 => all aid to the highest-need unit; 0 => proportional; <0 => regressive.
concentration_index <- function(aid, rank_var) {
  ok <- is.finite(aid) & is.finite(rank_var)
  aid <- aid[ok]; rank_var <- rank_var[ok]
  o <- order(rank_var)
  a <- aid[o]
  n <- length(a)
  if (sum(a) == 0) return(NA_real_)
  frac_rank <- (seq_len(n) - 0.5) / n
  mu <- mean(a)
  2 / (n * mu) * sum((frac_rank - mean(frac_rank)) * (a - mu))
}

# Theil T decomposition: returns total / between / within for groups.
theil_decomp <- function(x, groups) {
  keep <- x > 0
  x <- x[keep]; groups <- groups[keep]
  mu <- mean(x)
  total <- mean((x / mu) * log(x / mu))
  between <- 0; within <- 0
  for (g in unique(groups)) {
    xi <- x[groups == g]
    si <- sum(xi) / sum(x)
    mui <- mean(xi)
    between <- between + si * log(mui / mu)
    within  <- within  + si * mean((xi / mui) * log(xi / mui))
  }
  list(total = total, between = between, within = within)
}

lorenz_points <- function(x) {
  x <- sort(x)
  cc <- cumsum(x)
  if (utils::tail(cc, 1) > 0) cc <- c(0, cc) / utils::tail(cc, 1)
  else cc <- seq(0, 1, length.out = length(x) + 1)
  list(p = seq(0, 1, length.out = length(x) + 1), L = cc)
}

zscore <- function(x) (x - mean(x, na.rm = TRUE)) / stats::sd(x, na.rm = TRUE)
minmax <- function(x) (x - min(x, na.rm = TRUE)) / (max(x, na.rm = TRUE) - min(x, na.rm = TRUE))

# Dirichlet draw via independent gammas (no extra package dependency).
rdirichlet1 <- function(alpha) { g <- stats::rgamma(length(alpha), alpha, 1); g / sum(g) }

# numpy-style z-score on a plain vector (0 if degenerate)
zscore_np <- function(x) {
  s <- stats::sd(x, na.rm = TRUE)
  if (is.na(s) || s == 0) return(rep(0, length(x)))
  (x - mean(x, na.rm = TRUE)) / s
}

# percentile bootstrap CI for fn(*resampled columns); mirrors run_analysis.boot_ci
boot_ci <- function(fn, ..., reps = 2000, seed = 20260101, alpha = 0.05) {
  cols <- list(...); n <- length(cols[[1]])
  set.seed(seed)
  out <- vapply(seq_len(reps), function(i) {
    idx <- sample.int(n, n, replace = TRUE)
    tryCatch(fn(lapply(cols, function(c) c[idx])), error = function(e) NA_real_)
  }, numeric(1))
  out <- out[is.finite(out)]
  c(lo = unname(stats::quantile(out, alpha / 2)),
    hi = unname(stats::quantile(out, 1 - alpha / 2)))
}

# Mazziotta-Pareto index from a named list of z-scored dimension vectors -> minmax
mpi_from_z <- function(zcols, weights) {
  dims <- names(zcols)
  Rm <- sapply(dims, function(d) 100 + 10 * zcols[[d]])
  wv <- unlist(weights[dims])
  mbar <- as.numeric(Rm %*% wv) / sum(wv)
  msd  <- sqrt(((Rm - mbar)^2 %*% wv) / sum(wv))
  m <- mbar - msd * (msd / mbar)
  (m - min(m)) / (max(m) - min(m))
}

normalise_budget <- function(raw, budget) {
  raw <- pmax(raw, 0)
  tot <- sum(raw)
  if (tot > 0) raw / tot * budget else rep(0, length(raw))
}

## ---- name normalisation (settlement / county) ---------------------------

strip_accents <- function(s) stri_trans_general(s, "Latin-ASCII")

norm_txt <- function(s) {
  s <- tolower(strip_accents(as.character(s)))
  s <- gsub("[.,-]", " ", s)
  trimws(gsub("\\s+", " ", s))
}

norm_settlement <- function(s) {
  s <- norm_txt(s)
  roman <- c(i=1,ii=2,iii=3,iv=4,v=5,vi=6,vii=7,viii=8,ix=9,x=10,xi=11,xii=12,
             xiii=13,xiv=14,xv=15,xvi=16,xvii=17,xviii=18,xix=19,xx=20,xxi=21,xxii=22,xxiii=23)
  out <- vapply(s, function(z) {
    m <- regmatches(z, regexec("^budapest\\s+(\\d{1,2})\\b", z))[[1]]
    if (length(m) == 2) return(sprintf("budapest %02d", as.integer(m[2])))
    m <- regmatches(z, regexec("^budapest\\s+([ivx]+)\\b", z))[[1]]
    if (length(m) == 2 && !is.na(roman[m[2]])) return(sprintf("budapest %02d", roman[[m[2]]]))
    z <- gsub("kerulet|\\bker\\b", " ", z)
    trimws(gsub("\\s+", " ", z))
  }, character(1), USE.NAMES = FALSE)
  out
}

norm_county <- function(s) {
  s <- norm_txt(s)
  s <- trimws(gsub("\\s+", " ", gsub("varmegye|megye|\\bvm\\b|fovaros", " ", s)))
  ifelse(s %in% c("budapest", "bp", ""), "budapest", s)
}

## ---- LaTeX output helpers ---------------------------------------------------

.latexify <- function(s) {
  s <- as.character(s)
  s <- gsub("&", "\\\\&", s); s <- gsub("%", "\\\\%", s); s <- gsub("_", "\\\\_", s)
  greek <- c("π"="$\\pi$","τ"="$\\tau$","λ"="$\\lambda$","η"="$\\eta$",
             "μ"="$\\mu$","κ"="$\\kappa$","ρ"="$\\rho$","–"="--")
  for (k in names(greek)) s <- gsub(k, greek[[k]], s, fixed = TRUE)
  s
}

write_latex_table <- function(path, df, header, align, caption, label) {
  con <- file(path, open = "w", encoding = "UTF-8")
  on.exit(close(con))
  wl <- function(...) writeLines(paste0(...), con)
  wl("\\begin{table}[htbp]"); wl("\\centering"); wl("\\small")
  wl("\\caption{", caption, "}"); wl("\\label{", label, "}")
  wl("\\begin{tabular}{", align, "}"); wl("\\toprule")
  wl(paste(header, collapse = " & "), " \\\\"); wl("\\midrule")
  for (i in seq_len(nrow(df))) {
    wl(paste(vapply(df[i, ], .latexify, character(1)), collapse = " & "), " \\\\")
  }
  wl("\\bottomrule"); wl("\\end{tabular}"); wl("\\end{table}")
}

# LaTeX \newcommand macro registry ----------------------------------------
.NUM <- new.env(parent = emptyenv())
macro <- function(name, value, digits = NULL, plus = FALSE, big = FALSE) {
  if (is.character(value)) { s <- value } else {
    s <- if (!is.null(digits)) formatC(value, format = "f", digits = digits, big.mark = if (big) "\\," else "")
         else formatC(round(value), format = "d", big.mark = "\\,")
    if (plus && value >= 0) s <- paste0("+", s)
  }
  assign(name, s, envir = .NUM)
}
flush_macros <- function(path) {
  nm <- sort(ls(.NUM))
  writeLines(sprintf("\\newcommand{\\%s}{%s}", nm, vapply(nm, get, "", envir = .NUM)),
             con = file(path, encoding = "UTF-8"))
}
