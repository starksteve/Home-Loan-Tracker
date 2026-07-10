from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from loan_tracker.calculations import build_schedule, summarize_schedule
from loan_tracker.storage import load_data, save_data

HARD_PRINCIPAL = 1125000.0
HARD_DISBURSEMENT_DATE = "2022-05-31"
HARD_START_DATE = "2022-06-01"
HARD_TENURE_YEARS = 15
HARD_START_MONTH = "2022-06"


def _enforce_month_sequence(df: pd.DataFrame) -> pd.DataFrame:
    working = df.copy().reset_index(drop=True)
    if "month" not in working.columns:
        working["month"] = ""

    start_period = pd.Period(HARD_START_MONTH, freq="M")
    for idx in range(len(working)):
        working.at[idx, "month"] = str(start_period + idx)
    return working


def _prepare_base_payments_df(raw_payments: list[dict] | None) -> pd.DataFrame:
    payments_df = pd.DataFrame(raw_payments or [])
    if payments_df.empty:
        payments_df = pd.DataFrame(columns=["month", "interest_charged", "emi_paid", "extra_principal"])

    if "interest_charged" not in payments_df.columns and "interest_paid" in payments_df.columns:
        payments_df["interest_charged"] = payments_df["interest_paid"]

    for col, default in [
        ("month", ""),
        ("interest_charged", None),
        ("emi_paid", 0.0),
        ("extra_principal", 0.0),
    ]:
        if col not in payments_df.columns:
            payments_df[col] = default

    payments_df = payments_df[["month", "interest_charged", "emi_paid", "extra_principal"]].copy()
    for numeric_col in ["interest_charged", "emi_paid", "extra_principal"]:
        payments_df[numeric_col] = pd.to_numeric(payments_df[numeric_col], errors="coerce")

    payments_df = _enforce_month_sequence(payments_df)
    if payments_df.empty:
        payments_df = pd.DataFrame(
            [{"month": HARD_START_MONTH, "interest_charged": None, "emi_paid": 0.0, "extra_principal": 0.0}]
        )
    return payments_df.reset_index(drop=True)


def _with_derived_columns(df: pd.DataFrame, principal: float) -> pd.DataFrame:
    working = df.copy().reset_index(drop=True)
    for numeric_col in ["interest_charged", "emi_paid", "extra_principal"]:
        working[numeric_col] = pd.to_numeric(working[numeric_col], errors="coerce")

    opening = float(principal)
    principal_from_emi_list: list[float] = []
    interest_rate_pct_list: list[float | None] = []

    for _, row in working.iterrows():
        interest = max(0.0, float(row["interest_charged"])) if pd.notna(row["interest_charged"]) else 0.0
        emi = max(0.0, float(row["emi_paid"])) if pd.notna(row["emi_paid"]) else 0.0
        extra = max(0.0, float(row["extra_principal"])) if pd.notna(row["extra_principal"]) else 0.0

        principal_from_emi = max(0.0, emi - interest)
        principal_reduction = max(0.0, principal_from_emi + extra)
        shortfall = max(0.0, interest - emi)

        if opening > 0 and interest > 0:
            interest_rate_pct_list.append(round((interest * 12 * 100) / opening, 4))
        else:
            interest_rate_pct_list.append(None)

        closing = max(0.0, opening - principal_reduction + shortfall)
        principal_from_emi_list.append(round(principal_from_emi, 2))
        opening = closing

    working["principal_from_emi_calc"] = principal_from_emi_list
    working["interest_rate_pct_calc"] = interest_rate_pct_list
    return working

