# TDK 2026 — közös eszközök

| Fájl | Mire jó |
|---|---|
| `tdk.sty` | A Corvinus TDK 2025/26 versenyfelhívás összes formai követelménye egy LaTeX csomagban. Másold a dolgozat mappájába, és tedd a preambulumba: `\usepackage{tdk}` (magyar) vagy `\usepackage[english]{tdk}`. |
| `tdk_ellenorzes.py` | Végigellenőrzi a lefordított PDF-eket a felhívás szerint: betűméret, betűtípus, margó, sorköz, oldalszámozás, decimális fejezetszámozás, borító, absztrakt karakterszám, forrás minden ábra/táblázat alatt, hivatkozási stílus, kötelező nyilatkozatok, terjedelem. |

## tdk.sty — mit ad

```latex
\documentclass[12pt,a4paper]{article}
\usepackage[utf8]{inputenc}
\usepackage[magyar]{babel}
\usepackage{tdk}

\tdkev{2026}
\tdkszerzo{...}  \tdkszak{...}  \tdkevfolyam{...}
\tdktemavezeto{...}  \tdkszekcio{...}
\tdkcim{...}

\begin{document}
\tdkfrontmatter          % számozatlan előlap
\tdkborito               % 14 pontos borító (angolul: \tdkcover)
\begin{tdkabsztrakt} ... \end{tdkabsztrakt}
\tableofcontents
\tdkmaintext             % innentől arab oldalszám, 1-től
\section{Bevezetés}
...
\end{document}
```

Ábra/táblázat alá a kötelező forrás: `\forras{NNGYK adatai alapján saját szerkesztés}`

## Ellenőrzés

```bash
python tdk_ellenorzes.py
```

Az útvonalak a szkript tetején állíthatók. Függőség: `pdftotext`, `pdfinfo`,
`pdffonts` (poppler-utils).

## TeX-csomagok, amik kellenek

`texlive-lang-european` (magyar elválasztás), `texlive-fonts-extra` (newtx =
Times New Roman), `tex-gyre`, `texlive-latex-extra`, `texlive-plain-generic`.

## Lefedett projektek

A `tdk_ellenorzes.py` jelenleg tizenegy dolgozatot ellenőriz:

| Projekt | Mappa | Oldal | Nyelv |
|---|---|---|---|
| ROTAVIRUS | `ROTAVIRUS\TDK_2026\analysis\paper` | 30 | HU |
| BUDAPEST | `BUDAPEST\TDK_2026\paper` | 33 | EN |
| MFKAN | `mfkan_portfolio_v8\TDK_2026\paper` | 35 | EN |
| Spectral | `Spectral\TDK_2026\paper` | 22 | EN |
| regime_v2 | `regime_v2\TDK_2026\paper` | 31 | EN |
| OKTATÁS | `OKTATÁS\TDK_2026\paper` | 26 | HU |
| EGÉSZSÉGÜGY | `EGÉSZSÉGÜGY\TDK_2026\paper` | 32 | HU |
| NEM SZABAD ISKOLA | `NEM SZABAD ISKOLA\TDK_2026\analysis\paper` | 19 | HU ⚠️ szintetikus adat |
| STAT_test_MFKAN | `STAT_test_MFKAN\TDK_2026\paper` | 47 | EN |
| DARTS | `DARTS\TDK_2026\paper` | 20 | EN |
| Symbolic regression | `Symbolic regression\TDK_2026\paper` | 23 | EN |

⚠️ A NEM SZABAD ISKOLA dolgozat **nem adható be** a jelenlegi állapotában:
minden száma szintetikus fejlesztői fixtúrán fut. Részletek a projekt
`README_TDK.md` fájljában.
