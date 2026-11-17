"""Where prices come from, by country and currency. A STRUCTURE for the owner to fill in, not prices.

VIDHI invents no price. Each price is an environment setting; a plan is offered in a currency only when its setting exists. A country is open for sale only when
lib/jurisdictions.py says it is live (its law library and readiness have been checked), whatever prices are set. Today that is India. The other countries
(AE, UK, US, SG) have a currency and a setting name reserved so that opening one later is a settings change plus the legal and tax work, not a rewrite.

No tax or GST is calculated or shown anywhere: whether and how it applies is a decision for the owner and an accountant (docs/PAYMENTS.md)."""

import os

from lib.jurisdictions import REGISTRY

# (currency) -> (monthly env, yearly env). INR and USD are the settings the payment code already uses; the others are reserved names for later.
PRICE_ENV: dict[str, tuple[str, str]] = {
    "INR": ("PRO_PRICE_AMOUNT", "PRO_PRICE_YEARLY_AMOUNT"),
    "USD": ("PRO_PRICE_USD", "PRO_PRICE_USD_YEARLY"),
    "AED": ("PRO_PRICE_AED", "PRO_PRICE_AED_YEARLY"),
    "GBP": ("PRO_PRICE_GBP", "PRO_PRICE_GBP_YEARLY"),
    "SGD": ("PRO_PRICE_SGD", "PRO_PRICE_SGD_YEARLY"),
}
# Reserved settings that no payment code reads yet: set today they do nothing, and the table says so.
IN_USE = {"INR", "USD"}


def _set(name: str) -> bool:
    return bool((os.environ.get(name) or "").strip())


def table() -> list[dict]:
    rows = []
    for code, j in REGISTRY.items():
        monthly_env, yearly_env = PRICE_ENV[j.currency]
        rows.append({
            "country": code, "country_name": j.name, "country_status": j.status, "currency": j.currency,
            "monthly_setting": monthly_env, "monthly_set": _set(monthly_env) or (j.currency == "INR"),  # INR monthly has a built-in default only for development: set it for real
            "yearly_setting": yearly_env, "yearly_set": _set(yearly_env),
            "payment_code_reads_these": j.currency in IN_USE,
            "open_for_sale": j.status == "live" and j.currency in IN_USE,
            "note": ("Live. Set the prices you have decided." if j.status == "live" else "Not live: no law library or readiness check for this country yet, so nothing is sold for it."),
        })
    return rows