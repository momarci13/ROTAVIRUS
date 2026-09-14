# ROTAVIRUS — TDK 2026 beadásra kész csomag

Corvinus TDK 2025/26 versenyfelhívás szerint formázott dolgozat és a hozzá
tartozó, végponttól végpontig újrafuttatható elemzés.

## Mi hol van

| Útvonal | Tartalom |
|---|---|
| `analysis/paper/paper.tex` | a dolgozat forrása |
| `analysis/paper/paper.pdf` | **a beadásra kész dolgozat** |
| `analysis/paper/tdk.sty` | a TDK formai követelményeit megvalósító LaTeX csomag |
| `analysis/paper/tables/` | generált táblázatok + `_numbers.tex` (153 számmakró) |
| `analysis/paper/figures/` | generált ábrák |
| `analysis/python/run_analysis.py` | a teljes elemzés (ez generál minden számot) |
| `analysis/R/` | ugyanaz R-ben, párhuzamos implementáció |
| `analysis/config/` | paraméterek (költség, szükségletindex, érzékenység) |
| `analysis/results/` | köztes eredmény-CSV-k |
| `data/` | a pipeline parquet-kimenetei (a projekt gyökeréből) |

## Újrafuttatás

```bash
cd analysis/python && python3 run_analysis.py     # számok, ábrák, táblák
cd ../paper && ./forditas.sh                               # paper.pdf
```

Függőségek: `pandas numpy scipy matplotlib pyarrow pyyaml`, TeX Live
(`texlive-lang-european`, `texlive-fonts-extra`, `tex-gyre`).
A Monte-Carlo lépések magja rögzített (`analysis/config/analysis.yaml → seed`),
így a futás bitre azonos számokat ad.

## Mi változott a korábbi változathoz képest

**Formai (a versenyfelhívás szerint), mind a `tdk.sty`-ban:**

- 12 pontos Times New Roman, 1,5-ös sortávolság, 2,5 cm margó, sorkizárt.
- Oldalszám a lap alján középen; az oldalszámozás a Bevezetéssel indul 1-től.
- Decimális fejezetszámozás: `I.` / `I.2.` / `I.2.3.`
- Új, 14 pontos borító: szerző, szak, évfolyam, cím, témavezető.
- Minden ábra és táblázat alatt sorszám + cím + **forrás**.
- Félkövér kiemelés a folyószövegből kivéve (a felhívás csak dőltet enged).

**Szerkezeti:**

- Borító → Absztrakt → Vezetői összefoglaló → Tartalomjegyzék → Bevezetés →
  tartalmi fejezetek → Összefoglalás → Irodalomjegyzék → Mellékletek.
- „Következtetések" → „Összefoglalás" (a felhívás szóhasználata).
- Fogalomtár és Reprodukálhatóság a Mellékletekbe került (A, B).
- Új C melléklet: **nyilatkozat a mesterséges intelligencia használatáról**
  (a felhívás kötelező eleme) — kitöltendő.
- Új D melléklet: eredetiségi nyilatkozat.
- Az absztrakt a felhívás három kötelező elemére átírva: kutatási kérdés /
  módszertan / saját eredmények. Hossza 1515 karakter (követelmény 500–2500),
  a saját eredmények része 416 karakter (követelmény max. 500).

**Hivatkozás:**

- natbib `[numbers]` → **szerző–év** (Harvard/APA), ahogy a felhívás kéri.
- A hivatkozáslista APA-formátumú, ezért „et al." szerepel benne. Ha a
  szekcióban magyaros „és mtsai" az elvárt, a `paper.bbl`-ben cserélhető.

**Kód:**

- `run_analysis.py` — `hu_num()`: magyar számtipográfia minden generált számban
  és táblacellában (tizedesvessző, ezres helyiértékben vékony szóköz).
  A 153 számmakró **értéke bitre azonos** maradt, csak az írásmód változott.
- `run_analysis.py` — `write_table()`: a sorszám, a cím és a forrás a táblázat
  **alá** kerül, és minden táblázathívás kapott saját `source=` szöveget.
- Egy keménykódolt „lásd 3.4" fejezethivatkozás javítva (a decimális
  számozás miatt már nem stimmelt).

## Kitöltendő beadás előtt

A `paper.tex` elején, a borító mezőiben:

```latex
\tdkszerzo{...}  \tdkszak{...}  \tdkevfolyam{...}
\tdktemavezeto{...}  \tdkszekcio{...}
```

Továbbá a C melléklet (MI-nyilatkozat) szögletes zárójeles mezői.

## Terjedelem

30 oldal összesen, ebből 25 számozott. A tartalmi rész ~22 oldal.
Közgazdaságtudományi szekció: max. 80 oldal. Társadalomtudományi: max. 60,
tartalmi rész 20–40. Mindkettőnek megfelel.
