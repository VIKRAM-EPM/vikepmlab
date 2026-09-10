# =============================================================================
# main.py — Orchestrator: Import -> Validate -> Notify
#
# Runs the full pre-load check pipeline:
#   1. importStep.extract_unique_members()  -> unique dimension values + files
#   2. validator.validate_members()         -> checks values against EPM
#                                              (mock or live — see config.py
#                                              VALIDATION_MODE)
#   3. Prints a combined summary report
#   4. Emails the results (optional — see config.py SEND_EMAIL)
#
# Usage: python3 main.py
# =============================================================================

import logging

from importStep import extract_unique_members
from validator import validate_members
from notifier import send_validation_email
from config import SEND_EMAIL

log = logging.getLogger(__name__)


def run() -> dict:
    log.info("=" * 70)
    log.info("STEP 1 — IMPORT: extracting unique dimension values")
    log.info("=" * 70)
    extracted = extract_unique_members()

    log.info("=" * 70)
    log.info("STEP 2 — VALIDATE: checking values against EPM")
    log.info("=" * 70)
    results = validate_members(extracted)

    return results


def print_summary(results: dict) -> None:
    print("\n" + "=" * 78)
    print(f"{'DIMENSION':<20} {'VALID':>8} {'INVALID':>8} {'API_ERROR':>10}")
    print("=" * 78)

    total_invalid = 0
    for dim, buckets in results.items():
        valid_ct   = len(buckets["valid"])
        invalid_ct = len(buckets["invalid"])
        error_ct   = len(buckets["api_error"])
        total_invalid += invalid_ct
        print(f"{dim:<20} {valid_ct:>8} {invalid_ct:>8} {error_ct:>10}")

    print("=" * 78)

    if total_invalid == 0:
        print("Result: ALL DIMENSION VALUES VALID — safe to proceed with EPM load")
    else:
        print(f"Result: {total_invalid} INVALID VALUE(S) FOUND — load would fail in EPM")
        print("\nInvalid values by dimension:")
        for dim, buckets in results.items():
            if buckets["invalid"]:
                print(f"\n  [{dim}]")
                for value, files in buckets["invalid"].items():
                    file_list = ", ".join(files)
                    print(f"    '{value}'  (found in: {file_list})")

    print("=" * 78)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    results = run()
    print_summary(results)

    if SEND_EMAIL:
        log.info("=" * 70)
        log.info("STEP 3 — NOTIFY: emailing results")
        log.info("=" * 70)
        send_validation_email(results)
    else:
        log.info("SEND_EMAIL is False in config.py — skipping email step")