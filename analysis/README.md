# `analysis/` — TDK-elemzés és dolgozat

Ez a mappa a `ROTAVIRUS` adat-pipeline kimeneteire épülő elemzést és a
Corvinus TDK-dolgozatot tartalmazza.

```
analysis/
├── PLAN.md                    részletes elemzési terv (magyar)
├── config/
│   ├── analysis.yaml          futtatási paraméterek (év, keret, seed, útvonalak)
│   ├── cost_parameters_analysis.yaml   átlátható költség-feltevések (alap/alsó/felső)
│   ├── need_index_analysis.yaml         csökkentett 3-dimenziós szükségletindex
│   └── kedvezmenyezett_jaras_290_2014_TEMPLATE.csv   (elavult; lásd data/ alább)
├── data/                      az elemzési réteg magasabb felbontású bemenetei
│   ├── _provenance.json       minden fájl forrása / bizonyíték-osztálya / letöltés dátuma
│   ├── _broken.json           a best-effort módon nem megszerzett elemek
│   ├── kedvezmenyezett_jaras_290_2014.csv     a 290/2014 VALÓS 2–3. melléklete (197 járás)
│   ├── ksh_county_population_by_age.csv       KSH vármegyei 0–14 / 15–64 / 65+ népesség
│   ├── ksh_national_annual_diseases.csv       KSH országos bejelentett fertőző betegségek, éves
│   ├── ksh_national_monthly.csv               ugyanaz, havi (2020–)
│   ├── ksh_price_indices.csv                  headline + egészségügyi CPI, 2025-ös bázisra láncolva
│   └── osap_county_annual_rotavirus.csv       NNGYK OSAP éves, vármegyei rotavírus (kontroll)
├── R/                         az elemzés R-ben (00–10 + run_all.R)
├── python/
│   ├── acquire_extra.py       a data/ mappa bemeneteit állítja elő (nyers forrásokból)
│   └── run_analysis.py        a teljes elemzés (ez fut le a leszállított számokhoz)
├── results/                   generált köztes CSV-k
└── paper/
    ├── paper.tex              a dolgozat (magyar, pdfLaTeX + babel)
    ├── hivatkozasok.bib
    ├── figures/               generált ábrák (PDF)
    └── tables/                generált LaTeX-táblatöredékek + _numbers.tex
```

## Újrafuttatás

Előfeltétel: lefutott adat-pipeline, azaz léteznek a
`data/processed/{county_weekly_epi,district_panel,geo_districts,geo_settlements}.parquet`
és a `data/intermediate/{nfsz,okfo,ksh}/*.parquet` fájlok
(lásd a gyökér `README.md` „collect" lépését).

### 0. lépés — az elemzési réteg bemenetei (mindkét pipeline használja)

```bash
python analysis/python/acquire_extra.py
```

Ez a már letöltött nyers forrásokból (`data/raw/jogtar/korm_290_2014.html`,
`data/raw/ksh/*.xlsx`, `data/intermediate/nngyk/osap_*`) kinyeri a
`analysis/data/` alá a magasabb felbontású bemeneteket, és forrásnaplót ír
(`_provenance.json`). Néhány elemet hálózatról próbál megszerezni
(KSH-korcsoportos népesség; járáshatár-geometria) — sikertelenség esetén
tisztán kihagyja és a `_broken.json`-ba naplózza. A `run_analysis.py` és az
R-pipeline is működik e fájlok nélkül (visszaesik a proxykra), de ezekkel
lényegesen robusztusabb.

### R-rel

```bash
# csomagok: arrow, data.table, jsonlite, yaml, ggplot2, stringi, gridExtra
Rscript analysis/R/run_all.R
```

A `run_all.R` sorban lefuttatja a `00_setup.R` … `10_figures_tables.R`
szkripteket; minden ábra a `paper/figures/`-be, minden táblatöredék és a
`_numbers.tex` a `paper/tables/`-be kerül. Az R-változat a Python-vezérlő
tükre; mivel ebben a környezetben nincs R telepítve, a **leszállított
számokat a `run_analysis.py` adja** (ez a referencia-implementáció).

### Pythonnal (ez adja a leszállított számokat)

```bash
python analysis/python/run_analysis.py
```

Csomagok: `pandas`, `numpy`, `scipy`, `matplotlib`, `pyyaml`, `pyarrow`,
`beautifulsoup4` (az `acquire_extra.py`-hoz), `requests`.
A Monte-Carlo lépések magja `config/seed` = `20260101`.

## A dolgozat fordítása

```bash
cd analysis/paper
latexmk -pdf paper.tex          # vagy: pdflatex; bibtex; pdflatex; pdflatex
```

A `paper.tex` a `tables/_numbers.tex` generált `\newcommand`-jait és a
`tables/t*.tex` táblatöredékeket húzza be, így minden közölt szám az adott
futásból származik.

## Mit old meg az elemzési réteg (`analysis/data/`)

| Bemenet | Mit ad | Mit vált fel |
|---|---|---|
| `ksh_county_population_by_age.csv` | KSH vármegyei 0–14 éves népesség évente | a betegségteher-ráta nevezője (munkavállalási korú → gyermek) |
| `kedvezmenyezett_jaras_290_2014.csv` | a 290/2014 **valós** 3. melléklete (109 kedvezményezett járás) + a hivatalos komplex fejlettségi mutató minden járásra | a 7. forgatókönyv proxy jogosultsági szabálya; egyben a szükségletindex **külső érvényességi** mércéje |
| `ksh_price_indices.csv` | láncolt egészségügyi CPI (2025 = 100) | a fix 1,09-es deflátor-feltevés (a bér-tag továbbra is explicit) |
| `osap_county_annual_rotavirus.csv` | független vármegyei éves esetszám | *kereszt-ellenőrzés* a heti NNGYK-összegekre (Pearson ≈ 0,90) |

Még pontosabb lenne a **valódi járási 0–4 éves népesség** (KSH-kutatószoba
vagy egyedi adatkérés) — a hely készen áll rá (`analysis/data/`).

## Legfontosabb korlátok

- A járási esetszám **modellezett** (populációsúlyozott szétosztás, ±50% sáv),
  nem megfigyelés; a becslés a korszerkezet vármegyén belüli homogenitását
  feltételezi.
- Az elemzés a **járás** szintjén zajlik → módosítható területi egység
  problémája és ökológiai következtetés (lásd `paper.tex` „Korlátok").
- Minden költségparaméter `assumed`/`estimated`, forrásmegjelöléssel; a NEAK /
  9-1993 NM r. hatályos értékei behelyettesítendők.
- Részletek: `PLAN.md` és `paper.tex` „Korlátok" fejezet.
