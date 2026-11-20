"""
Live AI verification utility for ArthaShield.

Runs the real advisor path against the real Gemini API using synthetic data
and reports exactly what happened. It is the tool to use when a credential is
available and the live path has to be proven.

Usage (from the ``backend`` directory):

    set GEMINI_API_KEY=<your key>          # Windows PowerShell
    export GEMINI_API_KEY=<your key>       # Linux / macOS
    python verify_live_ai.py

    python verify_live_ai.py --model gemini-3.8-flash

The key is read from the environment only. It is never printed, never written
to a file and never logged: the report below shows only whether a key was
present and how long it is.

Exit codes:
    0  a genuine live request succeeded and passed every check
    1  the live request did not succeed (the report says why)
    2  the environment is not usable (no key / no Django setup)
"""

import argparse
import json
import os
import sys

import django


SYNTHETIC_TRANSACTIONS = """Account Statement - Synthetic Bank
Account Holder: [USER_PRIMARY]
Account Number: [REDACTED_ACCOUNT]
2026-10-01 ACH CRED SYNTHETIC EMPLOYER STIPEND 75000.00
2026-10-05 POS SYNTHETIC STREAMING SUBSCRIPTION 649.00
2026-10-07 LANDLORD RENT TRANSFER 25000.00
2026-10-08 UPI/SELF/TRANSFER 10000.00
2026-10-09 POS SYNTHETIC GROCERY ORDER 5000.00
2026-10-10 REFUND SYNTHETIC GROCERY ORDER 5000.00"""

SYNTHETIC_METRICS = {
    "health_score": 78,
    "health_grade": "A (Strong)",
    "emergency_runway_months": 3.5,
    "monthly_income": 75000.0,
    "monthly_expenses": 25769.0,
    "monthly_leakage": 649.0,
    "safe_to_spend_daily": 1200.0,
    "recurring_commitments": {
        "monthly_commitments": 25649.0,
        "monthly_leakage": 649.0,
        "confirmed_commitment_count": 2,
        "recurring_pattern_count": 2,
    },
}

PII_PROBES = (
    "998877665544",
    "9876543210",
    "ABCDE1234F",
    "Rajesh",
    "Verma",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the live Gemini path.")
    parser.add_argument(
        "--model",
        default=None,
        help="Override the model for this run (default: GEMINI_MODEL or the built-in default).",
    )
    args = parser.parse_args()

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
    try:
        django.setup()
    except Exception as exc:  # pragma: no cover - environment guard
        print(f"FAIL  Django could not be set up: {type(exc).__name__}")
        return 2

    from advisor.services import AdvisorService

    if args.model:
        os.environ["GEMINI_MODEL"] = args.model

    api_key = os.environ.get("GEMINI_API_KEY")
    print("=" * 68)
    print("ArthaShield - live AI verification")
    print("=" * 68)
    print(f"API key present : {'yes' if api_key else 'no'}")
    if api_key:
        print(f"API key length  : {len(api_key)} characters (value never shown)")
    print(f"Model requested : {AdvisorService.get_model()}")
    print(f"Endpoint        : generativelanguage.googleapis.com (v1, v1beta fallback)")
    print(f"Timeout         : {AdvisorService.REQUEST_TIMEOUT}s")
    print()

    if not api_key:
        print("BLOCKER  GEMINI_API_KEY is not set, so no live request was made.")
        print("         Set the key in the environment and run this script again.")
        print()
        result = AdvisorService.analyze_sanitized_statement(
            SYNTHETIC_TRANSACTIONS, SYNTHETIC_METRICS
        )
        print("Offline fallback check (runs without a key):")
        print(f"  source                : {result['source']}")
        print(f"  engine_label          : {result['engine_label']}")
        print(f"  numeric_claims_verified: {result['numeric_claims_verified']}")
        print(f"  unverified claims     : {result['unverified_amount_claims']}")
        return 1

    result = AdvisorService.analyze_sanitized_statement(
        SYNTHETIC_TRANSACTIONS, SYNTHETIC_METRICS
    )

    print("-" * 68)
    print("RESULT")
    print("-" * 68)
    print(f"source                 : {result.get('source')}")
    print(f"is_ai_generated         : {result.get('is_ai_generated')}")
    print(f"engine_label            : {result.get('engine_label')}")
    print(f"model                   : {result.get('model')}")
    print(f"numeric_claims_verified : {result.get('numeric_claims_verified')}")
    print(f"unverified_amount_claims: {result.get('unverified_amount_claims')}")
    print()

    serialized = json.dumps(result, indent=2)
    leaked = [probe for probe in PII_PROBES if probe in serialized]
    if leaked:
        print(f"FAIL  personal identifiers present in the response: {leaked}")
        return 1
    print("PASS  no personal identifiers in the response")

    if api_key and api_key in serialized:
        print("FAIL  the API key leaked into the response")
        return 1
    print("PASS  the API key did not leak into the response")

    if result.get("source") != "LIVE_GEMINI":
        print()
        print("FAIL  the live request did not succeed. The deterministic fallback was")
        print("      used instead, which is the designed fail-safe behaviour.")
        print("      Check the key, the account's access to the model, and the")
        print("      network path to generativelanguage.googleapis.com.")
        return 1

    print()
    print("PASS  a genuine live Gemini request succeeded")
    print()
    print("Live model answer (synthetic data only):")
    print(json.dumps(
        {
            "plain_english_summary": result.get("plain_english_summary"),
            "top_actionable_wins": result.get("top_actionable_wins"),
            "hidden_risks_and_predatory_clauses": result.get(
                "hidden_risks_and_predatory_clauses"
            ),
            "disclaimer": result.get("disclaimer"),
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
