# Elemzési terv

**Területi egyenlőtlenségek a gyermekkori rotavírus‑betegségteherben és egy
szükségletalapú járási támogatásallokációs keretrendszer Magyarországon
(2017–2026)**

Készült: Corvinus TDK‑dolgozat elemzési vázlata · a `ROTAVIRUS` adat‑pipeline
kimeneteire építve · 2026‑08‑29

---

## 1. Kutatási probléma és relevancia

A rotavírus okozta gastroenteritis a védőoltás előtti időszakban az 5 év alatti
gyermekek kórházi felvételeinek egyik vezető fertőző oka volt Magyarországon. A
rotavírus elleni oltás 2007 óta a magánpiacon elérhető, **nem része** a
kötelező (ingyenes) oltási rendnek, így a hozzáférést a szülői fizetőképesség és
az önkormányzati támogatási döntések határozzák meg. Ez a berendezkedés
földrajzilag egyenlőtlen betegségterhet és egyenlőtlen megelőzési kapacitást
eredményezhet: ott a legkisebb a lakossági oltási lefedettség, ahol a
szülők jövedelme alacsony és az önkormányzat nem tud támogatást nyújtani –
miközben éppen ezekben a járásokban a legrosszabb a gyermek‑alapellátás
lefedettsége (tartósan betöltetlen házi gyermekorvosi körzetek).

A dolgozat azt vizsgálja, **hogyan lehetne az állami támogatást a járások között
a tényleges szükséglet arányában elosztani**, és hogy a különböző elosztási
elvek mennyire méltányos, progresszív és robusztus eredményre vezetnek.

### Kutatási kérdések

- **K1.** Mekkora és hogyan alakult 2017 és 2026 között a bejelentett rotavírus‑
  megbetegedések **vármegyék közötti** egyenlőtlensége? Együtt mozog‑e a
  betegségteher a munkaerőpiaci depriváltsággal?
- **K2.** Járási szintre bontva (modellezett becslés) mekkora a betegségteher, a
  szocioökonómiai depriváltság és a gyermek‑alapellátási kapacitáshiány
  **együttes** szükséglete? Milyen a járások rangsora egy összetett
  szükségletindex szerint?
- **K3.** Nyolc elosztási forgatókönyv (status quo, egyenlő fejkvóta,
  epidemiológiai, szocioökonómiai, kapacitásalapú, teljes szükségletalapú,
  költségrés, jogszabályi küszöb) hogyan osztja el ugyanazt a 2,5 Mrd Ft‑os
  keretet? Mennyire tér el egymástól a járási allokáció és a rangsor?
- **K4.** Melyik forgatókönyv a leginkább **progresszív** a szükséglethez és a
  szocioökonómiai helyzethez képest (koncentrációs index, Kakwani‑index), és
  mekkora a vármegyék **közötti / vármegyéken belüli** egyenlőtlenség
  (Theil‑dekompozíció)?
- **K5.** Mennyire **robusztus** a szükségletalapú allokáció a
  költségparaméterek, a betegségteher‑bizonytalanság (±50%) és a dimenziósúlyok
  megválasztására? Mely járások maradnak *bármely* ésszerű beállítás mellett a
  prioritási (felső) decilisben?
- **K6.** Mennyire fedi egymást a szükségletalapú prioritási halmaz a
  290/2014. (XI. 26.) Korm. rendelet szerinti kedvezményezett járásokkal, és a
  jelenlegi (alulról szerveződő) **önkormányzati** rotavírus‑oltástámogatás
  mennyire igazodik a modellezett szükséglethez?

### Hipotézisek

- **H1.** A vármegyék közötti esetszám‑egyenlőtlenség (Gini) nem csökkent
  érdemben 2017–2026 között; a COVID‑időszak (2020–2021) átmeneti
  szintcsökkenést, de nem konvergenciát hozott.
- **H2.** A modellezett járási betegségteher pozitívan korrelál a
  munkanélküliségi rátával és a betöltetlen gyermekorvosi körzetek arányával –
  a három szükséglet‑dimenzió tehát *nem* kompenzálja egymást (halmozott
  hátrány).
- **H3.** Az epidemiológiai és a teljes szükségletalapú célzás lényegesen
  progresszívebb (magasabb pozitív koncentrációs index a szükséglet szerint),
  mint az egyenlő fejkvóta vagy a status quo; a status quo gyakorlatilag
  semleges vagy enyhén regresszív.
