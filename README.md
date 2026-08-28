# Magyar járásszintű rotavírus-adatgyűjtő és támogatásallokációs pipeline

Reprodukálható Python adat-pipeline egy egészségpolitikai kutatáshoz. A rendszer
**nem végez elemzést** — az adatinfrastruktúrát adja, amelyből levezethető:

```
betegségteher → várható költség → szükségletpontszám → járási támogatási összeg
             → teljes állami kiadás → szakpolitikai értékelés
```

## Kutatási kérdés

> Hogyan allokálja Magyarország az állami támogatást a járások között a
> földrajzilag egyenlőtlen rotavírussal összefüggő ellátási és megelőzési
> szükségletek kezelésére, és mekkora lenne egy ilyen szükségletalapú allokációs
> rendszer fiskális költsége, várható haszna és szakpolitikai kompromisszuma?

A kutatócsoport a **szükségleti képletet, a súlyokat, a költségfeltevéseket, a
deflátorválasztást, a jogosultsági kritériumokat, a költségvetési korlátot és új
allokációs forgatókönyveket kizárólag a `config/*.yaml` fájlokból** módosítja — a
scraper átírása nélkül (lásd [Bővíthetőség](#bővíthetőség)).

---

## Két abszolút szabály

### 1. Területi felbontás

A publikusan elérhető **legfinomabb rotavírus-felbontás a vármegye** (19 vármegye
+ Budapest), heti bontásban, 2014-től. **Járásszintű esetszám nem publikus.** A
pipeline ezt kódszinten kikényszeríti:

- minden epidemiológiai rekordnak kötelező `geo_level` mezője van
  (`country` | `county` | `district`);
- a járási szintű **becsült** értékek külön, `*_modelled` nevű oszlopokba
  kerülnek, kötelező `*_lo` / `*_hi` (95% hitelességi intervallum) oszlopokkal;
- a validáció **hibát dob**, ha bárki `geo_level='district'` +
  `evidence_class='observed'` rotavírus-esetszámot próbál beírni — **kivéve** az
  `nngyk_foia` kollektort, amely a jövőben megérkező valódi járási adatot tölti
  be ugyanabba a sémába.

### 2. Bizonyíték-osztályozás

Minden numerikus mező mellett kötelező `evidence_class`:

| érték | jelentés |
| --- | --- |
| `observed` | magyar hivatalos forrásból közvetlenül kinyert érték (pl. NNGYK bejelentett esetszám, HBCs alapdíj) |
| `estimated` | megfigyelt adatokból számított/modellezett érték (pl. járási becsült esetszám, termelékenységveszteség) |
| `assumed` | nemzetközi irodalomból vagy szakértői becslésből átvett paraméter (pl. oltáshatásosság, alulbejelentési szorzó, QALY-súly) |

Minden `assumed` és `estimated` értékhez kötelező `source_citation`,
`source_url`, `source_year`, `confidence` (`high` / `medium` / `low`).

---

## Telepítés

Python ≥ 3.11 szükséges.

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# POSIX:    source .venv/bin/activate

pip install -e ".[dev]"
```

### Opcionális extrák

| extra | mit ad hozzá | megjegyzés |
| --- | --- | --- |
| `pdf` | `pdfplumber` + `camelot-py` PDF-táblakinyerés | a camelot lattice-módja Ghostscript-et igényel; a `pdfplumber` tiszta Python és mindig működő fallback |
| `spatial` | `geopandas`, `shapely`, `libpysal`, `esda`, `spreg` | térbeli klaszterezés/átgyűrűzés; Windowson conda-forge ajánlott |
| `render` | `playwright` | JS-alapú oldalakhoz (`--render`); utána `playwright install chromium` |
| `era5` | `cdsapi` | ERA5-Land reanalízis; `CDS_API_KEY` a `.env`-ből |
| `bayes` | `pymc`, `arviz` | a járási kis területi modell valódi (Bayes) implementációjához |

```bash
pip install -e ".[pdf,spatial,render,era5,bayes]"
```

> **Windows-megjegyzés:** az alap-pipeline (`geography`, `validation`, `costs`,
> `allocation`) az `pdf` és `spatial` extrák nélkül is fut és tesztelhető. A
> Ghostscript hiányában a camelot `lattice` stratégiája kimarad, a `pdfplumber`
> stratégiák viszont működnek.

### `.env`

Másold a `.env.example`-t `.env`-re:

```
CONTACT_EMAIL=rotavirus-research@example.org   # a HTTP User-Agentben hirdetett kapcsolat — NE személyes cím
CDS_API_KEY=<uid>:<apikey>                      # csak az `era5` extrához
HTTP_PROXY= / HTTPS_PROXY=                      # opcionális
```

---

## CLI

```bash
# --- gyűjtés ---
python -m scraper.run --all
python -m scraper.run --source nngyk
python -m scraper.run --source nngyk --since 2019-01-01 --force
python -m scraper.run --source nngyk --dry-run            # csak discover, nincs letöltés
python -m scraper.run --list-sources

# --- geográfia (BLOKKOLÓ előfeltétel) ---
python -m scraper.geography build

# --- validáció (letöltés nélkül) ---
python -m scraper.validate --all
python -m scraper.validate --table data/intermediate/nngyk/nngyk.parquet
python -m scraper.validate --compare-modelled             # FOIA-adat megérkezése után

# --- panelek ---
python -m scraper.process panel --resolution county       # megfigyelt vármegyei heti panel
python -m scraper.process panel --resolution district     # modellezett járási panel

# --- költség ---
python -m scraper.costs resolve                           # hiányzó kötelező paramétereket jelenti, nem helyettesít

# --- allokáció ---
python -m scraper.allocate --scenario 5 --budget 2500000000
python -m scraper.allocate --all-scenarios --compare

# --- riportok ---
python -m scraper.report dictionary                       # data/metadata/data_dictionary.md
python -m scraper.report availability                     # docs/availability_matrix.md
```

Globális kapcsolók: `--config`, `--log-level`, `--cache/--no-cache`, `--render`,
`--max-workers`.

`Makefile` célok: `make setup | collect | validate | geo | panel | costs |
allocate | report | test | lint | typecheck | all`.

---

## Adatelérhetőségi mátrix

Generált — lásd [`docs/availability_matrix.md`](docs/availability_matrix.md)
(`python -m scraper.report availability`). Az oszloponkénti lefedettséghez lásd
[`data/metadata/data_dictionary.md`](data/metadata/data_dictionary.md)
(`python -m scraper.report dictionary`).

Fő források (részletek: `config/sources.yaml`):

| forrás | mit ad | felbontás | robots |
| --- | --- | --- | --- |
| **NNGYK** | rotavírus heti/éves esetszám (elsődleges epi-forrás) | vármegye × hét, 2014– | ok (heti fájllista JS-render) |
| **KSH** | demográfia, szocioökonómia, TSZJ/helynévkönyv, árindexek | járás/település, éves | Tájékoztatási adatbázis + TIMEA: **manuális export** |
| **NFSZ** | regisztrált álláskeresők | település, havi | ok |
| **OKFŐ** | tartósan betöltetlen házi-/gyermek-/fogorvosi körzetek | pillanatkép (Wayback CDX-szel idősor) | ok |
| **NEAK** | HBCs alapdíj, német pont, szabálykönyvek, PUPHA | országos | alapdíj-közlemény JS-render |
| **Jogtár/NJT** | 9/1993, 290/2014 (kedvezményezett járások + komplex mutató), 218/2012; önkormányzati oltástámogatási rendeletek | járás / önkormányzat | ok |
| **MÁK** | önkormányzati éves költségvetési beszámolók | önkormányzat, éves | ok |
| **HungaroMet** | napi/havi állomásadatok + meta | állomás | ok |
| **OSM (data2.osm.hu)** | járás- és településhatárok | geometria | ok |
| **TeIR** | járási fejlettségi mutatók | járás | **regisztrációhoz kötött — csak manuális export** |

---

## Manuális exportot igénylő források

Ahol a `robots.txt` tiltja a gépi lekérdezést vagy regisztráció kell, a kollektor
**nem kerüli meg** — „manuális beolvasó” módban ellenőrzi a kézzel exportált
fájl meglétét, és ha hiányzik, kiírja a pontos lépéseket.

### KSH Tájékoztatási adatbázis / STADAT-on kívüli táblák
1. Nyisd meg <https://www.ksh.hu/adatbazis>.
2. Állítsd össze a lekérdezést (járás/település, év).
3. Exportálj XLSX/CSV formátumba.
4. Tedd a fájlt változatlanul ide: `data/raw/ksh/manual/adatbazis/`.
5. `python -m scraper.run --source ksh`.

### KSH TIMEA (járási területi mutatók)
1. <https://map.ksh.hu/timea/?locale=hu> → mutató + időszak kiválasztása → export.
2. `data/raw/ksh/manual/timea/` alá.

### Geográfiai törzs (ha nincs letöltött TSZJ)
Add meg **valamelyiket**:
- **A)** kanonikus éves CSV-k `registry_<év>.csv` néven
  (`settlement_id, settlement_name, postal_codes, district_id, district_name,
  county_id, county_name, nuts3_code, nuts2_code`; `postal_codes` `;`-vel
  elválasztva) ide: `data/raw/ksh/manual/registry/`;
- **B)** KSH TSZJ munkafüzetek
  (`teruleti_szamjelrendszer_struktura_elemei_<év>_megnevezesekkel.xlsx`) a
  <https://www.ksh.hu/teruleti_szamjel_menu> oldalról, változatlanul ide:
  `data/raw/ksh/`.

### TeIR
1. Jelentkezz be <https://www.teir.hu>.
2. Válaszd ki a járásszintű mutatókat, exportálj XLSX/CSV-be.
3. `data/raw/other/teir/` alá, majd `python -m scraper.run --source teir`.

### NEAK alapdíj-közlemény (JS-render)
`python -m scraper.run --source neak --render` (playwright telepítve), **vagy**
mentsd a közlemény HTML-jét `data/raw/neak/` alá.

---

## Adatigénylési útvonalak

- **NNGYK** — járásszintű rotavírus-esetszám közérdekűadat-igénylésben kérhető.
  A megérkező fájlt tedd `data/raw/nngyk_foia/` alá; a `nngyk_foia` kollektor
  `geo_level='district'`, `evidence_class='observed'` értékkel tölti be, majd
  `python -m scraper.validate --compare-modelled` összeveti a modellezett és a
  valós járási értékeket (`MODEL_VALIDATION_REPORT.md`).
- **NEAK** — tételes finanszírozási adatok (szolgáltatónként, HBCs-bontásban)
  adatkérésben; a publikus alapdíj-közlemény és szabálykönyvek elégségesek a
  fajlagos költségekhez.
- **KSH kutatószoba (Safe Centre)** — vármegye × korcsoport kereszttábla és
  településszintű mikroadat a kutatószobában érhető el; ez váltaná ki az
  indirekt korstandardizálást.

---

## Kimenetek

| fájl | tartalom |
| --- | --- |
| `data/processed/geo_districts.parquet` / `geo_settlements.parquet` | kanonikus járás- és településtörzs `valid_from`/`valid_to` intervallumokkal |
| `data/processed/county_weekly_epi.parquet` | **megfigyelt** vármegyei × heti rotavírus-panel („ground truth”) |
| `data/processed/district_panel.parquet` | járási × éves panel a **modellezett** rotavírus-oszlopokkal (§11 séma) |
| `data/processed/cost_parameters_resolved.parquet` | a ténylegesen használt költségparaméterek forrással + bizonyítékosztállyal |
| `data/processed/allocation_scenarios.parquet` | hosszú formátum: `district_id × scenario_id × year → aid_amount, need_score, delta_vs_baseline` |
| `data/metadata/source_registry.json` | minden letöltött fájl: URL, sha256, méret, HTTP-fejlécek (verziókövetve) |
| `data/metadata/run_manifest/<ts>.json` | git commit, config-hash-ek, `pip freeze`, CLI-parancs, erőforrás-sha256-ok |
| `data/metadata/{surveillance_breaks,boundary_changes,harmonisation_log}.json` | módszertani nyilvántartások |
| `VALIDATION_REPORT.md`, `SCHEMA_DRIFT_REPORT.md`, `BROKEN_LINKS.md`, `MANUAL_EXTRACTION_QUEUE.md`, `SUM_MISMATCH_LOG.md` | emberi olvasásra szánt futás-riportok |

---

## Bővíthetőség

A kód átírása nélkül módosítható:

| mit | hol |
| --- | --- |
| szükségleti képlet dimenziói, irányai | `config/need_index.yaml` |
| súlyok és aggregáció (`weighted_sum` / `mpi` / `pca` / `entropy`) | `config/need_index.yaml` |
| költségparaméterek (nominális érték + forrás + `price_year`) | `config/cost_parameters.yaml` |
| deflátorválasztás (egészségügyi CPI / keresetindex / fő CPI) | `config/hta_parameters.yaml` + `cost_parameters.yaml::deflators` |
| diszkontráta, időhorizont, perspektíva, küszöbérték | `config/hta_parameters.yaml` |
| jogosultsági kritériumok, költségvetési korlát | `config/scenarios.yaml` |
| **új allokációs forgatókönyv** (kódírás nélkül) | `config/scenarios.yaml` — a 0–7. forgatókönyv mind egyetlen generikus `allocate_generic()` függvény paraméterezése |
| területi felbontás | `--resolution county|district` |

Minden config pydantic modellel validált; a futás manifesztje rögzíti a
ténylegesen használt konfiguráció sha256-át.

### A 8 forgatókönyv

| # | név | képlet |
| --- | --- | --- |
| 0 | Status quo | `Aid_i = existing_local_funding_i` |
| 1 | Egyenlő fejkvóta | `Aid_i = B · P_u5_i / Σ P_u5_j` |
| 2 | Epidemiológiai célzás | `Aid_i = B · Λ̂_i / Σ Λ̂_j` |
| 3 | Szocioökonómiai célzás | `Aid_i = B · P_u5_i·S̃_i^α / Σ(...)` |
| 4 | Kapacitás szerinti célzás | ugyanez `H̃_i`-vel |
| 5 | Teljes szükségletalapú (fő) | `Aid_i = Ĉ_i·(1+η·Ñ_i)·(1−κ·F̃_i) − L_i`, majd `B`-re normálva |
| 6 | Költségrés | `Aid_i = max(0, Ĉ_i − L_i − φ·FiscCap_i)` (nem normált — a valós fiskális költséget jelenti) |
| 7 | Küszöbös (jogszabályi) | csak a 290/2014 szerinti kedvezményezett járások |

Az 5. az általános alak; a többi ennek speciális esete (`η=κ=0, L=0 → 2`;
`Ĉ_i≡const → 1`; stb.).

---

## Ismert korlátok

1. **Járásszintű rotavírus-esetszám nem publikus** → modellezett érték, széles
   (alapértelmezésben ±50%) hitelességi intervallummal. Az alapértelmezett
   `PopulationShareModel` egy **cserélhető placeholder**; a valódi hierarchikus
   Bayes (BYM2/CAR) modell a `scraper/processing/small_area_model.py`
   `BayesSmallAreaModel` stubjában van vázolva (`bayes` extra).
2. **Aluljelentés:** a bejelentett esetszám a valós teher töredéke — a szint
   helyett a **térbeli mintázatra** érdemes következtetést építeni.
3. **Surveillance-törés 2014-nél:** a „Rotavírus-gastroenteritis” önálló
   bejelentési kategória csak 2014-től létezik (1/2014. (I. 16.) EMMI r.); előtte
   az `Enteritis infectiosa` gyűjtőkategória. A pipeline 2014 előtti fájlt
   letölt/archivál, de a panelbe **nem** enged 2014 előtti rotavírus-sort
   (`data/metadata/surveillance_breaks.json`).
4. **COVID-torzítás 2020–2021:** strukturális törés, nem valós járványügyi
   változás.
5. **Vármegye × korcsoport kereszttábla nem publikus** → indirekt
   korstandardizálás (`processing/standardise.py`); a KSH kutatószoba oldaná fel.
6. A **290/2014 komplex mutató 2014-es adatokon** nyugszik, azóta nem frissült.
7. **Járási határváltozások 2013 óta** → harmonizáció kötelező
   (`geography/harmonise.py`; KTE-partíció + népességsúlyozott visszaosztás;
   `data/metadata/boundary_changes.json`).
8. A **KSH Tájékoztatási adatbázis** és a **TeIR** gépi lekérdezése
   korlátozott/regisztrációhoz kötött → manuális export.
9. A **Lechner-határállomány fizetős** → alapértelmezésben az OSM-geometria
   (`config/sources.yaml::sources.geo.boundary_provider`).
10. A **járás nem egészségfinanszírozási egység** — az implementációs útvonal
    (járási hivatal / önkormányzatok / NEAK) nyitott szakpolitikai kérdés.
11. **Nincs hazai rotavírus-specifikus QALY-súly, oltáshatásosság és lefedettségi
    adat** → ezek `assumed`, `confidence: low`, forráshivatkozással.
12. **Ökológiai torzítás és kis területi volatilitás** — a járási becslések
    aggregált adatból származnak; a `smoothing.py` empirikus Bayes simítást kínál.

---

## Reprodukálhatóság

- Minden futás `data/metadata/run_manifest/<ts>.json`-t ír: git commit hash,
  `git diff --stat` (ha piszkos a fa), a config-fájlok sha256-ja, `pip freeze`,
  Python-verzió, OS, a futtatott CLI-parancs, a feldolgozott erőforrások
  sha256-tal.
- Determinisztikus mintavétel: a `config/seed` rögzíti a magot minden
  Monte-Carlo/Dirichlet/EB eljáráshoz.
- `data/raw/` nincs git-ben, de a `source_registry.json` igen → a nyers fájlok
  bármikor újratölthetők és sha256-tal ellenőrizhetők.

---

## Séma-drift és hibatűrés

| helyzet | teendő |
| --- | --- |
| egy URL 404 | naplózva, `BROKEN_LINKS.md`, a futás folytatódik; **nincs találgatott helyettesítő URL** |
| listaoldal JS-sel töltődik, nincs playwright | informatív hiba a manuális mód lépéseivel; `--render` javaslat |
| PDF-táblakinyerés minden stratégiával elbukik | nyers PDF megőrizve, `MANUAL_EXTRACTION_QUEUE.md`, a futás folytatódik; **soha nincs becsült szám** |
| összegellenőrzés nem stimmel | `quality_flag='table_sum_mismatch'`, karantén (`data/intermediate/quarantine/`), nem kerül a panelbe |
| forrás oszlopsémája megváltozott | jelentve (`SCHEMA_DRIFT_REPORT.md`), `quality_flag='schema_drift'`, a futás nem omlik össze |
| kötelező költségparaméter hiányzik | a költségmodul leáll, megnevezi a paramétert és a forrás URL-jét; **soha nincs alapértelmezett szám** |

---

## Fejlesztés / hozzájárulás

```bash
make lint        # ruff
make typecheck   # mypy src
make test        # pytest --cov  (cél: ≥85% a geography/validation/costs/allocation modulokon)
```

- Minden szakasz zárása előtt futtasd: `ruff check .`, `mypy src`, `pytest`.
- Kód-azonosítók és docstringek angolul; a README és a generált riportok
  magyarul.
- Ha egy forrás tényleges felbontásában vagy egy URL érvényességében
  bizonytalan vagy: **ne találgass** — naplózd, dokumentáld a
  `BROKEN_LINKS.md`-ben / `MANUAL_EXTRACTION_QUEUE.md`-ben, és kérdezz.
- A `config/*.yaml` a viselkedés forrása; ne égess be paramétert, súlyt,
  küszöböt, árat vagy forgatókönyv-definíciót a kódba.

## Licenc

MIT.
