# Run the whole analysis in order. From the repository root:
#     Rscript analysis/R/run_all.R
# or from analysis/R/:
#     Rscript run_all.R
#
# Reproduces every figure (analysis/paper/figures/*.pdf), LaTeX table fragment
# and analysis/paper/tables/_numbers.tex from the pipeline parquet outputs.
# Equivalent to analysis/python/run_analysis.py.

t0 <- Sys.time()
here <- if (file.exists("analysis/R/00_setup.R")) "analysis/R"
        else if (file.exists("00_setup.R")) "."
        else stop("run from the repo root or analysis/R/")

source(file.path(here, "00_setup.R"))
for (s in sprintf("%02d_%s.R", 1:10,
                  c("load", "descriptive", "district_burden", "need_index", "cost_model",
                    "allocation", "equity", "sensitivity", "policy_eval", "figures_tables"))) {
  message("\n=== ", s, " ===")
  source(file.path(here, s))
}
message(sprintf("\nDONE in %.1fs. Now compile the paper:\n  cd analysis/paper && latexmk -pdf paper.tex",
                as.numeric(difftime(Sys.time(), t0, units = "secs"))))