- **H4.** A prioritási (felső decilis) járások halmaza a súlyok és a
  költségparaméterek széles tartományában stabil (Jaccard‑hasonlóság > 0,7 a
  Dirichlet‑újramintavételben).
- **H5.** A jelenlegi önkormányzati támogatás lefedettsége elenyésző (<5% a
  járásoknak), és nincs érdemi korrelációja a modellezett szükséglettel.

---

## 2. Adatforrások és fedettség

| Blokk | Forrás (kollektor) | Felbontás | Időszak | Bizonyíték‑osztály |
|---|---|---|---|---|
| Rotavírus‑surveillance | NNGYK heti tájékoztató (`nngyk`) | vármegye × ISO‑hét | 2017–2026\* | `observed` |
| Munkaerőpiac | NFSZ településsoros nyilvántartott álláskeresők (`nfsz`) | település × hó → járás | 2019–2026 | `observed` |
| Alapellátási kapacitás | OKFŐ tartósan betöltetlen körzetek (`okfo`) | település × pillanatkép → járás | 2021–2026 | `observed` |
| Árindexek (deflátor) | KSH STADAT ár‑témakör (`ksh`) | országos, éves | 2010–2025 | `observed` |
| Közigazgatási térkép | KSH TSZJ 2022/2025 (`geo`/`geography`) | járás, település | 2022, 2025 | `observed` |
| Jogszabályi keret | Nemzeti Jogszabálytár (`jogtar`) | — | — | `observed` |
| Önkormányzati oltástámogatás | önkormányzati rendeletek (`jogtar`) | önkormányzat | eseti | `observed` |
| Költségparaméterek | NEAK közlemények + szakirodalom | — | 2024–2025 | `assumed` / `estimated` |

\* 2017 és 2026 részleges év (34, ill. 33 hét). Elsődleges keresztmetszeti év:
**2024** (51 hét, teljes vármegyei fedettség). Pre‑COVID referencia: **2019**.
Trendelemzés: teljes 2017–2026 idősor, a részleges évek jelölésével.

### Az abszolút szabályok betartása

1. **Területi felbontás.** A rotavírus‑esetszám legfinomabb *megfigyelt*
   felbontása a vármegye. Minden járási esetszám **modellezett** (`_modelled`
   oszlopok, kötelező `_lo`/`_hi` sávval), `evidence_class = estimated`,
   `confidence = low`, ±50% hitelességi intervallummal.
2. **Bizonyíték‑osztályozás.** Minden numerikus mező mellé `evidence_class`
   kerül; minden `assumed`/`estimated` érték forrásmegjelöléssel és
   megbízhatósági szinttel szerepel (lásd `config/cost_parameters_analysis.yaml`).

### Ismert adatkorlátok (a dolgozat „Korlátok" fejezetébe)

- **Nincs közvetlen járási 0–4 éves népesség** az automatikusan begyűjtött
  adatban (KSH Helységnévkönyv / Tájékoztatási adatbázis manuális export).
  Helyettesítő: a járási **munkavállalási korú népesség** (NFSZ), mint
  populációsúly – feltételezve, hogy a korszerkezet vármegyén belül homogén.
  A dolgozat egy `district_u5_population.csv` beviteli helyet biztosít a valódi
  KSH‑adat utólagos behelyettesítéséhez, és érzékenységvizsgálatot közöl a
  súlyválasztásra.
- A `nngyk` heti PDF‑ekből 2014–2015‑re a táblázatkinyerés több héten nem
  sikerült (kézi kinyerési sor). Ezért az idősor 2017‑től indul.
- A 290/2014 kedvezményezett‑járás lista automatikus kinyerése nem adott
  használható járásneveket; a jogszabályi küszöb‑forgatókönyvhöz **proxy**
  jogosultsági szabályt használunk (a szocioökonómiai depriváltság legrosszabb
  harmada), és külön CSV‑sablont adunk a hiteles melléklet behelyettesítésére.
- A rotavírus‑esetszám **bejelentett** eset; a valós közösségi előfordulás
  többszöröse (aluljelentési szorzó – `assumed` paraméter,
  érzékenységvizsgálatban változtatva).
- Az OKFŐ‑pillanatképek 2021 előtt nem elérhetők; a kapacitásdimenzió a
  legfrissebb elérhető pillanatképből számol keresztmetszetet.

---

## 3. Módszertan

