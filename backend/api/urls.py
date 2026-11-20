from django.urls import path
from .views import (
    # Auth & Session (Phase 3)
    InitSessionView,
    RotateSessionView,
    SessionStatusView,
    # Personas
    PersonaListView,
    SelectPersonaView,
    # Privacy & Sanitization
    SanitizePreviewView,
    DocumentAnalyzeView,
    # Consent
    ConsentAuditView,
    ConsentWithdrawView,
    PrivacyAuditTrailView,
    # Data Parsing
    ParseStatementView,
    ParseSmsView,
    # Analytics
    SimulateEmiView,
    NukeDataView,
    # Phase 2: Financial Intelligence
    TransactionCategorizationView,
    MonthlyBudgetView,
    SubscriptionDetectorView,
    UnusualSpendingDetectorView,
    SpendingPatternAnalyzerView,
    # Task 17: Imported-session overview
    ImportedSessionOverviewView,
    EvidenceBriefingView,
    # Commitment Stress Test & Judgment Flip
    CommitmentStressTestView,
    CommitmentStressTestExplainView,
    TransactionCorrectionView,
)

urlpatterns = [
    # Auth & Session Identity
    path('auth/session/init/', InitSessionView.as_view(), name='auth-session-init'),
    path('auth/session/rotate/', RotateSessionView.as_view(), name='auth-session-rotate'),
    path('auth/session/me/', SessionStatusView.as_view(), name='auth-session-me'),
    # Personas
    path('personas/', PersonaListView.as_view(), name='persona-list'),
    path('personas/select/', SelectPersonaView.as_view(), name='select-persona'),
    # Privacy
    path('privacy/consent/', ConsentAuditView.as_view(), name='privacy-consent'),
    path('privacy/consent/withdraw/', ConsentWithdrawView.as_view(), name='consent-withdraw'),
    path('privacy/audit-trail/', PrivacyAuditTrailView.as_view(), name='privacy-audit-trail'),
    path('privacy/sanitize-preview/', SanitizePreviewView.as_view(), name='sanitize-preview'),
    path('privacy/nuke-data/', NukeDataView.as_view(), name='nuke-data'),
    # Documents / AI Analysis
    path('documents/analyze/', DocumentAnalyzeView.as_view(), name='document-analyze'),
    # Data Parsing
    path('data/parse-statement/', ParseStatementView.as_view(), name='parse-statement'),
    path('data/parse-sms/', ParseSmsView.as_view(), name='parse-sms'),
    # Analytics
    path('analytics/simulate-emi/', SimulateEmiView.as_view(), name='simulate-emi'),
    # Phase 2: Financial Intelligence
    path('insights/categorize/', TransactionCategorizationView.as_view(), name='tx-categorize'),
    path('insights/monthly-budget/', MonthlyBudgetView.as_view(), name='monthly-budget'),
    path('insights/subscriptions/', SubscriptionDetectorView.as_view(), name='subscriptions'),
    path('insights/unusual-spending/', UnusualSpendingDetectorView.as_view(), name='unusual-spending'),
    path('insights/spending-patterns/', SpendingPatternAnalyzerView.as_view(), name='spending-patterns'),
    # Task 17: Imported-session snapshot/overview
    path('insights/imported-overview/', ImportedSessionOverviewView.as_view(), name='imported-overview'),
    # Evidence-Based Financial Insights Briefing
    path('insights/evidence-briefing/', EvidenceBriefingView.as_view(), name='evidence-briefing'),
    # Commitment Stress Test & Judgment Flip
    path('analytics/commitment-stress-test/', CommitmentStressTestView.as_view(), name='commitment-stress-test'),
    path('analytics/commitment-stress-test/explain/', CommitmentStressTestExplainView.as_view(), name='commitment-stress-test-explain'),
    path('insights/correct-transaction/', TransactionCorrectionView.as_view(), name='correct-transaction'),
]
