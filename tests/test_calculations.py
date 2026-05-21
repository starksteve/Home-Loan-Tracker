import pandas as pd

from loan_tracker.calculations import build_schedule, calculate_emi, summarize_schedule


def test_calculate_emi_zero_rate():
    emi = calculate_emi(principal=1200000, annual_rate=0, tenure_months=12)
    assert round(emi, 2) == 100000.0


def test_build_schedule_and_summary_basic():
    loan = {"principal": 100000, "start_date": "2026-01-01", "tenure_years": 1}
    rates = [{"effective_month": "2026-01", "annual_rate": 12.0}]
    payments = [
        {"month": "2026-01", "emi_paid": 9000, "extra_principal": 1000},
        {"month": "2026-02", "emi_paid": 9000, "extra_principal": 0},
    ]

    schedule = build_schedule(loan, rates, payments, as_of_month="2026-02", project_to_end=False)

    assert not schedule.empty
    assert list(schedule.columns) == [
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
    assert schedule.iloc[0]["month"] == "2026-01"
    assert schedule.iloc[-1]["closing_principal"] < loan["principal"]

    summary = summarize_schedule(schedule)
    assert summary["total_paid"] == 19000.0
    assert summary["principal_paid"] > 0
    assert summary["interest_paid"] > 0


def test_projected_rows_generated_when_enabled():
    loan = {"principal": 50000, "start_date": "2026-01-01", "tenure_years": 1}
    rates = [{"effective_month": "2026-01", "annual_rate": 10.0}]
    payments = [{"month": "2026-01", "emi_paid": 5000, "extra_principal": 0}]

    schedule = build_schedule(loan, rates, payments, as_of_month="2026-01", project_to_end=True)

    assert isinstance(schedule, pd.DataFrame)
    assert (schedule["is_projected"] == True).any()  # noqa: E712


def test_monthly_interest_override_without_rate_history():
    loan = {
        "principal": 200000,
        "start_date": "2026-01-01",
        "tenure_years": 2,
        "assumed_annual_rate": 8.5,
    }
    rates: list[dict] = []
    payments = [
        {
            "month": "2026-01",
            "emi_paid": 18000,
            "interest_paid": 1400,
            "extra_principal": 2000,
        },
        {
            "month": "2026-02",
            "emi_paid": 18000,
            "interest_paid": 1300,
            "extra_principal": 0,
        },
    ]

    schedule = build_schedule(loan, rates, payments, as_of_month="2026-02", project_to_end=False)
    jan = schedule.iloc[0]
    feb = schedule.iloc[1]

    assert jan["interest_component"] == 1400
    assert feb["interest_component"] == 1300
    assert jan["principal_component"] == 18600

    summary = summarize_schedule(schedule)
    assert summary["interest_paid"] == 2700.0
    assert summary["total_paid"] == 38000.0


def test_invalid_month_entries_are_ignored():
    loan = {"principal": 100000, "start_date": "2026-01-01", "tenure_years": 1}
    rates = [{"effective_month": "2026-01", "annual_rate": 10.0}]
    payments = [
        {"month": None, "emi_paid": 5000, "extra_principal": 0},
        {"month": "", "emi_paid": 5000, "extra_principal": 0},
        {"month": "not-a-date", "emi_paid": 5000, "extra_principal": 0},
        {"month": "2026-01", "emi_paid": 9000, "extra_principal": 1000},
    ]

    schedule = build_schedule(loan, rates, payments, as_of_month="2026-01", project_to_end=False)

    assert not schedule.empty
    assert len(schedule) == 1
    assert schedule.iloc[0]["month"] == "2026-01"


def test_explicit_interest_charged_can_exceed_emi():
    loan = {"principal": 100000, "start_date": "2026-01-01", "tenure_years": 1}
    rates: list[dict] = []
    payments = [
        {
            "month": "2026-01",
            "interest_charged": 5000,
            "emi_paid": 3000,
            "extra_principal": 0,
        }
    ]

    schedule = build_schedule(loan, rates, payments, as_of_month="2026-01", project_to_end=False)
    row = schedule.iloc[0]

    assert row["interest_component"] == 3000
    assert row["principal_component"] == 0
    assert row["closing_principal"] == 102000
    assert row["annual_rate"] == 60.0


def test_summary_outstanding_is_current_not_projected():
    loan = {"principal": 100000, "start_date": "2026-01-01", "tenure_years": 2, "assumed_annual_rate": 10.0}
    rates: list[dict] = []
    payments = [
        {"month": "2026-01", "interest_charged": 1000, "emi_paid": 9000, "extra_principal": 0},
        {"month": "2026-02", "interest_charged": 920, "emi_paid": 9000, "extra_principal": 0},
    ]

    schedule = build_schedule(loan, rates, payments, as_of_month="2026-02", project_to_end=True)
    summary = summarize_schedule(schedule)

    actual = schedule[schedule["is_projected"] == False]  # noqa: E712
    assert summary["outstanding"] == float(actual.iloc[-1]["closing_principal"])
    assert summary["outstanding_projected"] == float(schedule.iloc[-1]["closing_principal"])