### 3.1 Adat‑előkészítés és területi harmonizáció

1. **Vármegyei éves esetszám.** `cases_{c,y} = Σ_hét value` a
   `county_weekly_epi` táblából (`variable = rotavirus_cases`).
2. **Település → járás hozzárendelés.** Normalizált településnév‑illesztés
   (`scraper.geography.crosswalk.normalise_name`) az NFSZ/OKFŐ nevek és a
   `geo_settlements` törzs között. Nem illesztett tételek naplózva, a fedettségi
   arány a függelékbe kerül. Kétértelmű nevek (azonos név több járásban)
   irányítószám alapján oldva.
3. **Járási populációsúly.** `pop_i` = a járás településeinek
   munkavállalási korú népessége (NFSZ, a vizsgált év havi átlaga).
4. **Deflálás.** A 2024‑es keresetalapú paraméterek 2025‑ös árszintre hozva a
   KSH bruttó keresetindexszel (`ksh` tábla, `price_earnings_index`), a
   `c_valós = c_nominális · P_2025 / P_év` képlettel.

### 3.2 Leíró elemzés (K1, H1)

- Országos heti bejelentett esetszám 2017–2026: szezonalitás, a 2020–2021‑es
  visszaesés, a 2024‑es és 2026‑os megugrás.
- Vármegyei éves eset‑ráta (eset / munkavállalási korú népesség · 100 000) –
  a ráta évenkénti **Gini‑együtthatója** és **variációs koefficiense**;
  a rangkorreláció stabilitása évek között (Spearman).
- Vármegyei choropleth (OSM‑határok) a 2024‑es és a pre‑COVID 2019‑es
  eset‑rátáról.
- A vármegyei betegségteher és a vármegyei munkanélküliségi ráta
  keresztmetszeti korrelációja (Pearson és Spearman), 2024.

### 3.3 Járási betegségteher‑becslés (K2)

Kis területi (small‑area) modell – **populációsúlyozott szétosztás + indirekt
kor‑standardizálás**:

```
λ_i = cases_{megye(i), y} · pop_i / Σ_{j ∈ megye(i)} pop_j
CI_i = [0,5 · λ_i ; 1,5 · λ_i]              (±50%, evidence_class = estimated)
```

Relatív betegségteher‑index: `burden_rate_i = λ_i / pop_i · 100 000`
(nem valódi u5‑incidencia – a hiányzó 0–4 éves nevező miatt a
munkavállalási korú népességre vetített relatív mérőszám).

Robusztussági változat: a populációsúly helyett egyenletes szétosztás, ill.
(ha rendelkezésre áll) a valódi 0–4 éves KSH‑népesség.

### 3.4 Költségmodell (K3, `assumed` paraméterekkel)

Egy bejelentett esetre jutó várható társadalmi költség:

```
c_fekvő   = alapdíj · HBCs_súly(gyermek gastroenteritis)
c_járó    = német_pont_érték · pont/eset  +  háziorvosi_vizit_költség
c_direkt  = h · c_fekvő + (1 − h) · c_járó                    (h = kórházi felvételi arány)
ProdLoss  = π_szülői · min(d_átlag, munkanap) · napi_bruttó_bér · (1 + τ)
c_eset    = c_direkt + ProdLoss
Ĉ_i       = λ_i · c_eset            (bejelentett alapon; társadalmi: · aluljelentési szorzó)
```

Minden paraméterhez **alap / alsó / felső** érték tartozik
(`config/cost_parameters_analysis.yaml`), forrásmegjelöléssel. A modell a
pipeline szabálya szerint **leáll**, ha egy kötelező paraméter hiányzik –
az elemzési réteg ezért külön, tételesen hivatkozott alap‑forgatókönyvet
definiál, nem a magmodul default értékeit.

### 3.5 Összetett szükségletindex (K2, H2)

Csökkentett, az elérhető adatokra szabott index
(`config/need_index_analysis.yaml`):

| Dimenzió | Súly\* | Változó(k) | Irány |
|---|---|---|---|
| Betegség | 0,41 | `burden_rate_i` (modellezett) | több = nagyobb szükséglet |
| Szocioökonómiai | 0,35 | `jobseeker_rate_i` | több = nagyobb szükséglet |
| Alapellátási kapacitás | 0,24 | `vacant_paed_practice_rate_i` | több = nagyobb szükséglet |

