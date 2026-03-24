"""
data.py – Calculation logic without Pandas.
No config, no DB – pure calculations on lists of dicts.
"""

import sqlite3
from collections import defaultdict

# Defaults (standalone / fallback)
DEFAULT_PRICE_PER_KWH        = 0.37
DEFAULT_FEEDIN_PRICE_PER_KWH = 0.00
DEFAULT_BASE_PRICE_PER_MONTH = 15.0
DEFAULT_ALT_PRICE_PER_KWH    = 0.2939
DEFAULT_ALT_BASE_PER_MONTH   = 11.31
DEFAULT_FEEDIN_SCALE         = 0.10
DEFAULT_CURRENCY             = "EUR"


def load_reference_days(db_path, mac):
    """Load all stored reference days from the database for a given Shelly device."""
    con  = sqlite3.connect(db_path)
    rows = con.execute(
        "SELECT date, ts_start, ts_end, consumption_wh, feedin_wh "
        "FROM reference_days WHERE mac = ? ORDER BY date",
        (mac,)
    ).fetchall()
    con.close()
    return [
        {
            "date":           r[0],
            "ts_start":       r[1],
            "ts_end":         r[2],
            "consumption_wh": r[3],
            "feedin_wh":      r[4],
        }
        for r in rows
    ]


def calculate_monthly(records, price_per_kwh=DEFAULT_PRICE_PER_KWH):
    """Aggregate reference days into monthly totals, converting Wh to kWh."""
    buckets = defaultdict(lambda: {"consumption_wh": 0.0, "feedin_wh": 0.0})
    for r in records:
        month = r["date"][:7]   # YYYY-MM
        buckets[month]["consumption_wh"] += r["consumption_wh"]
        buckets[month]["feedin_wh"]      += r["feedin_wh"]

    return [
        {
            "month":           month,
            "consumption_kwh": buckets[month]["consumption_wh"] / 1000,
            "feedin_kwh":      buckets[month]["feedin_wh"] / 1000,
            "energy_cost":     buckets[month]["consumption_wh"] / 1000 * price_per_kwh,
        }
        for month in sorted(buckets)
    ]


def calculate_yearly(monthly, price_per_kwh=DEFAULT_PRICE_PER_KWH):
    """Aggregate monthly totals into yearly totals."""
    buckets = defaultdict(lambda: {"consumption_kwh": 0.0, "feedin_kwh": 0.0, "month_count": 0})
    for m in monthly:
        year = m["month"][:4]   # YYYY
        buckets[year]["consumption_kwh"] += m["consumption_kwh"]
        buckets[year]["feedin_kwh"]      += m["feedin_kwh"]
        buckets[year]["month_count"]     += 1

    return [
        {
            "year":            year,
            "consumption_kwh": buckets[year]["consumption_kwh"],
            "feedin_kwh":      buckets[year]["feedin_kwh"],
            "energy_cost":     buckets[year]["consumption_kwh"] * price_per_kwh,
            "month_count":     buckets[year]["month_count"],
        }
        for year in sorted(buckets)
    ]


def cost_summary_monthly(monthly,
                         price_per_kwh        = DEFAULT_PRICE_PER_KWH,
                         base_price_per_month = DEFAULT_BASE_PRICE_PER_MONTH,
                         alt_price_per_kwh    = DEFAULT_ALT_PRICE_PER_KWH,
                         alt_base_per_month   = DEFAULT_ALT_BASE_PER_MONTH):
    """Calculate costs per month for the current and an alternative tariff."""
    return [
        {
            "month":        m["month"],
            "cur_variable": m["consumption_kwh"] * price_per_kwh,
            "cur_base":     base_price_per_month,
            "cur_total":    m["consumption_kwh"] * price_per_kwh + base_price_per_month,
            "alt_variable": m["consumption_kwh"] * alt_price_per_kwh,
            "alt_base":     alt_base_per_month,
            "alt_total":    m["consumption_kwh"] * alt_price_per_kwh + alt_base_per_month,
            "diff":         (m["consumption_kwh"] * price_per_kwh + base_price_per_month) -
                            (m["consumption_kwh"] * alt_price_per_kwh + alt_base_per_month),
        }
        for m in monthly
    ]


def cost_summary_yearly(yearly,
                        price_per_kwh        = DEFAULT_PRICE_PER_KWH,
                        base_price_per_month = DEFAULT_BASE_PRICE_PER_MONTH,
                        alt_price_per_kwh    = DEFAULT_ALT_PRICE_PER_KWH,
                        alt_base_per_month   = DEFAULT_ALT_BASE_PER_MONTH):
    """Calculate costs per year; base price is prorated by actual months recorded."""
    return [
        {
            "year":         y["year"],
            "month_count":  y["month_count"],
            "cur_variable": y["consumption_kwh"] * price_per_kwh,
            "cur_base":     y["month_count"] * base_price_per_month,
            "cur_total":    y["consumption_kwh"] * price_per_kwh + y["month_count"] * base_price_per_month,
            "alt_variable": y["consumption_kwh"] * alt_price_per_kwh,
            "alt_base":     y["month_count"] * alt_base_per_month,
            "alt_total":    y["consumption_kwh"] * alt_price_per_kwh + y["month_count"] * alt_base_per_month,
            "diff":         (y["consumption_kwh"] * price_per_kwh + y["month_count"] * base_price_per_month) -
                            (y["consumption_kwh"] * alt_price_per_kwh + y["month_count"] * alt_base_per_month),
        }
        for y in yearly
    ]