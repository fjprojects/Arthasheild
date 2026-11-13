import os
import sys
import django

# Setup Django standalone
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from rest_framework.test import APIRequestFactory
from api.views import (
    PersonaListView,
    SelectPersonaView,
    SanitizePreviewView,
    SimulateEmiView,
    NukeDataView
)

factory = APIRequestFactory()

def run_tests():
    print("=== TEST 1: Persona List ===")
    req1 = factory.get('/api/v1/personas/')
    resp1 = PersonaListView.as_view()(req1)
    print("Status:", resp1.status_code)
    assert resp1.status_code == 200
    print("Found personas:", len(resp1.data.get("personas", [])))

    print("\n=== TEST 2: Select Persona (Freelancer Rohit) ===")
    req2 = factory.post('/api/v1/personas/select/', {"persona_id": "persona_freelancer_rohit", "session_id": "test_session_1"}, format='json')
    resp2 = SelectPersonaView.as_view()(req2)
    print("Status:", resp2.status_code)
    assert resp2.status_code == 200
    print("Health Score:", resp2.data.get("health_metrics", {}).get("health_score"))
    print("Daily Safe to Spend:", resp2.data.get("safe_to_spend", {}).get("safe_to_spend_daily"))

    print("\n=== TEST 3: Privacy Inspector Sanitize Preview ===")
    sample_raw = """
Account Statement - Apex National Bank
Account Holder: Rohit Ramesh Verma
Account Number: 4821-9988-1200-5541
Registered Phone: +91-9876543210
Registered Email: rohit.verma.freelance@gmail.com
IFSC Code: APEX0001234
Date,Description,Debit
2026-10-04,UPI/SWIGGY/ORDER_9824219/swiggy@icici,480.00
2026-10-05,ACH DEBIT APEX BANK PHONE EMI NO-COST-882,5735.00
"""
    req3 = factory.post('/api/v1/privacy/sanitize-preview/', {"raw_text": sample_raw}, format='json')
    resp3 = SanitizePreviewView.as_view()(req3)
    print("Status:", resp3.status_code)
    assert resp3.status_code == 200
    print("Total Redactions Performed:", resp3.data.get("total_redactions_count"))
    print("Sanitized text preview:\n", resp3.data.get("sanitized_text_preview"))

    print("\n=== TEST 4: EMI Reality Check Simulator ===")
    req4 = factory.post('/api/v1/analytics/simulate-emi/', {
        "item_name": "Premium Laptop",
        "price": 80000,
        "tenure_months": 12,
        "nominal_apr": 0.0,
        "monthly_processing_fee": 199.0,
        "discretionary_buffer": 15000.0
    }, format='json')
    resp4 = SimulateEmiView.as_view()(req4)
    print("Status:", resp4.status_code)
    assert resp4.status_code == 200
    print("Advertised APR:", resp4.data.get("advertised_interest_rate_pct"), "%")
    print("True Effective APR:", resp4.data.get("true_effective_apr_pct"), "%")
    print("Total Hidden Fees + GST:", resp4.data.get("total_hidden_fees_and_gst"))
    print("Viability Verdict:", resp4.data.get("verdict"))

    print("\n=== TEST 5: One-Click Data Shredder (Nuke Data) ===")
    req5 = factory.post('/api/v1/privacy/nuke-data/', {"session_id": "test_session_1"}, format='json')
    resp5 = NukeDataView.as_view()(req5)
    print("Status:", resp5.status_code)
    assert resp5.status_code == 200
    print("Purge Status:", resp5.data.get("status"))
    print("Records Shredded:", resp5.data.get("records_shredded"))

    print("\n>>> ALL BACKEND API TESTS PASSED PERFECTLY! <<<")

if __name__ == "__main__":
    run_tests()