\* Az eredeti `need_index.yaml` 0,35 / 0,30 / 0,20 súlyainak arányos
újranormálása (a nem elérhető fiskális dimenzió elhagyásával).

- **Standardizálás:** z‑score (robusztussági változat: min–max, rang).
- **Aggregálás:** Mazziotta–Pareto index (MPI, nem kompenzáló, a horizontális
  szórást bünteti); robusztussági változat: súlyozott átlag és az entrópia‑
  súlyozás.
- Kimenet: `need_score_i` és a három rész‑pontszám; járási rangsor és térkép.

### 3.6 Elosztási forgatókönyvek (K3)

Egyetlen generikus allokációs függvény (`scraper.allocation.scenarios.
allocate_generic`) paraméterezései; keret **B = 2,5 Mrd Ft**, év = 2024.

| # | Név | Elv |
|---|---|---|
| 0 | Status quo | `Aid_i = meglévő önkormányzati támogatás_i` (nincs újraelosztás) |
| 1 | Egyenlő fejkvóta | `Aid_i = B · pop_i / Σ pop` |
| 2 | Epidemiológiai | `Aid_i = B · λ_i / Σ λ` |
| 3 | Szocioökonómiai | `Aid_i ∝ pop_i · S_i` (S = szocioökon. rész‑pontszám) |
| 4 | Kapacitásalapú | `Aid_i ∝ pop_i · H_i` (H = kapacitás rész‑pontszám) |
| 5 | Teljes szükségletalapú | `Aid_i ∝ Ĉ_i · (1 + η · Ñ_i)`, B‑re normálva (η = 0,5) |
| 6 | Költségrés | `Aid_i = max(0, Ĉ_i − L_i)` – nem normált, a valós fiskális igényt mutatja |
| 7 | Jogszabályi küszöb (proxy) | csak a szocioökon. szempontból legrosszabb harmad; azon belül fejkvóta |

A fiskális kapacitás‑büntetést (κ) 0‑ra állítjuk (nincs járási fiskális
kapacitás‑adat), ezt a Korlátoknál jelezzük.

### 3.7 Méltányossági elemzés (K4, H3)

Forgatókönyvenként (`scraper.allocation.equity`):

- **Gini(Aid)** – az allokáció koncentrációja.
- **Koncentrációs index CI(Aid | szükséglet‑rang)** – a támogatás a
  magas‑szükségletű járásokhoz áramlik‑e (pozitív = progresszív).
- **CI(Aid | szocioökon. rang)** – pro‑poor‑e az elosztás.
- **Kakwani‑index** = CI(Aid) − Gini(szükséglet): progresszivitás a
  szükséglethez képest.
- **Theil‑dekompozíció**: vármegyék *közötti* vs. *belüli* egyenlőtlenség az
  allokációban.
- **A keret hányada a legrosszabb szükségleti kvintilisnek.**
- **Spearman‑rangkorrelációs mátrix** a hét (nem‑triviális) forgatókönyv járási
  allokációi között.
- **Felső‑decilis (kb. 20 járás) átfedés** (Jaccard) forgatókönyv‑párokra.

### 3.8 Érzékenységvizsgálat (K5, H4)

- **Egyváltozós (tornádó):** a „keret hányada a legrosszabb kvintilisnek" (5.
  forgatókönyv) érzékenysége η‑ra, a költségparaméterekre (±10/25/50%), az
  aluljelentési szorzóra és a ±50% betegségteher‑sávra.
- **Valószínűségi (PSA), 2000 húzás:** gamma a költségre, béta a kórházi
  felvételi arányra, lognormális a betegségteher‑szorzóra → a
  progresszivitási mérőszámok és a rangstabilitás eloszlása.
- **Dirichlet‑súlyújramintavétel, 2000 húzás** (koncentráció = 20) → járásonként
  P(felső‑decilis a szükségletben) → **„robusztus prioritási halmaz"** (a
  járások, amelyek a húzások ≥ 80%‑ában felső decilisben maradnak).

### 3.9 Szakpolitikai értékelés (K6, H5)

- A szükségletalapú prioritási halmaz (5. forgatókönyv felső kvintilise) és a
  290/2014‑proxy jogosult halmaz átfedése (Jaccard, konfúziós tábla).
