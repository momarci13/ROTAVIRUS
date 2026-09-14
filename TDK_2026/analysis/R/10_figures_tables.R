# 10 — assemble the LaTeX table fragments from analysis/results/*.csv and
#      write the final analysis/paper/tables/_numbers.tex.

if (!exists("ANALYSIS")) source(file.path("analysis", "R", "00_setup.R"))
message("[10] LaTeX tables ...")

fmt_range <- function(lo, hi) ifelse(hi < 10, sprintf("%.2f--%.2f", lo, hi),
                                     paste0(formatC(lo, format = "d", big.mark = "\\,"), "--",
                                            formatC(hi, format = "d", big.mark = "\\,")))

rdl <- if (!is.null(POPAGE)) "100\\,000 gyermek (0--14)" else "100\\,000 munkavállalási korú fő"

## T1 — data sources ------------------------------------------------------
t1 <- data.table(
  Blokk = c("Rotavírus-surveillance", "Rotavírus éves kontroll", "Országos idősor",
            "Gyermeknépesség", "Munkaerőpiac", "Alapellátási kapacitás",
            "Fejlettségi mutató", "Árindex (deflátor)", "Közigazgatási térkép",
            "Önkorm. oltástámogatás", "Költségparaméterek"),
  Forrás = c("NNGYK heti tájékoztató", "NNGYK OSAP éves jelentés",
             "KSH STADAT 4.1.1.31 / 4.2.1.1", "KSH STADAT 22.1.2.2",
             "NFSZ településsoros álláskeresők", "OKFŐ betöltetlen körzetek",
             "290/2014. Korm. r. 2--3. mell.", "KSH STADAT 1.1.1.1 / 1.1.1.3",
             "KSH TSZJ 2022/2025", "önkorm. rendeletek (Jogtár)",
             "NEAK közlemények + szakirodalom"),
  Felbontás = c("vármegye × ISO-hét", "vármegye × év", "ország, év / hó",
                "vármegye × korcsop. × év", "település × hó → járás",
                "település × pillanatkép → járás", "járás", "országos, éves",
                "járás, település", "önkormányzat", "—"),
  Időszak = c("2017–2026", "2024", "2012–2025", "2001–2026", "2019–2026",
              "2021–2026", "2014", "2001–2025", "2022, 2025", "eseti", "2024–2025"),
  Bizonyíték = c(rep("observed", 10), "assumed/estim."))
write_latex_table(file.path(TABDIR, "t1_sources.tex"), t1,
  c("Blokk", "Forrás", "Felbontás", "Időszak", "Biz."),
  "p{2.5cm}p{3.7cm}p{4.0cm}p{1.8cm}p{1.6cm}",
  paste0("Az elemzésben felhasznált adatforrások. Minden rotavírus-esetszám ",
         "vármegyei felbontásban megfigyelt; a járási bontás modellezett."), "tab:sources")

## T2 — cost parameters -------------------------------------------------
cp <- fread(file.path(RESULTS, "cost_parameters.csv"))
cp[, b := ifelse(base < 10, sub("\\.?0+$", "", sprintf("%.2f", base)),
                 formatC(base, format = "d", big.mark = "\\,"))]
cp[, rng := fmt_range(low, high)]
write_latex_table(file.path(TABDIR, "t2_cost_parameters.tex"),
  cp[, .(desc, b, rng, evidence, confidence)],
  c("Paraméter", "Alap", "Tartomány", "Bizonyíték", "Megbízh."),
  "p{5.4cm}rp{2.9cm}ll",
  paste0("Költségparaméterek: alap- és érzékenységi tartomány, bizonyíték-osztály és ",
         "megbízhatóság. Minden érték az elemzési réteg átlátható feltevése (lásd 3.4)."),
  "tab:cost")

