export const UNIDENTIFIED_COUNTERPARTY = 'Unidentified Counterparty';
export const PERSONAL_TRANSFER = 'Personal Transfer';
// Fixed, content-free label for a confirmed own-account transfer. It names the
// movement without revealing any counterparty, so it must survive the display
// boundary unchanged.
export const INTERNAL_TRANSFER = 'Internal Transfer';
const INTERNAL_TRANSFER_RE = /^internal\s+transfer$/i;

// Internal markers emitted by the PII pipeline (e.g. [REDACTED_UPI_ID],
// [REDACTED_ACCOUNT], [USER_PRIMARY]). They identify a redaction, not a person,
// and must never be rendered as a counterparty name.
const INTERNAL_MARKER_RE = /\[(?:REDACTED_[A-Z_]+|USER_PRIMARY)\]/gi;

// Conservative identifier shapes. This is defense in depth: the server sanitizer
// remains the primary boundary, and nothing here reconstructs a redacted value.
const EMAIL_RE = /\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b/;
const VPA_RE = /\b[\w.-]{2,}@[A-Za-z]{2,}\b/;
const PHONE_RE = /(?:\+?91[\s.-]?)?\b[6-9]\d{4}[\s.-]?\d{5}\b/;
const AADHAAR_RE = /\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b/;
const PAN_RE = /\b[A-Z]{5}\d{4}[A-Z]\b/i;
const ACCOUNT_RE = /(?:A\/C|A\.C|Account|Acct|Acc\s*No)[\s.:#-]*[\dXx*]{4,}/i;

// Payment narration such as "Payment to Rahul" or "Transfer from ..." is never a
// merchant identity, even after the identifier itself has been removed.
const PERSONAL_NARRATION_RE =
  /^(?:payment|paid|pay|sent|transferred?)\b.*\b(?:to|from)\b/i;

// A label left with only a payment-rail word (e.g. "UPI" from "UPI/[REDACTED_UPI_ID]")
// carries no counterparty identity.
const RAIL_ONLY_RE =
  /^(?:upi|pos|neft|imps|ach|nach|rtgs|payment|pay|txn|transaction|debit|credit|dr|cr)$/i;

// Transaction reference suffixes (ORD-5555, REF-777, TXN1234). The value must start
// with a digit so ordinary words such as "Order Food" are never removed.
const REFERENCE_SUFFIX_RE = /\b(?:ord|ref|txn|utr|inv)[\s:#/-]?\d[A-Za-z0-9]{2,}\b/gi;

// Recognized commercial names that carry no generic business keyword. Mirrors the
// server-side demo lexicon; it is not a complete merchant allowlist.
const KNOWN_MERCHANT_RE = new RegExp(
  '\\b(?:' +
    [
      'chai point', 'blue tokai', 'third wave coffee', 'cafe coffee day', 'local kirana',
      'standard chartered', 'amazon', 'swiggy', 'instamart', 'zomato', 'blinkit',
      'flipkart', 'myntra', 'nykaa', 'croma', 'makemytrip', 'bookmyshow', 'netflix',
      'spotify', 'hotstar', 'youtube', 'chatgpt', 'openai', 'airtel', 'jio', 'bescom',
      'cult fit', 'cultfit', 'decathlon', 'uber', 'ola', 'tanishq', 'haldiram',
      'apple', 'macbook', 'samsung', 'oneplus', 'boat',
    ].join('|') +
    ')\\b',
  'i'
);

// Commerce vocabulary that reliably indicates a business rather than a person.
const COMMERCE_SIGNAL_RE = new RegExp(
  '\\b(?:' +
    [
      'store', 'stores', 'shop', 'shops', 'mart', 'market', 'electronics',
      'appliances', 'services?', 'solutions?', 'technolog(?:y|ies)', 'systems?',
      'labs?', 'pharmacy', 'diagnostics', 'hospital', 'clinic', 'hotels?',
      'restaurants?', 'cafe', 'coffee', 'kitchen', 'bakery', 'dairy', 'grocer(?:y|ies)',
      'supermart', 'supermarket', 'kirana', 'salon', 'spa', 'gym', 'fitness',
      'tuition', 'school', 'college', 'institute', 'academy', 'coaching', 'travels?',
      'airlines?', 'tours?', 'tickets?', 'bookings?', 'flights?', 'cinema', 'theatre',
      'theater', 'fuel', 'petrol', 'diesel', 'energy', 'subscriptions?',
      'memberships?', 'recharge', 'bills?', 'orders?', 'purchases?', 'boutique',
      'stationery', 'jewell?ers?', 'bank', 'insurance', 'finance', 'capital',
      'enterprises?', 'industries?', 'traders?', 'limited', 'ltd', 'pvt', 'private',
      'llp', 'inc', 'corp', 'company',
    ].join('|') +
    ')\\b',
  'i'
);

// Two to four plain alphabetic words with no brand, identifier, narration or commerce
// signal are ambiguous, not a confirmed personal transfer. Deliberately narrow: it is
// evaluated only after every stronger signal has been ruled out.
const AMBIGUOUS_NAME_RE = /^[A-Za-z][A-Za-z'-]*(?:\s+[A-Za-z][A-Za-z'-]*){1,3}$/;

/**
 * Returns a user-facing counterparty name for a value that may still carry an
 * internal redaction marker or a residual identifier. Falls back to a generic
 * label and never reconstructs the original value.
 */
export function safeCounterpartyName(value) {
  if (typeof value !== 'string') return UNIDENTIFIED_COUNTERPARTY;

  const cleaned = value
    .replace(INTERNAL_MARKER_RE, ' ')
    .replace(/\s+/g, ' ')
    .trim();

  if (!cleaned) return UNIDENTIFIED_COUNTERPARTY;

  // Remove reference codes even from recognized brands: a known merchant must not
  // carry an order, refund or transaction reference into the UI.
  const withoutRefs = cleaned.replace(REFERENCE_SUFFIX_RE, ' ').replace(/\s+/g, ' ').trim();
  if (!withoutRefs) return UNIDENTIFIED_COUNTERPARTY;
  const text = withoutRefs;

  if (EMAIL_RE.test(text) || VPA_RE.test(text)) return UNIDENTIFIED_COUNTERPARTY;
  if (PHONE_RE.test(text)) return UNIDENTIFIED_COUNTERPARTY;
  if (PAN_RE.test(text) || AADHAAR_RE.test(text) || ACCOUNT_RE.test(text)) {
    return UNIDENTIFIED_COUNTERPARTY;
  }
  if (PERSONAL_NARRATION_RE.test(text)) return PERSONAL_TRANSFER;

  // A confirmed own-account transfer keeps its own label.
  if (INTERNAL_TRANSFER_RE.test(text)) return INTERNAL_TRANSFER;

  const railOnly = text.replace(/[^A-Za-z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim();
  if (!railOnly || RAIL_ONLY_RE.test(railOnly)) return UNIDENTIFIED_COUNTERPARTY;
  if ((text.match(/[A-Za-z]/g) || []).length < 2) return UNIDENTIFIED_COUNTERPARTY;

  // An explicitly unknown counterparty stays unidentified regardless of vocabulary.
  if (/\b(?:unknown|unrecognised|unrecognized|unnamed)\b/i.test(text)) {
    return UNIDENTIFIED_COUNTERPARTY;
  }

  // Recognized merchants and commerce vocabulary stay readable.
  if (KNOWN_MERCHANT_RE.test(text) || COMMERCE_SIGNAL_RE.test(text)) return text;

  // Strip payment-rail words before judging a remaining name shape.
  const nameShape = railOnly
    .replace(/\b(?:upi|neft|imps|rtgs|ach|nach|refund|refunded|payment|paid|txn|debit|credit)\b/gi, ' ')
    .replace(/\s+/g, ' ')
    .trim();

  // A bare person-shaped name proves neither identity; never echo it as a merchant.
  if (AMBIGUOUS_NAME_RE.test(nameShape)) return UNIDENTIFIED_COUNTERPARTY;
  if (/^[A-Za-z][A-Za-z'-]*$/.test(nameShape)) return UNIDENTIFIED_COUNTERPARTY;

  return text;
}
