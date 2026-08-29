"""CLI smoke tests (typer CliRunner) for the entry points that fail fast or
only read — kept free of writes into the repo tree."""

from __future__ import annotations

from typer.testing import CliRunner

runner = CliRunner()


def test_run_list_sources():
    from scraper.run import app

    res = runner.invoke(app, ["--list-sources"])
    assert res.exit_code == 0
    assert "nngyk" in res.stdout and "jogtar" in res.stdout


def test_run_requires_a_source():
    from scraper.run import app

    res = runner.invoke(app, [])
    assert res.exit_code != 0


def test_geography_build_reports_missing_sources(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from scraper.geography import build_registry as br
    from scraper.geography.__main__ import app

    # point every input/output path at the empty tmp tree so the build has no
    # source files to find (independent of what the real data/ tree holds)
    monkeypatch.setattr(br, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(br, "MANUAL_REGISTRY_DIR", tmp_path / "raw" / "ksh" / "manual" / "registry")
    monkeypatch.setattr(br, "PROCESSED_DIR", tmp_path / "processed")

    res = runner.invoke(app, ["build"])
    assert res.exit_code == 2
    assert "No geography source files found" in res.stdout


def test_costs_resolve_halts_on_missing_required(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from scraper.costs.__main__ import app

    res = runner.invoke(app, ["resolve"])
    assert res.exit_code == 2
    assert "hbcs_base_rate" in res.stdout


def test_process_district_panel_without_geo_errors(monkeypatch, tmp_path):
    from scraper.process import app
    from scraper.processing import panel as panel_mod

    # redirect every processed-tree path into tmp; the district step then
    # fails fast because geo_districts.parquet is absent there
    monkeypatch.setattr(panel_mod, "PROCESSED_DIR", tmp_path)
    monkeypatch.setattr(panel_mod, "COUNTY_WEEKLY_OUT", tmp_path / "cw.parquet")
    monkeypatch.setattr(panel_mod, "DISTRICT_PANEL_OUT", tmp_path / "dp.parquet")
    res = runner.invoke(app, ["panel", "--resolution", "district"])
    assert res.exit_code == 2
    assert "geo_districts.parquet missing" in res.stdout
