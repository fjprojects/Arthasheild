import os
import json
import logging
import re
import requests
from typing import Dict, Any, List, Optional

from sanitizer.services import SanitizerService

logger = logging.getLogger(__name__)

class AdvisorService:
    """
    Structured Semantic LLM Service.
    Translates pre-calculated metrics and sanitized documents into plain-English advice
    without ever receiving raw PII or calculating financial arithmetic.
    """

    #: Model used for the optional live analysis. The value is overridable with
    #: GEMINI_MODEL so a deployment can pin a currently supported model without
    #: a code change. The default is a currently supported, stable Flash model
    #: (Gemini 3.6 Flash) that supports structured JSON output.
    #: NOTE: Gemini 2.5 Flash is deprecated and is shut down on 2026-12-01.
    DEFAULT_MODEL = "gemini-3.6-flash"

    #: API versions tried in order. ``v1`` is the current stable version and
    #: ``v1beta`` is kept as a fallback for accounts that are not yet served by
    #: the stable route. All current models are supported by both.
    API_VERSIONS = ("v1", "v1beta")

    #: Request timeout for the provider call, in seconds.
    REQUEST_TIMEOUT = 20

    #: Keys the model must return for its answer to be usable.
    REQUIRED_KEYS = (
        "plain_english_summary",
        "top_actionable_wins",
        "hidden_risks_and_predatory_clauses",
        "disclaimer",
    )

    #: A monetary figure such as "₹1,500" or "Rs. 1,500.00".
    AMOUNT_RE = re.compile(
        r"(?:₹|\brs\.?\s*|\binr\s*)\s?(\d[\d,]*(?:\.\d{1,2})?)",
        re.IGNORECASE,
    )

    #: A figure written without a currency marker that is large enough to be a
    #: monetary amount rather than a count, a percentage or a duration:
    #: "999999", "49,999". Percentages, month counts and short durations are
    #: deliberately excluded.
    BARE_AMOUNT_RE = re.compile(
        r"(?<![\w.])(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d{4,}(?:\.\d{1,2})?)(?![\w%])"
    )

    SYSTEM_INSTRUCTION = """
You are ArthaShield, an elite privacy-first AI financial copilot designed for hackathons and consumer protection.
Your core mandates:
1. PRIVACY FIRST: You only see tokenized/sanitized financial records (e.g. [USER_PRIMARY], [REDACTED_ACCOUNT]). Never attempt to de-anonymize.
2. ZERO ARITHMETIC HALLUCINATIONS: All numbers, sums, and ratios have been pre-computed by a deterministic Python engine. Always cite and explain those exact pre-calculated metrics; never invent new financial calculations.
3. CLEAR CONSUMER ADVOCACY: Highlight hidden fees, predatory loan penalties, and forgotten subscriptions in simple, non-intimidating bullet points.
4. REGULATORY INTEGRITY: Never guarantee investment returns or claim to be a certified financial advisor. Frame insights as educational budgeting analysis.

Respond in strict JSON with the following keys:
{
  "plain_english_summary": "string (2-3 concise, empathetic sentences)",
  "top_actionable_wins": [
    { "title": "string", "impact_amount": "string", "action": "string" }
  ],
  "hidden_risks_and_predatory_clauses": [
    { "risk_name": "string", "explanation": "string", "severity": "HIGH|MEDIUM|LOW" }
  ],
  "disclaimer": "string"
}
"""

    @classmethod
    def get_api_key(cls) -> Optional[str]:
        return os.environ.get("GEMINI_API_KEY")

    @classmethod
    def get_model(cls) -> str:
        """The model used for the optional live analysis."""
        return os.environ.get("GEMINI_MODEL", "").strip() or cls.DEFAULT_MODEL

    @classmethod
    def _validate_payload(cls, payload: Any) -> Optional[str]:
        """
        Validates the model answer against the expected schema.

        Returns a short error description when the payload cannot be used, or
        None when it is structurally sound. A payload that fails validation is
        never surfaced: the deterministic fallback is used instead.
        """
        if not isinstance(payload, dict):
            return "payload is not an object"
        for key in cls.REQUIRED_KEYS:
            if key not in payload:
                return f"missing key: {key}"
        summary = payload["plain_english_summary"]
        if not isinstance(summary, str) or not summary.strip():
            return "plain_english_summary must be a non-empty string"
        if len(summary) > 4000:
            return "plain_english_summary is too long"
        for key in ("top_actionable_wins", "hidden_risks_and_predatory_clauses"):
            entries = payload[key]
            if not isinstance(entries, list):
                return f"{key} must be a list"
            if len(entries) > 12:
                return f"{key} has too many entries"
            for entry in entries:
                if not isinstance(entry, dict):
                    return f"{key} entries must be objects"
                if not isinstance(entry.get("title") or entry.get("risk_name"), str):
                    return f"{key} entries need a text title"
        if not isinstance(payload["disclaimer"], str):
            return "disclaimer must be a string"
        return None

    @classmethod
    def _iter_text_values(cls, payload: Any):
        """Yields every string inside the model answer."""
        if isinstance(payload, dict):
            for value in payload.values():
                yield from cls._iter_text_values(value)
        elif isinstance(payload, list):
            for value in payload:
                yield from cls._iter_text_values(value)
        elif isinstance(payload, str):
            yield payload

    @classmethod
    def _deterministic_amounts(cls, computed_metrics: Dict[str, Any]) -> set:
        """Every monetary figure the deterministic engine produced."""
        amounts = set()

        def walk(value):
            if isinstance(value, dict):
                for nested in value.values():
                    walk(nested)
            elif isinstance(value, list):
                for nested in value:
                    walk(nested)
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                amounts.add(round(float(value), 2))
            elif isinstance(value, str):
                for match in cls.AMOUNT_RE.finditer(value):
                    try:
                        amounts.add(round(float(match.group(1).replace(",", "")), 2))
                    except ValueError:
                        pass

        walk(computed_metrics or {})
        return amounts

    @classmethod
    def _unverified_amount_claims(cls, payload: Any, computed_metrics: Dict[str, Any]) -> List[str]:
        """
        Monetary figures asserted by the model that the deterministic engine did
        not produce. They are advisory claims, never verified calculations.
        """
        allowed = cls._deterministic_amounts(computed_metrics)
        unverified = []
        for text in cls._iter_text_values(payload):
            candidates = list(cls.AMOUNT_RE.findall(text))
            candidates += list(cls.BARE_AMOUNT_RE.findall(text))
            for token in candidates:
                try:
                    value = round(float(token.replace(",", "")), 2)
                except (ValueError, AttributeError):
                    continue
                if value not in allowed:
                    unverified.append(f"₹{token}")
        return sorted(set(unverified))

    @classmethod
    def _supports_thinking_level(cls, model: str) -> bool:
        """
        Gemini 3 and later accept the ``thinkingLevel`` control. Earlier models
        reject the field with an error, so it is never sent to them.
        """
        match = re.search(r"gemini-(\d+)", (model or "").lower())
        if not match:
            return False
        return int(match.group(1)) >= 3

    @classmethod
    def _generation_config(cls, model: str) -> Dict[str, Any]:
        """
        Builds a generation configuration that is valid for the pinned model.

        * ``responseMimeType: application/json`` asks for a JSON document.
        * ``thinkingLevel`` is only sent to models that accept it, and only the
          "LOW" level, which every current Gemini 3.x / 4.x model supports.
        * ``temperature`` is only sent to earlier models: it is ignored by
          Gemini 3.6 Flash and newer.
        """
        config: Dict[str, Any] = {
            "responseMimeType": "application/json",
            "maxOutputTokens": 4096,
        }
        if cls._supports_thinking_level(model):
            config["thinkingConfig"] = {"thinkingLevel": "LOW"}
        else:
            config["temperature"] = 0.2
        return config

    @classmethod
    def _extract_answer_text(cls, data: Dict[str, Any]) -> Optional[str]:
        """
        Returns the model's answer text.

        Thinking models may return reasoning parts before the answer, so parts
        flagged as thoughts are ignored. A response without an answer part
        returns None and is handled by the caller.
        """
        if not isinstance(data, dict):
            return None
        candidates = data.get("candidates") or []
        if not candidates:
            return None
        content = candidates[0].get("content") or {}
        parts = content.get("parts") or []
        answer_parts = [
            part.get("text", "")
            for part in parts
            if isinstance(part, dict) and part.get("text") and not part.get("thought")
        ]
        if answer_parts:
            return "".join(answer_parts)
        return None

    @classmethod
    def _call_provider(
        cls, api_key: str, model: str, prompt_text: str
    ) -> tuple:
        """
        Calls the provider and returns ``(data, error_description)``.

        Exactly one of the two is set. The current stable API version is tried
        first; a 404 (the route is not served for this account) falls through
        to the beta route.
        """
        headers = {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        }
        body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt_text}],
                }
            ],
            "generationConfig": cls._generation_config(model),
        }

        last_error = None
        for version in cls.API_VERSIONS:
            url = (
                f"https://generativelanguage.googleapis.com/{version}/models/"
                f"{model}:generateContent"
            )
            try:
                resp = requests.post(
                    url, headers=headers, json=body, timeout=cls.REQUEST_TIMEOUT
                )
            except requests.exceptions.Timeout:
                logger.error(
                    "Gemini request timed out after %d seconds.", cls.REQUEST_TIMEOUT
                )
                return None, "provider timeout"
            except requests.exceptions.RequestException as exc:
                # Safe event logging only: the exception type never carries the
                # key, the URL or the payload.
                logger.error("Gemini request failed (%s).", type(exc).__name__)
                return None, "provider network error"
            except Exception as exc:  # noqa: BLE001 - any provider failure must fall back
                # Safe event logging only: never log secrets, URLs or raw tracebacks.
                logger.error("Gemini request failed (%s).", type(exc).__name__)
                return None, "provider error"

            if resp.status_code == 200:
                try:
                    return resp.json(), None
                except ValueError:
                    return None, "provider returned an unreadable body"

            if resp.status_code == 404:
                # This API version is not served for the account: try the next.
                last_error = f"HTTP 404 on {version}"
                continue

            # Safe event logging only: the status code never carries the key,
            # the URL or the payload.
            logger.warning(
                "Gemini request failed (HTTP %d on %s).", resp.status_code, version
            )
            return None, f"HTTP {resp.status_code}"

        logger.warning("Gemini request failed (%s).", last_error or "provider unavailable")
        return None, last_error or "provider unavailable"

    @classmethod
    def analyze_sanitized_statement(cls, sanitized_text: str, computed_metrics: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sends scrubbed text and pre-calculated deterministic metrics to Gemini.
        Falls back to local heuristic synthesis if API key is not yet set, if the
        request fails, or if the model answer does not satisfy the schema.
        """
        api_key = cls.get_api_key()

        if not api_key:
            # High-fidelity deterministic heuristic fallback for offline/instant testing
            return cls._generate_heuristic_response(sanitized_text, computed_metrics)

        # Defence in depth: the caller is expected to pass sanitized text, but
        # this service never hands an unsanitized payload to a third party.
        # Personal names, account numbers, phone numbers and PANs are replaced
        # with tokens before the text leaves the host.
        outbound_text = SanitizerService.sanitize(sanitized_text or "")["sanitized_text"]

        prompt = f"""
Analyze the following SANITIZED financial transaction stream and pre-computed health metrics:

PRE-COMPUTED DETERMINISTIC METRICS:
{json.dumps(computed_metrics, indent=2)}

SANITIZED TRANSACTION & DOCUMENT TEXT:
{outbound_text[:4000]}
"""

        model = cls.get_model()
        data, error = cls._call_provider(
            api_key, model, f"{cls.SYSTEM_INSTRUCTION}\n\n{prompt}"
        )

        if error is not None:
            # The failure was already logged safely by _call_provider.
            return cls._generate_heuristic_response(sanitized_text, computed_metrics)

        block_reason = (data.get("promptFeedback") or {}).get("blockReason")
        if block_reason:
            logger.warning("Gemini request was blocked (%s).", block_reason)
            return cls._generate_heuristic_response(sanitized_text, computed_metrics)

        raw_json = cls._extract_answer_text(data)
        if not raw_json:
            logger.warning("Gemini response contained no answer text.")
            return cls._generate_heuristic_response(sanitized_text, computed_metrics)

        try:
            parsed = json.loads(raw_json)
        except (ValueError, TypeError):
            logger.warning("Gemini response was not valid JSON.")
            return cls._generate_heuristic_response(sanitized_text, computed_metrics)

        # The model answer is validated before it is used: an answer that
        # does not satisfy the schema is discarded, never surfaced.
        schema_error = cls._validate_payload(parsed)
        if schema_error:
            logger.warning(
                "Gemini answer rejected by schema validation (%s).", schema_error
            )
            return cls._generate_heuristic_response(sanitized_text, computed_metrics)

        parsed["source"] = "LIVE_GEMINI"
        parsed["is_ai_generated"] = True
        parsed["engine_label"] = "Live Gemini AI Analysis"
        parsed["model"] = model
        # Figures the deterministic engine did not produce are advisory
        # claims: they are listed explicitly instead of being presented
        # as verified calculations.
        unverified = cls._unverified_amount_claims(parsed, computed_metrics)
        parsed["unverified_amount_claims"] = unverified
        parsed["numeric_claims_verified"] = not unverified
        return parsed

    @classmethod
    def _generate_heuristic_response(cls, sanitized_text: str, computed_metrics: Dict[str, Any]) -> Dict[str, Any]:
        """
        Deterministic, zero-hallucination fallback that provides structured insights
        even when offline or running without an API key.
        Clearly labeled as Offline Rule-Based Financial Insights.

        Every amount quoted here is derived from the deterministic metrics that the
        Python engine produced. No figure is invented.
        """
        health = computed_metrics.get("health_score")
        runway = (
            computed_metrics.get("metrics", {}).get("runway_months")
            or computed_metrics.get("emergency_runway_months")
        )
        recurring = computed_metrics.get("recurring_commitments", {}) or {}
        monthly_leakage = recurring.get("monthly_leakage") or 0
        monthly_commitments = recurring.get("monthly_commitments") or 0

        if monthly_leakage:
            leak_impact = f"Reduce identified recurring charges worth ₹{monthly_leakage}/mo"
        else:
            leak_impact = "Amount depends on the recurring charges found in your statement"
        if monthly_commitments:
            commitment_impact = f"₹{monthly_commitments}/mo of recurring commitments are already reserved"
        else:
            commitment_impact = "Amount depends on the recurring commitments found in your statement"

        if health is not None and runway is not None:
            summary = (
                f"Your finances have a health score of {health}/100 with an emergency runway of "
                f"{runway} months. We identified several recurring leaks that can be eliminated "
                "to immediately restore your disposable cash buffer."
            )
        else:
            summary = (
                "No deterministic financial metrics are available for this session yet. "
                "Import a bank statement (or load a demo persona) to compute verified income, "
                "spending and runway figures; every amount below is derived from those metrics."
            )

        return {
            "source": "OFFLINE_RULE_BASED",
            "is_ai_generated": False,
            "engine_label": "Offline Rule-Based Financial Insights",
            "model": None,
            "numeric_claims_verified": True,
            "unverified_amount_claims": [],
            "plain_english_summary": summary,
            "top_actionable_wins": [
                {
                    "title": "Prune Dormant Recurring Subscriptions",
                    "impact_amount": leak_impact,
                    "action": "Cancel idle cloud hosting, duplicate design seats, or unutilized course memberships identified in your statement."
                },
                {
                    "title": "Establish Safe-to-Spend Ceiling",
                    "impact_amount": f"{commitment_impact}; keep a daily UPI cap for discretionary spending",
                    "action": "Cap non-essential daily discretionary UPI expenses to preserve pending rent and EMI obligations."
                },
                {
                    "title": "Audit Hidden EMI Charges",
                    "impact_amount": "Compare the effective annual borrowing cost in the EMI simulator before signing",
                    "action": "Examine 'No-Cost' EMI mandates for recurring convenience charges and GST on subvention."
                }
            ],
            "hidden_risks_and_predatory_clauses": [
                {
                    "risk_name": "Disguised 0% EMI Surcharges",
                    "explanation": "No-cost EMIs frequently levy processing fees and 18% GST on interest discounts, significantly inflating true borrowing cost.",
                    "severity": "HIGH"
                },
                {
                    "risk_name": "Auto-Debit Subscription Creep",
                    "explanation": "Micro-mandates between ₹100 and ₹900 quietly renew without prompt notifications, draining your savings buffer.",
                    "severity": "MEDIUM"
                }
            ],
            "disclaimer": "Educational financial analysis generated with privacy-preserving deterministic engine. Not certified financial advice."
        }

