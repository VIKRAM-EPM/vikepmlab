# =============================================================================
# validator.py — Phase 2: Validate unique dimension values
#
# Input  : unique member dict from importStep.py
#          { epm_dim: { member_value: [filename, ...] } }
#
# TWO MODES — controlled by VALIDATION_MODE in config.py:
#
#   VALIDATION_MODE = "mock"  (default)
#     Validates against a locally-defined mock member set built from the
#     known Kaggle "Retail Store Sales" dataset values. No EPM connection
#     required — good for the blog demo and for local testing.
#
#     To see an `invalid` result: open the CSV (or a copy of it), add a row
#     with a made-up Category/Item/Payment Method value that does NOT appear
#     in MOCK_EPM_MEMBERS below, then re-run importStep.py + validator.py.
#     That value won't be in the mock set, so it will correctly show up
#     under `invalid`.
#
#   VALIDATION_MODE = "live"
#     Validates against a real Oracle EPM Cloud instance via the
#     Get Dimension Details REST API (one call per dimension).
#     Requires EPM_BASE_URL / EPM_APPLICATION / EPM_PLAN_TYPE /
#     EPM_USERNAME / EPM_PASSWORD set in config.py.
# =============================================================================

import logging

from config import VALIDATION_MODE

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MOCK EPM DIMENSION MEMBERS
#
# Built from the actual Kaggle "Retail Store Sales" dataset structure —
# represents "what EPM would say these dimensions contain" for demo purposes.
#   Product_Category : the 8 real Category values in the dataset
#   Tender_Type       : the 3 real Payment Method values in the dataset
#   SKU               : all 200 real Item values (25 items x 8 categories),
#                       generated here instead of hand-typed
# ---------------------------------------------------------------------------

MOCK_EPM_MEMBERS: dict[str, set[str]] = {
    "Product_Category": {
        "Beverages",
        "Butchers",
        "Computers and electric accessories",
        "Electric household essentials",
        "Food",
        "Furniture",
        "Milk Products",
        "Patisserie",
    },
    "Tender_Type": {"Cash", "Credit Card", "Digital Wallet"},
    "SKU": {
        f"Item_{n}_{suffix}"
        for n in range(1, 26)
        for suffix in ["BEV", "BUT", "CEA", "EHE", "FOOD", "FUR", "MILK", "PAT"]
    },
}


# ---------------------------------------------------------------------------
# Public entry point — called by main.py
# ---------------------------------------------------------------------------

def validate_members(
    extracted: dict[str, dict[str, list[str]]]
) -> dict[str, dict]:
    """
    Validate all extracted members against EPM (mock or live — see
    _fetch_dimension_members switch at the bottom of this file).

    Args:
        extracted: output from importStep.extract_unique_members()
                   { epm_dim: { member_value: [filename, ...] } }

    Returns:
        {
            "Product_Category": {
                "valid":     { "Food": ["retail_store_sales.csv"] },
                "invalid":   { "Frozen Meals": ["retail_store_sales.csv"] },
                "api_error": {},   # only populated if a live REST call failed
            },
            "SKU": { ... },
            "Tender_Type": { ... },
        }
    """
    results: dict[str, dict] = {}

    for epm_dim, members in extracted.items():
        log.info(
            "Checking dimension '%s' (%d CSV value(s) to validate) ...",
            epm_dim, len(members)
        )

        epm_member_set, fetch_ok = _fetch_dimension_members(epm_dim)

        if not fetch_ok:
            log.error(
                "  Failed to fetch dimension '%s' — all %d value(s) marked api_error",
                epm_dim, len(members)
            )
            results[epm_dim] = {
                "valid":     {},
                "invalid":   {},
                "api_error": dict(members),
            }
            continue

        valid:   dict[str, list[str]] = {}
        invalid: dict[str, list[str]] = {}

        for member_value, file_list in members.items():
            if member_value in epm_member_set:
                valid[member_value] = file_list
            else:
                invalid[member_value] = file_list

        results[epm_dim] = {
            "valid":     valid,
            "invalid":   invalid,
            "api_error": {},
        }

        log.info("  valid=%d  invalid=%d", len(valid), len(invalid))

    return results


# ---------------------------------------------------------------------------
# MOCK fetch — no network call, just looks up the hardcoded set above
# ---------------------------------------------------------------------------

def _fetch_dimension_members_mock(epm_dim: str) -> tuple[set[str], bool]:
    if epm_dim not in MOCK_EPM_MEMBERS:
        log.error("No mock members defined for dimension '%s'", epm_dim)
        return set(), False
    return MOCK_EPM_MEMBERS[epm_dim], True


# ---------------------------------------------------------------------------
# LIVE fetch — calls real Oracle EPM Cloud Get Dimension Details API
#
# GET /HyperionPlanning/rest/v3/applications/{app}
#     /plantypes/{plantype}/dimensions/{dimname}?fields=name,children
#
# Response is a nested JSON tree; we recurse through it and collect every
# "name" value into a flat set.
# ---------------------------------------------------------------------------