- A modellezett betegségteher és a szocioökonómiai depriváltság együttállása
  (kétdimenziós tipológia: „halmozottan hátrányos" járások).
- Önkormányzati oltástámogatás: lefedettség (hány járásban van bármilyen
  támogatás), az összegek nagyságrendje, és a támogatás korrelációja a
  modellezett szükséglettel (koncentrációs index).
- Újraelosztási hatás: a 2. (epidemiológiai) vs. 1. (fejkvóta) forgatókönyv
  nyertes/vesztes járásai NUTS2‑régiónként.

---

## 4. Kimenetek (a dolgozathoz)

### Ábrák

1. Országos heti bejelentett rotavírus‑esetszám, 2017–2026 (szezonalitás + trend).
2. Vármegyei éves eset‑ráta Gini/CV idősora, 2017–2026.
3. Vármegyei eset‑ráta choropleth: 2019 vs. 2024.
4. Járási szükségletindex choropleth + a három rész‑pontszám kis sokszorosa.
5. Járási allokáció forgatókönyvenként (Lorenz‑görbék egy ábrán).
6. Koncentrációs index és Kakwani‑index forgatókönyvenként (pontdiagram hibasávval, PSA).
7. Tornádó‑ábra (5. forgatókönyv).
8. Dirichlet‑robusztusság: járásonkénti P(felső decilis) rendezett vonaldiagram + a robusztus halmaz térképe.
9. Szükségletalapú prioritás vs. 290/2014‑proxy: átfedési térkép.

### Táblázatok

1. Adatforrások, felbontás, időszak, bizonyíték‑osztály.
2. Költségparaméterek: alap / alsó / felső érték, forrás, `evidence_class`.
3. Leíró statisztikák: vármegyei eset‑ráta 2019 és 2024 (átlag, szórás, min, max, Gini).
4. A 10 legmagasabb szükségletindexű járás (rész‑pontszámokkal).
5. Méltányossági mérőszámok forgatókönyvenként (Gini, CI\_szükséglet, CI\_szocioökon., Kakwani, Theil‑közötti/belüli, kvintilis‑részesedés).
6. Forgatókönyvek közötti Spearman‑ és Jaccard‑mátrix.
7. Robusztus prioritási járások (Dirichlet ≥ 0,8 és ±50% sáv mellett is felső decilis).
8. Érzékenységi tartományok (tornádó számszerű táblája).

### Reprodukálhatóság

- Minden ábra/tábla a `analysis/R/` szkriptekből (vagy a párhuzamos
  `analysis/python/run_analysis.py`‑ból) regenerálható a `data/processed/` és
  `data/intermediate/` parquet‑ekből.
- A szkriptek `analysis/results/` alá írják a köztes CSV‑ket és
  `analysis/paper/tables/_numbers.tex` alá a dolgozatban `\input`‑tal behúzott
  számmakrókat.
- Seed: `config/seed` (20260101) minden Monte‑Carlo lépéshez.

---

## 5. Munkamenet és szkriptek

| Szkript | Feladat | Fő kimenet |
|---|---|---|
| `R/00_setup.R` | csomagok, útvonalak, seed, segédfüggvények betöltése | — |
| `R/01_load.R` | parquet‑ek beolvasása, település→járás crosswalk | `results/harmonised_*.csv` |
| `R/02_descriptive.R` | K1: országos idősor, vármegyei egyenlőtlenség | `fig 1–3`, `tábla 3` |
| `R/03_district_burden.R` | K2: kis területi becslés + CI | `results/district_burden.csv` |
| `R/04_need_index.R` | K2: MPI szükségletindex + rész‑pontszámok | `fig 4`, `tábla 4`, `results/need_index.csv` |
| `R/05_cost_model.R` | K3: várható költség/eset és Ĉ_i, deflálás | `tábla 2`, `results/cost_panel.csv` |
| `R/06_allocation.R` | K3: 8 forgatókönyv | `fig 5`, `results/allocation.csv` |
| `R/07_equity.R` | K4: Gini, CI, Kakwani, Theil, Spearman, Jaccard | `fig 6`, `tábla 5–6` |
| `R/08_sensitivity.R` | K5: tornádó, PSA, Dirichlet | `fig 7–8`, `tábla 7–8` |
| `R/09_policy_eval.R` | K6: 290/2014‑proxy, önkormányzati támogatás | `fig 9`, `results/policy_eval.csv` |
| `R/10_figures_tables.R` | végső ábra/tábla export a `paper/`‑be | `paper/figures/*`, `paper/tables/*` |
| `R/run_all.R` | a fentiek sorban | teljes újrafuttatás |

---

## 6. Várható hozzájárulás

1. Az első **reprodukálható, járási felbontású** adat‑ és elemzési keret a
   magyar gyermekkori rotavírus‑betegségteher és a hozzá rendelhető állami
   támogatás vizsgálatára, a megfigyelt/becsült/feltételezett adatok explicit
   szétválasztásával.
2. A betegségteher, a szocioökonómiai depriváltság és az alapellátási
   kapacitáshiány **együttes** (nem kompenzáló) szükségletként való kezelése.
3. Nyolc elosztási elv egységes, ugyanazon a kereten végzett összehasonlítása
   méltányossági és progresszivitási mérőszámokkal, teljes
   érzékenységvizsgálattal.
4. Szakpolitikai tanulság: a jelenlegi (alulról szerveződő önkormányzati)
   finanszírozási minta és a modellezett szükséglet viszonyának kvantifikálása.

---

## 7. Kiegészítés — az elemzési réteg magasabb felbontású bemenetei

A terv első változata több ponton proxyval dolgozott. Az
`analysis/python/acquire_extra.py` ezeket a már letöltött nyers forrásokból
kinyert, forrásmegjelölt adatokkal váltja fel (`analysis/data/`,
`_provenance.json`):

| Bemenet | Forrás | Mit vált fel | Hol jelenik meg |
|---|---|---|---|
| Vármegyei 0–14 éves népesség, évente | KSH STADAT 22.1.2.2 | a betegségteher‑ráta munkavállalási korú nevezője → **gyermeknépesség** | 3.1, 3.2, 3.3 |
| 290/2014. Korm. r. **valós** 2–3. melléklet (197 járás komplex mutatója + 109 kedvezményezett) | Jogtár (hatályos szöveg) | a 7. forgatókönyv **proxy** jogosultsága; egyben a szükségletindex **külső érvényességi** mércéje | 3.5, 3.6, 3.9 |
| Egészségügyi ágazati CPI, 2025‑ös bázisra láncolva | KSH STADAT 1.1.1.3 (COICOP 6) | a fix 1,09‑es deflátor‑feltevés dokumentált kiegészítése | 3.4 |
| Vármegyei éves rotavírus‑esetszám (OSAP) | NNGYK OSAP éves jelentés | *kereszt‑ellenőrzés* a heti NNGYK‑összegekre (Pearson ≈ 0,90) | 3.2 |
| Országos éves fertőző‑betegség idősor (rotavírus vs. bárányhimlő) | KSH STADAT 4.1.1.31 | narratív kontroll: a 2019‑től kötelező bárányhimlő‑oltás hatása | 4. (kontextus‑ábra) |

### Bővített elemzési lépések

- **3.2** — a vármegyei Gini formális trendtesztje (OLS a teljes évekre;
  meredekség 95%‑os CI‑vel, $p$‑érték); az OSAP‑kereszt‑ellenőrzés;
  bootstrap‑CI a keresztmetszeti Gini‑re.
- **3.5** — külső érvényesség: a szükségletindex és a 290/2014 komplex mutató
  rang‑ és Pearson‑korrelációja; a szocioökonómiai dimenzió cseréje a
  hivatalos mutatóra (rangsor‑stabilitás); **specifikáció‑robusztus** halmaz
  (3 aggregálás + 3 dimenzió‑elhagyás + a hivatalos mutató‑csere).
- **3.7** — a progresszivitási mérőszámok (koncentrációs index, Kakwani)
  95%‑os **bootstrap konfidenciaintervalluma** (2000 járás‑újramintavétel).
- **3.8** — **kétváltozós** érzékenység: a szükségleti rugalmasság ($\eta$) és
  az aluljelentési szorzó rácsa a koncentrációs indexre és az újraosztott
  keret arányára.
- **3.10 (új)** — **megtérülési (break‑even) elemzés**: egy szükségletarányos
  oltástámogatás állandósult állapotú éves társadalmi mérlege járásonként
  (haszon/költség arány; a magas szükségletű járásokban $>1$).

### Új kimenetek

- Ábrák: `fig10` külső érvényesség, `fig11` kétváltozós érzékenység,
  `fig12` megtérülés, `fig13` országos kontextus (rotavírus vs. bárányhimlő).
- Táblázatok: `t9` megtérülés (top‑10 járás), `t10` bootstrap‑CI‑k,
  `t11` specifikáció‑robusztus prioritás.
