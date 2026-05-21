from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class LoanConfig:
    principal: float
    start_date: str
    tenure_years: int


@dataclass(frozen=True)
class RateChange:
    effective_month: str
    annual_rate: float


@dataclass(frozen=True)
class Payment:
    month: str
    emi_paid: float
    extra_principal: float
    interest_paid: float | None = None
    interest_charged: float | None = None
    annual_rate: float | None = None


def _month_start(value: str | date) -> date:
    if isinstance(value, date):
        return value.replace(day=1)
    parsed = pd.to_datetime(value)
    return date(parsed.year, parsed.month, 1)


def _month_str(value: date) -> str:
    return value.strftime("%Y-%m")


def _add_months(value: date, months: int) -> date:
    y = value.year + (value.month - 1 + months) // 12
    m = (value.month - 1 + months) % 12 + 1
    return date(y, m, 1)


def calculate_emi(principal: float, annual_rate: float, tenure_months: int) -> float:
    if tenure_months <= 0:
        return 0.0
    if principal <= 0:
        return 0.0

    monthly_rate = annual_rate / (12 * 100)
    if monthly_rate == 0:
        return principal / tenure_months

    factor = (1 + monthly_rate) ** tenure_months
    return principal * monthly_rate * factor / (factor - 1)


def _get_rate_for_month(month: date, sorted_rate_changes: list[RateChange]) -> float:
    target = _month_str(month)
    applicable = [item for item in sorted_rate_changes if item.effective_month <= target]
    if not applicable:
        return sorted_rate_changes[0].annual_rate
    return applicable[-1].annual_rate


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_month_key(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "nan", "nat"}:
        return None
    try:
        return _month_str(_month_start(text))
    except (TypeError, ValueError):
        return None