## T3 — county cross-section ------------------------------------------
ct <- fread(file.path(RESULTS, "county_cross_section.csv"))
for (j in 2:3) set(ct, j = j, value = sprintf("%.1f", ct[[j]]))
write_latex_table(file.path(TABDIR, "t3_county_xs.tex"), ct,
  c("Mutató", names(ct)[2], names(ct)[3]), "p{6.2cm}rr",
  sprintf(paste0("Vármegyei rotavírus eset-ráta (eset / %s) keresztmetszete, %s és %s. ",
                 "A nevező a KSH vármegyei 0--14 éves népessége."), rdl, PRE, YEAR), "tab:countyxs")

## T4 — need top 10 ---------------------------------------------------
nt <- fread(file.path(RESULTS, "need_top10.csv"))
t4 <- data.table(Járás = nt$district_name, Vármegye = nt$county_name,
  Szükséglet = sprintf("%.3f", nt$need_score),
  `Beteg.` = sprintf("%+.2f", nt$score_disease),
  `Szoc.` = sprintf("%+.2f", nt$score_socioeconomic),
  `Kap.` = sprintf("%+.2f", nt$score_healthcare),
  `$\\lambda$ (eset)` = sprintf("%.0f", nt$lambda))
write_latex_table(file.path(TABDIR, "t4_need_top10.tex"), t4, names(t4), "llrrrrr",
  "A tíz legmagasabb összetett szükségletindexű járás és a dimenzió-pontszámok (z-score).",
  "tab:needtop")

## T5 — equity -----------------------------------------------------
eq <- fread(file.path(RESULTS, "equity.csv"))
t5 <- data.table(Forgatókönyv = eq$label,
  `Gini(támog.)` = sprintf("%.3f", eq$gini_aid),
  `CI$_{sz}$` = sprintf("%+.3f", eq$ci_need),
  `CI$_{szoc}$` = sprintf("%+.3f", eq$ci_socio),
  Kakwani = sprintf("%+.3f", eq$kakwani_need),
  `Theil köz. (\\%)` = sprintf("%.0f", 100 * eq$theil_between_share),
  `Legr. kvint. (\\%)` = sprintf("%.1f", 100 * eq$worst_quintile_share))
write_latex_table(file.path(TABDIR, "t5_equity.tex"), t5, names(t5), "p{3.5cm}rrrrrr",
  paste0("Méltányossági mérőszámok forgatókönyvenként. CI$_{sz}$: koncentrációs index a ",
         "szükséglet-rang szerint (pozitív = progresszív); CI$_{szoc}$: a szocioökonómiai ",
         "rang szerint; Theil köz.: a vármegyék közötti egyenlőtlenség részaránya."),
  "tab:equity")

## T6 — Spearman ----------------------------------------------------
sp <- fread(file.path(RESULTS, "scenario_spearman.csv"))
lab <- function(x) sub(" .*", "", SCN_LABELS[x])
sp[, rn := lab(rn)]
setnames(sp, names(sp)[-1], lab(names(sp)[-1]))
for (j in 2:ncol(sp)) set(sp, j = j, value = sprintf("%.2f", as.numeric(sp[[j]])))
setnames(sp, "rn", "")
write_latex_table(file.path(TABDIR, "t6_spearman.tex"), sp, names(sp),
  paste0("l", strrep("r", ncol(sp) - 1)),
  "A normált forgatókönyvek járási allokációinak Spearman-rangkorrelációja.", "tab:spearman")

## T7 — robust priority ------------------------------------------
rp <- fread(file.path(RESULTS, "robust_priority.csv"))
t7 <- data.table(Járás = rp$district_name, Vármegye = rp$county_name,
  `P(felső dec.)` = sprintf("%.2f", rp$p_top_decile),
  Szükséglet = sprintf("%.3f", rp$need_score),
  `$\\lambda$` = sprintf("%.0f", rp$lambda),
  `Álláskeresői ráta (\\%)` = sprintf("%.1f", 100 * rp$jobseeker_rate),
  `Bet.tlen körzet` = sprintf("%.0f", rp$vacant_paed))
write_latex_table(file.path(TABDIR, "t7_robust.tex"), head(t7, 20), names(t7), "llrrrrr",
  sprintf(paste0("Robusztus prioritási járások: P(felső decilis a szükségletben) $\\ge$ %.2f ",
                 "a Dirichlet-súlyújramintavételben (%d húzás)."), ROBUST_T, W_DRAWS),
  "tab:robust")

