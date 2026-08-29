# 01 — load parquet inputs, harmonise settlements to districts, build the
#      district base table (population proxy, jobseeker rate, vacant practices).

if (!exists("ANALYSIS")) source(file.path("analysis", "R", "00_setup.R"))
message("[01] load & harmonise ...")

geo_d <- as.data.table(read_parquet(file.path(PROC, "geo_districts.parquet")))
geo_s <- as.data.table(read_parquet(file.path(PROC, "geo_settlements.parquet")))
cw    <- as.data.table(read_parquet(file.path(PROC, "county_weekly_epi.parquet")))
nfsz  <- as.data.table(read_parquet(file.path(INTER, "nfsz", "nfsz.parquet")))
okfo  <- as.data.table(read_parquet(file.path(INTER, "okfo", "okfo.parquet")))
ksh   <- as.data.table(read_parquet(file.path(INTER, "ksh", "ksh.parquet")))

## county name -> id lookup ------------------------------------------------
cmap <- unique(geo_d[, .(county_id, county_name)])
county_id_by_norm <- setNames(cmap$county_id, norm_county(cmap$county_name))
extra <- unique(cw[, .(county_id, geo_name)])
for (i in seq_len(nrow(extra))) {
  k <- norm_county(extra$geo_name[i])
  if (is.na(county_id_by_norm[k])) county_id_by_norm[k] <- extra$county_id[i]
}

## settlement -> district (disambiguated by county) ----------------------
geo_s[, s_norm := norm_settlement(settlement_name)]
s2d <- geo_s[, .(district_id = if (uniqueN(district_id) == 1) district_id[1] else NA_character_),
             by = .(s_norm, county_id)]

DISTRICTS <- unique(geo_d[, .(district_id, district_name, county_id, county_name,
                              nuts3_code, is_budapest_district)])
setorder(DISTRICTS, district_id)
N_DIST <- nrow(DISTRICTS)

## epidemiology: national weekly + county-year ---------------------------
epi <- cw[variable == "rotavirus_cases"]
epi[, value := as.numeric(value)]
natw <- epi[, .(value = sum(value)), by = .(iso_year, iso_week)][order(iso_year, iso_week)]
natw[, t := iso_year + (iso_week - 1) / 52]
fwrite(natw, file.path(RESULTS, "nat_weekly.csv"))

county_cases <- epi[, .(cases = sum(value)), by = .(county_id, year = iso_year)]
fwrite(county_cases, file.path(RESULTS, "epi_county_year.csv"))

## observed county child population (KSH 0-14) by year -> rate denominator ---
CHILD_BY_CY <- NULL
RATE_DENOM_LABEL <- "100\\,000 munkavállalási korú fő"
if (!is.null(POPAGE)) {
  pa <- copy(POPAGE)
  pa[, county_id := county_id_by_norm[norm_county(county_name)]]
  pa <- pa[age_group == "age_0_14" & !is.na(county_id)]
  CHILD_BY_CY <- pa[, .(county_id, year, population)]
  RATE_DENOM_LABEL <- "100\\,000 gyermek (0--14)"
}
macro("rateDenom", RATE_DENOM_LABEL)

## NFSZ: settlement -> district population proxy + jobseekers (YEAR) -----
nf <- copy(nfsz)
nf[, year := as.integer(substr(period_start, 1, 4))]
nf[, county_id := county_id_by_norm[norm_county(county_sheet)]]
nf[, s_norm := norm_settlement(settlement_name)]
pop_year <- nf[year == YEAR, .(wap = mean(working_age_population),
                               jobseekers = mean(registered_jobseekers)),
               by = .(county_id, s_norm)]
pop_year <- merge(pop_year, s2d, by = c("s_norm", "county_id"), all.x = TRUE)
macro_match <- mean(!is.na(pop_year$district_id))
macro("nfsMatchRate", 100 * macro_match, digits = 1)

dpop <- pop_year[!is.na(district_id),
                 .(pop = sum(wap), jobseekers = sum(jobseekers)), by = district_id]
dpop[, jobseeker_rate := jobseekers / pop]

## OKFŐ: chronically vacant GP/paediatric practices, latest snapshot ----
ok <- okfo[grepl("gp", source_file, ignore.case = TRUE)]
ok <- ok[snapshot_date == max(snapshot_date)]
ok[, s_norm := norm_settlement(settlement_name)]
ok[, county_id := county_id_by_norm[norm_county(county_name)]]
ok <- merge(ok, s2d, by = c("s_norm", "county_id"), all.x = TRUE)
vac <- ok[!is.na(district_id),
          .(vacant_paed = sum(practice_type %in% c("paediatric", "mixed")),
            vacant_any = .N), by = district_id]

## district base table --------------------------------------------------
D <- merge(DISTRICTS, dpop, by = "district_id", all.x = TRUE)
D[, pop := fifelse(is.na(pop), stats::median(pop, na.rm = TRUE), pop), by = county_id]
D[is.na(jobseeker_rate), jobseeker_rate := stats::median(D$jobseeker_rate, na.rm = TRUE)]
D <- merge(D, vac, by = "district_id", all.x = TRUE)
D[is.na(vacant_paed), vacant_paed := 0]; D[is.na(vacant_any), vacant_any := 0]
D[, vacant_paed_practice_rate := vacant_paed / pop * 1e5]

fwrite(D, file.path(RESULTS, "district_base.csv"))
saveRDS(list(D = D, epi = epi, county_cases = county_cases, ksh = ksh,
             county_id_by_norm = county_id_by_norm, N_DIST = N_DIST,
             CHILD_BY_CY = CHILD_BY_CY, RATE_DENOM_LABEL = RATE_DENOM_LABEL,
             pop_year = pop_year, s2d = s2d),
        file.path(RESULTS, "_state_01.rds"))
message(sprintf("    districts=%d  settlement match=%.1f%%", N_DIST, 100 * macro_match))