def _fetch_dimension_members_live(epm_dim: str) -> tuple[set[str], bool]:
    import time
    import urllib.parse

    import requests
    from requests.auth import HTTPBasicAuth
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    from config import (
        EPM_BASE_URL,
        EPM_APPLICATION,
        EPM_PLAN_TYPE,
        EPM_USERNAME,
        EPM_PASSWORD,
        EPM_REQUEST_TIMEOUT,
        EPM_MAX_RETRIES,
        EPM_RETRY_BACKOFF,
    )

    session = requests.Session()
    adapter = HTTPAdapter(
        max_retries=Retry(total=0, raise_on_status=False),
        pool_connections=5,
        pool_maxsize=10,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    encoded_dim   = urllib.parse.quote(epm_dim, safe="")
    encoded_app   = urllib.parse.quote(EPM_APPLICATION, safe="")
    encoded_ptype = urllib.parse.quote(EPM_PLAN_TYPE, safe="")

    url = (
        f"{EPM_BASE_URL}/applications/{encoded_app}"
        f"/plantypes/{encoded_ptype}"
        f"/dimensions/{encoded_dim}"
        f"?fields=name,children"
    )

    attempt = 0
    while attempt <= EPM_MAX_RETRIES:
        try:
            log.debug("GET %s", url)
            response = session.get(
                url,
                auth=HTTPBasicAuth(EPM_USERNAME, EPM_PASSWORD),
                timeout=EPM_REQUEST_TIMEOUT,
            )

            if response.status_code in (200, 201):
                data = response.json()
                member_set: set[str] = set()
                _collect_names(data, member_set)
                session.close()
                return member_set, True

            if response.status_code == 401:
                log.error("Auth failed (401) — check EPM_USERNAME / EPM_PASSWORD in config.py")
                session.close()
                return set(), False

            if response.status_code == 403:
                log.error("Forbidden (403) — check account role for dim='%s'", epm_dim)
                session.close()
                return set(), False

            if response.status_code == 404:
                log.error(
                    "Dimension '%s' not found in plantype '%s' (404) — "
                    "check EPM_PLAN_TYPE / dimension name in config.py",
                    epm_dim, EPM_PLAN_TYPE
                )
                session.close()
                return set(), False

            if response.status_code >= 500:
                log.warning(
                    "EPM 5xx (%d) fetching dim='%s' — attempt %d/%d",
                    response.status_code, epm_dim, attempt + 1, EPM_MAX_RETRIES + 1,
                )
            else:
                log.warning("Unexpected HTTP %d fetching dim='%s'", response.status_code, epm_dim)
                session.close()
                return set(), False

        except requests.exceptions.Timeout:
            log.warning("Timeout fetching dim='%s' — attempt %d/%d", epm_dim, attempt + 1, EPM_MAX_RETRIES + 1)
        except requests.exceptions.ConnectionError as exc:
            log.warning("Connection error fetching dim='%s': %s — attempt %d/%d", epm_dim, exc, attempt + 1, EPM_MAX_RETRIES + 1)

        attempt += 1
        if attempt <= EPM_MAX_RETRIES:
            sleep_secs = EPM_RETRY_BACKOFF * (2 ** (attempt - 1))
            log.info("Retrying in %ds ...", sleep_secs)
            time.sleep(sleep_secs)

    log.error("All %d attempts failed fetching dimension '%s'", EPM_MAX_RETRIES + 1, epm_dim)
    session.close()
    return set(), False


def _collect_names(node: dict, name_set: set[str]) -> None:
    name = node.get("name")
    if name:
        name_set.add(name)
    for child in node.get("children", []):
        _collect_names(child, name_set)


# =============================================================================
# ACTIVE MODE SWITCH
#   Mock  (default, no EPM needed) : _fetch_dimension_members_mock
#   Live  (real EPM REST calls)    : _fetch_dimension_members_live
# =============================================================================

# =============================================================================
# ACTIVE MODE — controlled by VALIDATION_MODE in config.py ("mock" or "live")
# =============================================================================

if VALIDATION_MODE == "live":
    _fetch_dimension_members = _fetch_dimension_members_live
elif VALIDATION_MODE == "mock":
    _fetch_dimension_members = _fetch_dimension_members_mock
else:
    raise ValueError(
        f"Unknown VALIDATION_MODE '{VALIDATION_MODE}' in config.py — "
        f"must be 'mock' or 'live'"
    )


# ---------------------------------------------------------------------------
# Entry point — smoke test
# Usage: python3 validator.py
# (Run importStep.py first, or wire this up in main.py, to get real
#  `extracted` data — this block below is just a standalone sanity check
#  using a tiny hand-built sample.)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    sample_extracted = {
        "Product_Category": {
            "Food": ["retail_store_sales.csv"],
            "Frozen Meals": ["retail_store_sales.csv"],  # not a real category — should be invalid
        },
        "Tender_Type": {
            "Cash": ["retail_store_sales.csv"],
        },
    }

    results = validate_members(sample_extracted)

    print("\n" + "=" * 70)
    for dim, buckets in results.items():
        print(f"{dim}: valid={len(buckets['valid'])} invalid={len(buckets['invalid'])} api_error={len(buckets['api_error'])}")
        if buckets["invalid"]:
            print(f"  invalid values: {list(buckets['invalid'].keys())}")
    print("=" * 70)