## T8 — tornado --------------------------------------------------
tor <- fread(file.path(RESULTS, "tornado.csv"))[order(-spread)]
t8 <- data.table(Tényező = tor$param,
  `Alsó (Mrd Ft)` = sprintf("%.2f", tor$low),
  `Felső (Mrd Ft)` = sprintf("%.2f", tor$high),
  `Terjedelem (Mrd Ft)` = sprintf("%.2f", tor$spread))
write_latex_table(file.path(TABDIR, "t8_tornado.tex"), t8, names(t8), "p{5.4cm}rrr",
  paste0("Egyváltozós érzékenység: a teljes társadalmi várható éves költség (Mrd Ft) az egyes ",
         "költségtényezők alsó/felső értéke mellett. Alapérték: \\baseCostMrd~Mrd Ft."),
  "tab:tornado")

## T9 — cost-effectiveness / break-even, top-10 need districts -----------
ce <- fread(file.path(RESULTS, "cost_effectiveness.csv"))[1:10]
t9 <- data.table(Járás = ce$district_name, Vármegye = ce$county_name,
  `Szüks.` = sprintf("%.3f", ce$need_score),
  Kohorsz = sprintf("%.0f", ce$birth_cohort),
  `Támogatás` = sprintf("%.1f", ce$subsidy_cost / 1e6),
  `Elkerült ktg.` = sprintf("%.1f", ce$averted_societal / 1e6),
  `H/K arány` = sprintf("%.2f", ce$benefit_cost_ratio))
write_latex_table(file.path(TABDIR, "t9_costeff.tex"), t9, names(t9), "llrrrrr",
  paste0("Egy szükségletarányos oltástámogatás állandósult állapotú éves megtérülése a tíz ",
         "legmagasabb szükségletindexű járásban (Támogatás és Elkerült ktg.\\ M~Ft/év). ",
         "H/K arány $>1$: a támogatás társadalmi szinten megtérül."), "tab:costeff")

## T10 — bootstrap CIs for the progressivity metrics --------------------
eb <- fread(file.path(RESULTS, "equity_bootstrap.csv"))
t10 <- data.table(Forgatókönyv = eb$label,
  `CI (szükséglet)` = sprintf("%+.3f [%+.3f; %+.3f]", eb$ci_need, eb$ci_lo, eb$ci_hi),
  Kakwani = sprintf("%+.3f [%+.3f; %+.3f]", eb$kakwani, eb$kak_lo, eb$kak_hi))
write_latex_table(file.path(TABDIR, "t10_bootstrap.tex"), t10, names(t10),
  "p{3.4cm}p{5.2cm}p{5.2cm}",
  paste0("A progresszivitási mérőszámok pontbecslése és 95\\%-os bootstrap ",
         "konfidenciaintervalluma (2000 járás-újramintavétel)."), "tab:bootstrap")

## T11 — specification-robust priority ---------------------------------
sr <- fread(file.path(RESULTS, "spec_robust.csv"))
sr <- sr[spec_top_count >= max(spec_n_specs) - 1][1:12]
t11 <- data.table(Járás = sr$district_name, Vármegye = sr$county_name,
  Szükségletindex = sprintf("%.3f", sr$need_score),
  `Felső decilis (spec. / összes)` = sprintf("%d / %d", sr$spec_top_count, sr$spec_n_specs))
write_latex_table(file.path(TABDIR, "t11_specrobust.tex"), t11, names(t11), "llrr",
  paste0("Specifikáció-robusztus prioritás: hány elemzési specifikációban (3 aggregálás + 3 ",
         "dimenzió-elhagyás + a hivatalos 290/2014 mutatóval való csere) kerül a járás a ",
         "szükségleti felső decilisbe."), "tab:specrobust")

flush_macros(file.path(TABDIR, "_numbers.tex"))
message("    tables t1..t11 + _numbers.tex written to ", TABDIR)