def build_schedule(
    loan: dict[str, Any],
    rate_changes: list[dict[str, Any]],
    payments: list[dict[str, Any]],
    as_of_month: str | None = None,
    project_to_end: bool = True,
) -> pd.DataFrame:
    principal = float(loan.get("principal", 0) or 0)
    tenure_years = int(loan.get("tenure_years", 15) or 15)
    assumed_annual_rate = _safe_float(loan.get("assumed_annual_rate", 0.0), 0.0)
    tenure_months = tenure_years * 12
    start_month = _month_start(loan.get("start_date", date.today().isoformat()))

    if principal <= 0:
        return pd.DataFrame(
            columns=[
                "month",
                "opening_principal",
                "annual_rate",
                "emi_due",
                "emi_paid",
                "extra_principal_paid",
                "interest_component",
                "principal_component",
                "closing_principal",
                "is_projected",
            ]
        )

    parsed_rates = [
        RateChange(
            effective_month=str(item.get("effective_month", "")),
            annual_rate=float(item.get("annual_rate", 0) or 0),
        )
        for item in rate_changes
        if item.get("effective_month")
    ]
    if not parsed_rates:
        parsed_rates = [
            RateChange(
                effective_month=_month_str(start_month),
                annual_rate=assumed_annual_rate,
            )
        ]
    parsed_rates.sort(key=lambda x: x.effective_month)

    payments_map: dict[str, dict[str, float | None]] = {}
    for entry in payments:
        month = _normalize_month_key(entry.get("month"))
        if month is None:
            continue
        cur = payments_map.setdefault(
            month,
            {
                "emi_paid": 0.0,
                "extra_principal": 0.0,
                "interest_paid": None,
                "annual_rate": None,
            },
        )
        cur["emi_paid"] = _safe_float(cur["emi_paid"], 0.0) + _safe_float(entry.get("emi_paid", 0), 0.0)
        cur["extra_principal"] = _safe_float(cur["extra_principal"], 0.0) + _safe_float(
            entry.get("extra_principal", 0), 0.0
        )

        month_interest = entry.get("interest_paid")
        if month_interest in (None, ""):
            month_interest = entry.get("interest_charged")

        if month_interest not in (None, ""):
            interest_piece = _safe_float(month_interest, 0.0)
            current_interest = cur.get("interest_paid")
            cur["interest_paid"] = (
                interest_piece
                if current_interest in (None, "")
                else _safe_float(current_interest, 0.0) + interest_piece
            )

        if entry.get("annual_rate") not in (None, ""):
            cur["annual_rate"] = _safe_float(entry.get("annual_rate"), 0.0)

    as_of = _month_start(as_of_month) if as_of_month else _month_start(date.today())
    last_payment_month = max((_month_start(m) for m in payments_map), default=start_month)
    actual_end_month = max(as_of, last_payment_month)

    rows: list[dict[str, Any]] = []
    balance = principal
    month = start_month
    elapsed = 0

    while balance > 0 and month <= actual_end_month and elapsed < tenure_months + 240:
        remaining_months = max(1, tenure_months - elapsed)
        month_key = _month_str(month)
        payment = payments_map.get(
            month_key,
            {
                "emi_paid": 0.0,
                "extra_principal": 0.0,
                "interest_paid": None,
                "annual_rate": None,
            },
        )

        payment_rate = payment.get("annual_rate")
        if payment_rate not in (None, ""):
            annual_rate = _safe_float(payment_rate, assumed_annual_rate)
        else:
            annual_rate = _get_rate_for_month(month, parsed_rates)

        emi_due = calculate_emi(balance, annual_rate, remaining_months)

        emi_paid = max(0.0, _safe_float(payment.get("emi_paid", 0.0), 0.0))
        extra_paid = max(0.0, _safe_float(payment.get("extra_principal", 0.0), 0.0))

        interest_due = balance * annual_rate / (12 * 100)
        interest_override = payment.get("interest_paid")
        annual_rate_for_row = annual_rate
        if interest_override not in (None, ""):
            explicit_interest = max(0.0, _safe_float(interest_override, 0.0))
            if balance > 0:
                annual_rate_for_row = (explicit_interest * 12 * 100) / balance
            interest_paid = min(emi_paid, explicit_interest)
            interest_shortfall = max(0.0, explicit_interest - emi_paid)
            principal_from_emi = max(0.0, emi_paid - explicit_interest)
            principal_reduction = min(balance, principal_from_emi + extra_paid)
            extra_effective = max(0.0, principal_reduction - principal_from_emi)
            closing = max(0.0, balance - principal_reduction + interest_shortfall)
        else:
            interest_paid = min(emi_paid, interest_due)
            principal_from_emi = max(0.0, emi_paid - interest_due)
            principal_reduction = min(balance, principal_from_emi + extra_paid)
            extra_effective = max(0.0, principal_reduction - principal_from_emi)
            interest_shortfall = max(0.0, interest_due - emi_paid)
            closing = max(0.0, balance - principal_reduction + interest_shortfall)

        rows.append(
            {
                "month": month_key,
                "opening_principal": round(balance, 2),
                "annual_rate": round(annual_rate_for_row, 4),
                "emi_due": round(emi_due, 2),
                "emi_paid": round(emi_paid, 2),
                "extra_principal_paid": round(extra_effective, 2),
                "interest_component": round(interest_paid, 2),
                "principal_component": round(principal_from_emi + extra_effective, 2),
                "closing_principal": round(closing, 2),
                "is_projected": False,
            }
        )

        balance = closing
        month = _add_months(month, 1)
        elapsed += 1

    if project_to_end and balance > 0:
        while balance > 0 and elapsed < tenure_months + 240:
            remaining_months = max(1, tenure_months - elapsed)
            annual_rate = _get_rate_for_month(month, parsed_rates)
            emi_due = calculate_emi(balance, annual_rate, remaining_months)

            interest_due = balance * annual_rate / (12 * 100)
            principal_from_emi = max(0.0, emi_due - interest_due)
            principal_reduction = min(balance, principal_from_emi)
            closing = max(0.0, balance - principal_reduction)

            rows.append(
                {
                    "month": _month_str(month),
                    "opening_principal": round(balance, 2),
                    "annual_rate": round(annual_rate, 4),
                    "emi_due": round(emi_due, 2),
                    "emi_paid": round(emi_due, 2),
                    "extra_principal_paid": 0.0,
                    "interest_component": round(min(interest_due, emi_due), 2),
                    "principal_component": round(principal_reduction, 2),
                    "closing_principal": round(closing, 2),
                    "is_projected": True,
                }
            )

            balance = closing
            month = _add_months(month, 1)
            elapsed += 1

    return pd.DataFrame(rows)


def summarize_schedule(schedule: pd.DataFrame) -> dict[str, float]:
    if schedule.empty:
        return {
            "total_paid": 0.0,
            "interest_paid": 0.0,
            "principal_paid": 0.0,
            "outstanding": 0.0,
            "outstanding_projected": 0.0,
        }

    actual = schedule[schedule["is_projected"] == False]  # noqa: E712
    total_paid = float((actual["emi_paid"] + actual["extra_principal_paid"]).sum())
    interest_paid = float(actual["interest_component"].sum())
    principal_paid = float(actual["principal_component"].sum())
    if not actual.empty:
        outstanding = float(actual.iloc[-1]["closing_principal"])
    else:
        outstanding = float(schedule.iloc[-1]["closing_principal"])

    outstanding_projected = float(schedule.iloc[-1]["closing_principal"])

    return {
        "total_paid": round(total_paid, 2),
        "interest_paid": round(interest_paid, 2),
        "principal_paid": round(principal_paid, 2),
        "outstanding": round(outstanding, 2),
        "outstanding_projected": round(outstanding_projected, 2),
    }
