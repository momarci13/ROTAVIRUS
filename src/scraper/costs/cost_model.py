"""Expected-cost model (spec §9).

    c_fekvo(y)   = hbcs_weight * hbcs_base_rate(y)
    c_jaro(y)    = sum_k n_k * p_k * outpatient_point_value(y)
    ProdLoss_i   = N_case_i * pi_parental * d_mean * (W_i / D_workdays) * (1 + tau)
    C_i          = N_hosp_i*c_fekvo + N_out_i*c_jaro + N_gp_i*c_gp + ProdLoss_i

Every monetary output is emitted twice: ``*_huf_nominal`` and
``*_huf_real_2025`` with ``price_year`` / ``deflator_id`` / ``deflator_source``.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from scraper.core.config import Config
from scraper.core.logging_setup import get_logger
from scraper.costs.deflate import DeflatorSet
from scraper.costs.parameters import ParameterBook, resolve_all

log = get_logger("scraper.costs.cost_model")


@dataclass(slots=True)
class UnitCosts:
    year: int
    c_inpatient_nominal: float
    c_outpatient_nominal: float
    c_gp_nominal: float
    price_year: int


def unit_costs(config: Config, *, year: int, strict: bool = True) -> UnitCosts:
    book = ParameterBook(resolve_all(config, year=year, strict=strict))

    hbcs_weight = book.get("hbcs_weight_paed_gastroenteritis")
    hbcs_rate = book.get("hbcs_base_rate")
    point_value = book.get("outpatient_point_value")
    points_per_case = book.get_optional("outpatient_points_per_case", 0.0) or 0.0
    gp_cost = book.get_optional("gp_visit_cost", 0.0) or 0.0

    return UnitCosts(
        year=year,
        c_inpatient_nominal=hbcs_weight * hbcs_rate,
        c_outpatient_nominal=points_per_case * point_value,
        c_gp_nominal=gp_cost,
        price_year=book.price_year("hbcs_base_rate") or year,
    )


def productivity_loss_nominal(
    n_cases: pd.Series | float,
    *,
    book: ParameterBook,
    daily_wage: pd.Series | float | None = None,
) -> pd.Series | float:
    pi = book.get("parental_work_loss_probability")
    d_mean = book.get("mean_illness_duration_days")
    tau = book.get("employer_contribution_rate")
    workdays = book.get("working_days_per_year")
    wage = daily_wage if daily_wage is not None else book.get("daily_gross_wage")
    # spec formula: N * pi * d_mean * (W_i / D_workdays) * (1 + tau).
    # `daily_gross_wage` is already W_i / D_workdays; days lost cannot exceed the
    # working year.
    d_effective = min(d_mean, workdays)
    return n_cases * pi * d_effective * wage * (1 + tau)


def expected_cost_panel(
    config: Config,
    panel: pd.DataFrame,
    *,
    year: int,
    cases_col: str = "rotavirus_cases_district_modelled",
    strict: bool = True,
) -> pd.DataFrame:
    """Add cost columns (nominal + real_<base>) to a district panel."""
    book = ParameterBook(resolve_all(config, year=year, strict=strict))
    uc = unit_costs(config, year=year, strict=strict)
    ds = DeflatorSet(config)
    base = ds.base_year

    out = panel.copy()
    cases_series = out[cases_col] if cases_col in out.columns else pd.Series(0.0, index=out.index)
    n = pd.to_numeric(cases_series, errors="coerce").fillna(0.0)

    hosp_rate = book.get("hospitalisation_rate_u5")
    under = book.get("underreporting_multiplier")
    n_true = n * under
    n_hosp = n_true * hosp_rate
    n_out = n_true * (1 - hosp_rate)

    daily_wage = pd.to_numeric(out["daily_gross_wage"], errors="coerce") if "daily_gross_wage" in out.columns else None

    cost_inpatient = n_hosp * uc.c_inpatient_nominal
    cost_outpatient = n_out * uc.c_outpatient_nominal
    cost_gp = n_out * uc.c_gp_nominal
    prod = productivity_loss_nominal(n_true, book=book, daily_wage=daily_wage)

    vacc_price = book.get("vaccine_course_price")
    vacc_admin = book.get_optional("vaccine_administration_cost", 0.0) or 0.0
    births = pd.to_numeric(out["births"], errors="coerce").fillna(0.0) if "births" in out.columns else 0.0
    cost_vacc = births * (vacc_price + vacc_admin)

    def _pair(series, cost_class: str, name: str) -> None:
        out[f"{name}_huf_nominal"] = series
        factor = ds.for_class(cost_class).factor(uc.price_year)
        out[f"{name}_huf_real_{base}"] = series * factor
        out[f"{name}_deflator_id"] = ds.for_class(cost_class).deflator_id

    denom = n.where(n > 0)
    per_case_nominal = ((cost_inpatient + cost_outpatient + cost_gp) / denom).fillna(0.0)
    _pair(per_case_nominal, "medical_costs", "cost_per_case")
    _pair(uc.c_inpatient_nominal + 0 * n, "medical_costs", "cost_per_hospitalisation")
    _pair(cost_vacc, "vaccination_costs", "vaccination_cost")
    _pair(prod, "productivity_costs", "productivity_cost")

    total_nominal = cost_inpatient + cost_outpatient + cost_gp + prod
    factor_med = ds.for_class("medical_costs").factor(uc.price_year)
    out["expected_total_cost_huf_nominal"] = total_nominal
    out[f"expected_total_cost_huf_real_{base}"] = (
        (cost_inpatient + cost_outpatient + cost_gp) * factor_med
        + prod * ds.for_class("productivity_costs").factor(uc.price_year)
    )
    out["price_year"] = uc.price_year
    out["deflator_source"] = "config/cost_parameters.yaml::deflators"
    out["cost_evidence_class"] = "estimated"
    log.info("costs.panel", rows=len(out), year=year, price_year=uc.price_year)
    return out
