# Adatszótár

Generált fájl (`python -m scraper.report dictionary`). Minden oszlop a `config/variables.yaml` alapján; a lefedettség a `data/processed/*.parquet` állományokból származik, ha elérhetők.

| Oszlop | Blokk | Tier | geo_level | Időbeli felbontás | Egység | evidence_class | Forrás | Forrás-URL | Lefedett évek | Hiányzó arány | Megjelenik |
| --- | --- | ---: | --- | --- | --- | --- | --- | --- | --- | ---: | --- |
| district_id | identifier | 1 | district | none | code | observed | ksh | https://www.ksh.hu | 2024–2024 | 0% | district_panel.parquet |
| district_name | identifier | 2 | district | none | text | observed | ksh | https://www.ksh.hu | 2024–2024 | 0% | district_panel.parquet |
| county_id | identifier | 1 | county | none | code | observed | ksh | https://www.ksh.hu | 2024–2024 | 0% | county_weekly_epi.parquet, district_panel.parquet |
| county_name | identifier | 2 | county | none | text | observed | ksh | https://www.ksh.hu | 2024–2024 | 0% | district_panel.parquet |
| nuts3_code | identifier | 2 | county | none | code | observed | geo | https://data2.openstreetmap.hu | 2024–2024 | 0% | district_panel.parquet |
| year | identifier | 1 | district | yearly | year | observed | ksh | https://www.ksh.hu | — | 0% | district_panel.parquet |
| month | identifier | 2 | district | monthly | month | observed | ksh | https://www.ksh.hu | — | — | — |
| iso_week | identifier | 1 | county | weekly | week | observed | nngyk | https://nngyk.gov.hu | — | 25% | county_weekly_epi.parquet |
| period_start | identifier | 1 | district | none | date | observed | ksh | https://www.ksh.hu | — | 0% | county_weekly_epi.parquet |
| period_end | identifier | 1 | district | none | date | observed | ksh | https://www.ksh.hu | — | 0% | county_weekly_epi.parquet |
| population_total | demography | 1 | district | yearly | persons | observed | ksh | https://www.ksh.hu | — | — | — |
| population_0_4 | demography | 1 | district | yearly | persons | observed | ksh | https://www.ksh.hu | — | — | — |
| population_0_1 | demography | 2 | district | yearly | persons | observed | ksh | https://www.ksh.hu | — | — | — |
| births | demography | 2 | district | yearly | persons | observed | ksh | https://www.ksh.hu | — | — | — |
| rotavirus_cases_district_modelled | epidemiology | 1 | district | yearly | cases | estimated | nngyk | https://nngyk.gov.hu | 2024–2024 | 0% | district_panel.parquet |
| rotavirus_cases_district_modelled_lo | epidemiology | 1 | district | yearly | cases | estimated | nngyk | https://nngyk.gov.hu | 2024–2024 | 0% | district_panel.parquet |
| rotavirus_cases_district_modelled_hi | epidemiology | 1 | district | yearly | cases | estimated | nngyk | https://nngyk.gov.hu | 2024–2024 | 0% | district_panel.parquet |
| rotavirus_incidence_u5_modelled | epidemiology | 1 | district | yearly | per_1000 | estimated | nngyk | https://nngyk.gov.hu | 2024–2024 | 0% | district_panel.parquet |
| hospitalisations_modelled | epidemiology | 1 | district | yearly | cases | estimated | nngyk | https://nngyk.gov.hu | 2024–2024 | 100% | district_panel.parquet |
| expected_cases_per_1000_u5_modelled | epidemiology | 1 | district | yearly | per_1000 | estimated | nngyk | https://nngyk.gov.hu | 2024–2024 | 0% | district_panel.parquet |
| jobseeker_rate | socioeconomic | 1 | district | monthly | ratio | observed | nfsz | https://nfsz.munka.hu | — | — | — |
| registered_jobseekers | socioeconomic | 2 | district | monthly | persons | observed | nfsz | https://nfsz.munka.hu | — | — | — |
| pit_income_per_capita | socioeconomic | 1 | district | yearly | huf | observed | ksh | https://www.ksh.hu | — | — | — |
| low_education_ratio | socioeconomic | 1 | district | yearly | ratio | observed | ksh | https://www.ksh.hu | — | — | — |
| housing_deprivation_ratio | socioeconomic | 2 | district | yearly | ratio | observed | ksh | https://www.ksh.hu | — | — | — |
| sewerage_ratio | socioeconomic | 2 | district | yearly | ratio | observed | ksh | https://www.ksh.hu | — | — | — |
| population_density | socioeconomic | 2 | district | yearly | per_km2 | observed | ksh | https://www.ksh.hu | — | — | — |
| komplex_mutato_2014 | socioeconomic | 1 | district | none | index | observed | jogtar | https://net.jogtar.hu | — | — | — |
| kedvezmenyezett_status | socioeconomic | 1 | district | none | bool | observed | jogtar | https://net.jogtar.hu | — | — | — |
| gp_services | healthcare | 2 | district | yearly | count | observed | okfo | https://alapellatas.okfo.gov.hu | — | — | — |
| paediatric_services | healthcare | 1 | district | yearly | count | observed | okfo | https://alapellatas.okfo.gov.hu | — | — | — |
| vacant_gp_practices | healthcare | 2 | district | monthly | count | observed | okfo | https://alapellatas.okfo.gov.hu | — | — | — |
| vacant_paediatric_practices | healthcare | 1 | district | monthly | count | observed | okfo | https://alapellatas.okfo.gov.hu | — | — | — |
| vacant_paediatric_practice_ratio | healthcare | 1 | district | monthly | ratio | estimated | okfo | https://alapellatas.okfo.gov.hu | — | — | — |
| hospital_beds_county | healthcare | 2 | county | yearly | beds | observed | neak | https://www.neak.gov.hu | — | — | — |
| paediatric_beds_county | healthcare | 1 | county | yearly | beds | observed | neak | https://www.neak.gov.hu | — | — | — |
| paed_beds_per_1000_u5_inverse | healthcare | 1 | county | yearly | per_1000 | estimated | neak | https://www.neak.gov.hu | — | — | — |
| travel_time_to_paed_hospital | healthcare | 1 | district | none | minutes | estimated | geo | https://data2.openstreetmap.hu | — | — | — |
| municipal_own_revenue_per_capita | fiscal | 1 | district | yearly | huf | observed | mak | https://www.allamkincstar.gov.hu | — | — | — |
| municipal_expenditure_per_capita | fiscal | 2 | district | yearly | huf | observed | mak | https://www.allamkincstar.gov.hu | — | — | — |
| existing_local_funding | fiscal | 1 | district | yearly | huf | observed | jogtar | https://net.jogtar.hu | — | — | — |
| temp_mean | environment | 3 | district | monthly | celsius | observed | hungaromet | https://odp.met.hu | — | — | — |
| temp_min | environment | 3 | district | monthly | celsius | observed | hungaromet | https://odp.met.hu | — | — | — |
| temp_max | environment | 3 | district | monthly | celsius | observed | hungaromet | https://odp.met.hu | — | — | — |
| precipitation | environment | 3 | district | monthly | mm | observed | hungaromet | https://odp.met.hu | — | — | — |
| relative_humidity | environment | 3 | district | monthly | percent | observed | hungaromet | https://odp.met.hu | — | — | — |
| cost_per_case_huf_nominal | cost | 1 | district | yearly | huf | estimated | neak | https://www.neak.gov.hu | — | — | — |
| cost_per_case_huf_real_2025 | cost | 1 | district | yearly | huf | estimated | neak | https://www.neak.gov.hu | — | — | — |
| cost_per_hospitalisation_huf_nominal | cost | 1 | district | yearly | huf | estimated | neak | https://www.neak.gov.hu | — | — | — |
| cost_per_hospitalisation_huf_real_2025 | cost | 1 | district | yearly | huf | estimated | neak | https://www.neak.gov.hu | — | — | — |
| vaccination_cost_huf_nominal | cost | 1 | district | yearly | huf | estimated | neak | https://www.neak.gov.hu | — | — | — |
| vaccination_cost_huf_real_2025 | cost | 1 | district | yearly | huf | estimated | neak | https://www.neak.gov.hu | — | — | — |
| productivity_cost_huf_nominal | cost | 1 | district | yearly | huf | estimated | ksh | https://www.ksh.hu | — | — | — |
| productivity_cost_huf_real_2025 | cost | 1 | district | yearly | huf | estimated | ksh | https://www.ksh.hu | — | — | — |
| expected_total_cost_huf_real_2025 | cost | 1 | district | yearly | huf | estimated | neak | https://www.neak.gov.hu | — | — | — |
| need_score | allocation | 1 | district | yearly | index | estimated | ksh | https://www.ksh.hu | — | — | — |
| aid_amount_huf | allocation | 1 | district | yearly | huf | estimated | ksh | https://www.ksh.hu | — | — | — |
| scenario_id | allocation | 1 | district | yearly | code | assumed | ksh | https://www.ksh.hu | — | — | — |
| evidence_class | quality | 1 | district | none | enum | observed | ksh | https://www.ksh.hu | 2024–2024 | 0% | county_weekly_epi.parquet, district_panel.parquet |
| quality_flag | quality | 1 | district | none | text | observed | ksh | https://www.ksh.hu | 2024–2024 | 0% | county_weekly_epi.parquet, district_panel.parquet |
| source_id | quality | 1 | district | none | text | observed | ksh | https://www.ksh.hu | 2024–2024 | 0% | county_weekly_epi.parquet, district_panel.parquet |
| extraction_run_id | quality | 1 | district | none | text | observed | ksh | https://www.ksh.hu | — | — | — |
| missing_reason | quality | 1 | district | none | text | observed | ksh | https://www.ksh.hu | — | — | — |