st.set_page_config(page_title="Home Loan Tracker", layout="wide")
st.title("🏠 Home Loan Tracker")
st.caption(
    "Track EMI, interest, principal, and extra pre-payments with floating interest changes."
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');

    html, body, [class*="css"]  {
        font-family: 'Inter', sans-serif;
    }

    [data-testid="stAppViewContainer"] {
        background: linear-gradient(120deg, #f5f9ff 0%, #eef3ff 40%, #f9fbff 100%);
    }

    .main .block-container {
        padding-top: 1.3rem;
        padding-bottom: 2rem;
    }

    h1, h2, h3 {
        color: #0f2f57;
        letter-spacing: -0.02em;
    }

    [data-testid="stMetric"] {
        background: white;
        border: 1px solid #dbe7ff;
        border-radius: 14px;
        padding: 12px;
        box-shadow: 0 6px 24px rgba(15, 47, 87, 0.08);
    }

    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #ffffff 0%, #f7faff 100%);
        border-right: 1px solid #e6efff;
    }

    .hero-card {
        background: linear-gradient(130deg, #ffffff 0%, #f1f6ff 55%, #e8f1ff 100%);
        border: 1px solid #dbe7ff;
        border-radius: 16px;
        padding: 14px 18px;
        margin-bottom: 12px;
        box-shadow: 0 8px 24px rgba(15, 47, 87, 0.08);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero-card">
            <strong>Smart monthly tracking</strong><br/>
            Just enter each month’s <code>-x interest</code> and <code>+y EMI</code>. The app auto-computes principal reduction and balance.
    </div>
    """,
    unsafe_allow_html=True,
)

DATA_PATH = Path("data/loan_data.json")
data = load_data(DATA_PATH)

with st.sidebar:
    st.header("Loan Baseline (hardcoded)")
    st.caption("These are fixed from your provided details.")
    st.markdown(f"**Disbursed amount:** ₹ {HARD_PRINCIPAL:,.2f}")
    st.markdown(f"**Disbursement date:** {HARD_DISBURSEMENT_DATE}")
    st.markdown(f"**Repayment start month:** {HARD_START_DATE[:7]}")
    st.markdown(f"**Tenure:** {HARD_TENURE_YEARS} years")

    assumed_annual_rate = st.number_input(
        "Assumed annual rate for projection (%)",
        min_value=0.0,
        value=float(data["loan"].get("assumed_annual_rate", 8.5) or 8.5),
        step=0.1,
        format="%.4f",
        help="Used for projection when month-wise rate/interest is not provided.",
    )

    project_to_end = st.toggle("Show projected future schedule", value=True)

def _load_saved_payments() -> list[dict]:
    """Load payments from disk as the single source of truth."""
    saved = load_data(DATA_PATH)
    return list(saved.get("payments", []) or [])


def _normalize_payments(raw_payments: list[dict]) -> list[dict]:
    """Sort by month and normalize keys/values."""
    normalized: list[dict] = []
    for entry in raw_payments:
        month = str(entry.get("month", "") or "").strip()
        if not month:
            continue
        interest = entry.get("interest_charged")
        if interest in (None, ""):
            interest = entry.get("interest_paid")
        normalized.append(
            {
                "month": month,
                "interest_charged": float(interest) if interest not in (None, "") else 0.0,
                "emi_paid": float(entry.get("emi_paid", 0) or 0),
                "extra_principal": float(entry.get("extra_principal", 0) or 0),
                "interest_paid": float(interest) if interest not in (None, "") else 0.0,
            }
        )
    normalized.sort(key=lambda x: x["month"])
    return normalized


def _next_month(payments: list[dict]) -> str:
    """Return the next month to add based on existing saved entries."""
    if not payments:
        return HARD_START_MONTH
    last = max(p["month"] for p in payments)
    return str(pd.Period(last, freq="M") + 1)


def _persist(payments: list[dict]) -> None:
    payload_to_save = {
        "loan": {
            "principal": HARD_PRINCIPAL,
            "disbursement_date": HARD_DISBURSEMENT_DATE,
            "start_date": HARD_START_DATE,
            "tenure_years": HARD_TENURE_YEARS,
            "assumed_annual_rate": float(assumed_annual_rate),
        },
        "rate_changes": [],
        "payments": _normalize_payments(payments),
    }
    save_data(DATA_PATH, payload_to_save)


# Source of truth is always the saved file (prevents entries disappearing).
saved_payments = _normalize_payments(_load_saved_payments())

st.subheader("1) Add a monthly entry")
st.caption("Fill the fields below and click **Add / Update entry**. It saves instantly.")

suggested_month = _next_month(saved_payments)

with st.form("add_entry_form", clear_on_submit=True):
    form_cols = st.columns([1, 1, 1, 1])
    with form_cols[0]:
        entry_month = st.text_input(
            "Month (YYYY-MM)",
            value=suggested_month,
            help="Next month is auto-suggested. You can also edit an existing month to update it.",
        )
    with form_cols[1]:
        entry_interest = st.number_input(
            "Interest charged (-x)", min_value=0.0, value=0.0, step=100.0, format="%.2f"
        )
    with form_cols[2]:
        entry_emi = st.number_input(
            "EMI paid (+y)", min_value=0.0, value=0.0, step=100.0, format="%.2f"
        )
    with form_cols[3]:
        entry_extra = st.number_input(
            "Extra principal", min_value=0.0, value=0.0, step=100.0, format="%.2f"
        )

    submitted = st.form_submit_button("➕ Add / Update entry", type="primary", use_container_width=True)

if submitted:
    month_key = str(entry_month or "").strip()
    valid_month = True
    try:
        month_key = str(pd.Period(month_key, freq="M"))
    except Exception:
        valid_month = False

    if not valid_month:
        st.error("Please enter a valid month in YYYY-MM format (e.g. 2026-07).")
    else:
        # Update if month exists, else append.
        updated = False
        for p in saved_payments:
            if p["month"] == month_key:
                p["interest_charged"] = float(entry_interest)
                p["interest_paid"] = float(entry_interest)
                p["emi_paid"] = float(entry_emi)
                p["extra_principal"] = float(entry_extra)
                updated = True
                break
        if not updated:
            saved_payments.append(
                {
                    "month": month_key,
                    "interest_charged": float(entry_interest),
                    "interest_paid": float(entry_interest),
                    "emi_paid": float(entry_emi),
                    "extra_principal": float(entry_extra),
                }
            )
        saved_payments = _normalize_payments(saved_payments)
        _persist(saved_payments)
        st.success(f"{'Updated' if updated else 'Added'} entry for {month_key} and saved.")

# Delete controls
if saved_payments:
    del_cols = st.columns([2, 1])
    with del_cols[0]:
        month_to_delete = st.selectbox(
            "Delete an entry (optional)",
            options=["—"] + [p["month"] for p in saved_payments],
        )
    with del_cols[1]:
        st.write("")
        st.write("")
        if st.button("🗑️ Delete", use_container_width=True) and month_to_delete != "—":
            saved_payments = [p for p in saved_payments if p["month"] != month_to_delete]
            saved_payments = _normalize_payments(saved_payments)
            _persist(saved_payments)
            st.success(f"Deleted entry for {month_to_delete}.")

st.subheader("2) All entries")
if not saved_payments:
    st.info("No entries yet. Add your first month above (starts at 2022-06).")
    display_df = pd.DataFrame(columns=["month", "interest_charged", "emi_paid", "extra_principal"])
else:
    display_df = pd.DataFrame(saved_payments)[["month", "interest_charged", "emi_paid", "extra_principal"]]

display_df = _with_derived_columns(display_df, HARD_PRINCIPAL) if not display_df.empty else display_df

st.dataframe(
    display_df,
    use_container_width=True,
    hide_index=True,
)

payments_for_engine = pd.DataFrame(saved_payments) if saved_payments else pd.DataFrame(
    columns=["month", "interest_charged", "emi_paid", "extra_principal", "interest_paid"]
)

payload = {
    "loan": {
        "principal": HARD_PRINCIPAL,
        "disbursement_date": HARD_DISBURSEMENT_DATE,
        "start_date": HARD_START_DATE,
        "tenure_years": HARD_TENURE_YEARS,
        "assumed_annual_rate": float(assumed_annual_rate),
    },
    "rate_changes": [],
    "payments": _normalize_payments(saved_payments),
}

schedule = build_schedule(
    payload["loan"],
    payload["rate_changes"],
    payload["payments"],
    as_of_month=date.today().strftime("%Y-%m"),
    project_to_end=project_to_end,
)
summary = summarize_schedule(schedule)

rows_missing_interest_context = schedule[
    (schedule["is_projected"] == False)  # noqa: E712
    & (schedule["emi_paid"] > 0)
    & (schedule["interest_component"] == 0)
    & (schedule["opening_principal"] > 0)
]

if not rows_missing_interest_context.empty:
    st.info(
        "Some rows have EMI but no monthly interest value. "
        "To match bank statement exactly, fill `Interest charged (-x)` for each month."
    )

st.subheader("2) Summary")
metric1, metric2, metric3, metric4 = st.columns(4)
metric1.metric("Total paid till date", f"₹ {summary['total_paid']:,.2f}")
metric2.metric("Principal paid", f"₹ {summary['principal_paid']:,.2f}")
metric3.metric("Interest paid", f"₹ {summary['interest_paid']:,.2f}")
metric4.metric("Outstanding (current)", f"₹ {summary['outstanding']:,.2f}")

if project_to_end:
    st.caption(f"Projected outstanding at closure: ₹ {summary['outstanding_projected']:,.2f}")

if schedule.empty:
    st.warning("Add at least one monthly entry to generate schedule.")
else:
    st.subheader("3) Payment composition")
    actual_schedule = schedule[schedule["is_projected"] == False]  # noqa: E712
    latest_actual_outstanding = (
        float(actual_schedule.iloc[-1]["closing_principal"])
        if not actual_schedule.empty
        else float(payload["loan"]["principal"])
    )

    paid_split_df = pd.DataFrame(
        {
            "component": ["Principal paid", "Interest paid"],
            "amount": [summary["principal_paid"], summary["interest_paid"]],
        }
    )
    paid_split_df = paid_split_df[paid_split_df["amount"] > 0]

    portfolio_df = pd.DataFrame(
        {
            "component": ["Principal paid", "Interest paid", "Outstanding"],
            "amount": [
                summary["principal_paid"],
                summary["interest_paid"],
                max(0.0, latest_actual_outstanding),
            ],
        }
    )
    portfolio_df = portfolio_df[portfolio_df["amount"] > 0]

    pie_col1, pie_col2 = st.columns(2)
    with pie_col1:
        if paid_split_df.empty:
            st.info("Pie chart will appear after at least one payment entry.")
        else:
            paid_fig = px.pie(
                paid_split_df,
                names="component",
                values="amount",
                hole=0.55,
                color="component",
                color_discrete_map={
                    "Principal paid": "#2e8bff",
                    "Interest paid": "#f27f3d",
                },
            )
            paid_fig.update_layout(
                title="Paid amount split (donut)",
                legend_title_text="",
                margin=dict(l=10, r=10, t=50, b=10),
            )
            st.plotly_chart(paid_fig, use_container_width=True)

    with pie_col2:
        if portfolio_df.empty:
            st.info("Loan composition chart will appear when amounts are available.")
        else:
            portfolio_fig = px.pie(
                portfolio_df,
                names="component",
                values="amount",
                hole=0.35,
                color="component",
                color_discrete_map={
                    "Principal paid": "#2e8bff",
                    "Interest paid": "#f27f3d",
                    "Outstanding": "#6b7b95",
                },
            )
            portfolio_fig.update_layout(
                title="Loan composition (till date)",
                legend_title_text="",
                margin=dict(l=10, r=10, t=50, b=10),
            )
            st.plotly_chart(portfolio_fig, use_container_width=True)

    st.subheader("4) Balance trend")
    trend_df = schedule[["month", "closing_principal", "is_projected"]].copy()
    trend_fig = px.line(
        trend_df,
        x="month",
        y="closing_principal",
        color="is_projected",
        markers=True,
        color_discrete_map={False: "#2e8bff", True: "#9db4d8"},
        labels={
            "month": "Month",
            "closing_principal": "Closing principal",
            "is_projected": "Projected",
        },
    )
    trend_fig.update_layout(
        template="plotly_white",
        legend_title_text="",
        margin=dict(l=10, r=10, t=20, b=10),
    )
    st.plotly_chart(trend_fig, use_container_width=True)

    st.subheader("5) Full amortization")
    st.dataframe(schedule, use_container_width=True)

    csv = schedule.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download schedule CSV",
        data=csv,
        file_name="loan_schedule.csv",
        mime="text/csv",
    )
