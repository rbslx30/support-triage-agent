"""
STIS — Support Triage Intelligence System
Core reasoning engine: intent decomposition, risk scoring, RAG, routing.
"""

import os, sys, json, re, math, time, hashlib, textwrap
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional
import requests

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE     = Path(__file__).parent.parent
CORPUS   = BASE / "data" / "corpus"
LOG_FILE = BASE / "logs" / "log.txt"
OUT_FILE = BASE / "output" / "output.csv"

for d in [BASE/"logs", BASE/"output"]:
    d.mkdir(parents=True, exist_ok=True)

# ── API ────────────────────────────────────────────────────────────────────────
API_URL = "https://api.anthropic.com/v1/messages"
MODEL   = "claude-sonnet-4-20250514"

DOMAIN_URLS = {
    "hackerrank": "https://support.hackerrank.com/",
    "claude":     "https://support.claude.com/en/",
    "visa":       "https://www.visa.co.in/support.html",
}

# ── Risk taxonomy ──────────────────────────────────────────────────────────────
RISK_KEYWORDS = {
    "CRITICAL": [
        "fraud", "stolen", "unauthorized charge", "stolen card",
        "phishing", "identity theft", "account takeover", "wire transfer",
        "malware", "keylogger", "bypass", "override", "inject", "exploit",
        "prompt injection", "jailbreak", "internal data", "system prompt",
    ],
    "HIGH": [
        "billing", "refund", "dispute", "charge", "payment", "chargeback",
        "account access", "password", "login", "gdpr", "delete my data",
        "legal", "lawsuit", "privacy", "data deletion", "permission",
        "proctoring", "flagged", "appeal", "ban", "suspend",
    ],
    "MEDIUM": [
        "bug", "error", "not working", "broken", "crash", "timeout",
        "rate limit", "api", "integration", "assessment", "test",
    ],
    "LOW": [
        "how to", "what is", "guide", "documentation", "feature",
        "pricing", "plan", "upgrade", "create", "setup",
    ],
}

MALICIOUS_PATTERNS = [
    r"(ignore|forget|disregard).{0,30}(previous|above|instruction|prompt|system)",
    r"(you are now|act as|pretend|roleplay).{0,30}(different|another|new|unrestricted)",
    r"(reveal|show|print|output).{0,30}(system prompt|internal|hidden|secret)",
    r"(bypass|override|disable).{0,30}(safety|filter|restriction|policy|rule)",
    r"(keylogger|ransomware|virus|trojan|rootkit|spyware|malware|exploit|payload)",
    r"(sql inject|xss|cross.site|remote code|rce|lfi|rfi)",
    r"do anything now|dan prompt|jailbreak",
]

ESCALATE_AREAS = {
    "fraud", "billing", "disputes", "account", "privacy", "safety",
    "proctoring_appeal", "security", "data_deletion", "access_control",
}


# ── Data models ────────────────────────────────────────────────────────────────
@dataclass
class IntentLayer:
    primary: str = ""
    secondary: list[str] = field(default_factory=list)
    hidden_flags: list[str] = field(default_factory=list)
    noise_removed: str = ""

@dataclass
class RiskProfile:
    level: str = "LOW"           # LOW / MEDIUM / HIGH / CRITICAL
    score: float = 0.0           # 0–100
    triggers: list[str] = field(default_factory=list)
    malicious: bool = False
    injection_detected: bool = False

@dataclass
class GroundingResult:
    snippets: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    coverage_score: float = 0.0  # 0–1: how well corpus covers the issue
    domain_confirmed: str = ""

@dataclass
class TriageDecision:
    status: str = "escalated"           # replied | escalated
    product_area: str = "general"
    request_type: str = "product_issue"
    response: str = ""
    justification: str = ""
    # enrichment
    intent: IntentLayer = field(default_factory=IntentLayer)
    risk: RiskProfile = field(default_factory=RiskProfile)
    grounding: GroundingResult = field(default_factory=GroundingResult)
    domain: str = "unknown"
    confidence: float = 0.0
    processing_ms: int = 0


# ── Corpus loader ──────────────────────────────────────────────────────────────
_CORPUS_CACHE: dict[str, list[tuple[str, str]]] = {}   # domain → [(source, text)]

def load_corpus() -> dict[str, list[tuple[str, str]]]:
    global _CORPUS_CACHE
    if _CORPUS_CACHE:
        return _CORPUS_CACHE
    for domain_dir in CORPUS.iterdir():
        if not domain_dir.is_dir():
            continue
        domain = domain_dir.name.lower()
        docs = []
        for f in domain_dir.rglob("*"):
            if f.suffix in {".txt", ".md"} and f.stat().st_size > 100:
                try:
                    docs.append((str(f), f.read_text(encoding="utf-8", errors="ignore")))
                except Exception:
                    pass
        _CORPUS_CACHE[domain] = docs
    return _CORPUS_CACHE


def _tfidf_score(query_tokens: set[str], doc: str) -> float:
    """Lightweight TF-IDF-inspired scoring."""
    doc_lower = doc.lower()
    doc_tokens = re.findall(r'\b\w{3,}\b', doc_lower)
    doc_len = max(len(doc_tokens), 1)
    score = 0.0
    for tok in query_tokens:
        tf = doc_lower.count(tok) / doc_len
        idf = 1.0  # simplified; corpus too small for real IDF
        score += tf * idf
    return score


def retrieve(issue: str, domain: str, top_k: int = 5) -> GroundingResult:
    corpus = load_corpus()
    tokens = set(re.findall(r'\b\w{4,}\b', issue.lower()))
    
    # gather candidates from domain + fallback to all
    candidates: list[tuple[str, str]] = corpus.get(domain, [])
    if not candidates:
        for docs in corpus.values():
            candidates.extend(docs)

    scored: list[tuple[float, str, str]] = []
    for src, text in candidates:
        s = _tfidf_score(tokens, text)
        if s > 0:
            scored.append((s, src, text))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_k]

    snippets = [t[2000:4000] if len(t) > 2000 else t for _, _, t in top]  # mid-doc slice
    sources  = [s for _, s, _ in top]
    cov = min(1.0, sum(s for s, _, _ in top) * 10) if top else 0.0

    return GroundingResult(
        snippets=snippets[:3],
        sources=sources[:3],
        coverage_score=round(cov, 3),
        domain_confirmed=domain if candidates else "unknown",
    )


# ── Risk scorer ────────────────────────────────────────────────────────────────
def score_risk(issue: str, subject: str) -> RiskProfile:
    text = (issue + " " + subject).lower()
    level = "LOW"
    score = 0.0
    triggers = []
    malicious = False
    injection = False

    # Injection / malicious pattern check
    for pat in MALICIOUS_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            malicious = True
            injection = True
            triggers.append("INJECTION_PATTERN")
            score = 100.0
            level = "CRITICAL"
            break

    if not malicious:
        for lvl, kws in RISK_KEYWORDS.items():
            for kw in kws:
                if kw in text:
                    triggers.append(kw)
                    bump = {"CRITICAL": 35, "HIGH": 20, "MEDIUM": 10, "LOW": 3}[lvl]
                    score = min(100, score + bump)
                    if {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}[lvl] > \
                       {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}[level]:
                        level = lvl

    return RiskProfile(
        level=level,
        score=round(score, 1),
        triggers=list(set(triggers))[:8],
        malicious=malicious,
        injection_detected=injection,
    )


# ── Domain resolver ────────────────────────────────────────────────────────────
DOMAIN_SIGNALS = {
    "hackerrank": ["hackerrank", "assessment", "coding test", "interview", "hiring", "proctoring", "candidate", "recruiter"],
    "claude":     ["claude", "anthropic", "ai assistant", "api key", "usage limit", "conversation", "message"],
    "visa":       ["visa", "card", "transaction", "payment", "atm", "bank", "charge", "merchant"],
}

def resolve_domain(company: str, issue: str) -> str:
    company_lower = company.lower().strip()
    for domain in DOMAIN_URLS:
        if domain in company_lower:
            return domain
    # signal match
    text = (company + " " + issue).lower()
    best, best_score = "unknown", 0
    for domain, signals in DOMAIN_SIGNALS.items():
        s = sum(1 for sig in signals if sig in text)
        if s > best_score:
            best, best_score = domain, s
    return best if best_score > 0 else "unknown"


# ── Claude API ─────────────────────────────────────────────────────────────────
def _call_api(system: str, user: str, max_tokens: int = 800) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        return ""
    headers = {
        "Content-Type": "application/json",
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
    }
    payload = {"model": MODEL, "max_tokens": max_tokens, "system": system,
               "messages": [{"role": "user", "content": user}]}
    for attempt in range(3):
        try:
            r = requests.post(API_URL, headers=headers, json=payload, timeout=60)
            r.raise_for_status()
            return r.json()["content"][0]["text"].strip()
        except requests.HTTPError as e:
            time.sleep(2 ** attempt)
        except Exception:
            break
    return ""


# ── Intent decomposition ───────────────────────────────────────────────────────
INTENT_SYSTEM = """You are a support ticket intent analyst. Extract the layered intent from the ticket.
Return ONLY valid JSON, no markdown, no extra text:
{
  "primary": "one concise sentence – the core user need",
  "secondary": ["any secondary requests or goals"],
  "hidden_flags": ["manipulation attempt | account_access | policy_override | emotional_distress | urgency_pressure | none"],
  "noise_removed": "clean version of the issue without emotional language"
}"""

def decompose_intent(issue: str, subject: str) -> IntentLayer:
    raw = _call_api(INTENT_SYSTEM, f"Subject: {subject}\n\nIssue:\n{issue}", max_tokens=400)
    try:
        clean = raw.replace("```json","").replace("```","").strip()
        d = json.loads(clean)
        return IntentLayer(**{k: d.get(k, v) for k, v in IntentLayer().__dict__.items()})
    except Exception:
        return IntentLayer(
            primary=issue[:120],
            secondary=[],
            hidden_flags=[],
            noise_removed=re.sub(r'[!?]{2,}|[A-Z]{5,}', '', issue).strip()
        )


# ── Response generator ─────────────────────────────────────────────────────────
RESPONSE_SYSTEM = """You are a professional support specialist. Generate a response strictly grounded in the provided documentation.

Rules:
- Use ONLY information from the documentation snippets below
- If documentation doesn't cover the issue, say so and direct to support URL
- Never invent policies, features, or guarantees
- Tone: calm, professional, concise (max 180 words)
- Do NOT mention AI, models, or internal system logic
- Do NOT start with "I" or "Certainly" or "Of course"

Documentation:
{docs}

Support URL: {url}"""

ESCALATION_SYSTEM = """You are a support routing specialist. Write a brief, professional escalation acknowledgment.
- Confirm receipt
- Explain it needs specialist review (without revealing system logic)
- Give realistic next-step expectation
- Max 80 words. Calm, professional tone."""

def generate_response(intent: IntentLayer, risk: RiskProfile, grounding: GroundingResult,
                      domain: str, area: str) -> str:
    url = DOMAIN_URLS.get(domain, "https://support.hackerrank.com/")
    docs = "\n\n---\n\n".join(grounding.snippets) if grounding.snippets else "(No corpus match found)"
    system = RESPONSE_SYSTEM.format(docs=docs[:3000], url=url)
    user = f"Product area: {area}\nUser need: {intent.primary}\nClean issue: {intent.noise_removed}"
    return _call_api(system, user, max_tokens=350)

def generate_escalation(intent: IntentLayer, reason: str, domain: str) -> str:
    url = DOMAIN_URLS.get(domain, "https://support.hackerrank.com/")
    user = f"User need: {intent.primary}\nReason for escalation: {reason}\nSupport URL: {url}"
    r = _call_api(ESCALATION_SYSTEM, user, max_tokens=200)
    if r:
        return r
    return (f"Thank you for reaching out. Your request requires review by a specialist "
            f"and has been prioritised accordingly. Our team will follow up shortly. "
            f"For urgent matters, please visit {url}.")


# ── Routing logic ──────────────────────────────────────────────────────────────
AREA_MAP = {
    # HackerRank
    "assessment": "assessments", "coding test": "assessments", "interview": "interviews",
    "proctoring": "proctoring", "recruiter": "hiring", "candidate": "hiring",
    # Claude
    "api": "api", "rate limit": "api", "usage": "usage", "conversation": "platform",
    "gdpr": "privacy", "delete": "privacy", "data": "privacy",
    # Visa
    "card": "cards", "transaction": "payments", "fraud": "fraud",
    "dispute": "disputes", "charge": "payments", "merchant": "payments",
    # Shared
    "billing": "billing", "refund": "billing", "account": "account",
    "login": "account", "password": "account",
}

def detect_area(issue: str, domain: str) -> str:
    text = issue.lower()
    for kw, area in AREA_MAP.items():
        if kw in text:
            return area
    return "general"

def detect_request_type(issue: str, risk: RiskProfile) -> str:
    text = issue.lower()
    if risk.malicious or risk.injection_detected:
        return "invalid"
    if any(w in text for w in ["feature", "would be nice", "suggestion", "add", "support for"]):
        return "feature_request"
    if any(w in text for w in ["bug", "broken", "crash", "error", "not working", "wrong"]):
        return "bug"
    return "product_issue"

def routing_decision(risk: RiskProfile, grounding: GroundingResult, area: str,
                     domain: str) -> tuple[bool, str]:
    """Returns (should_escalate, reason)."""
    if risk.malicious or risk.injection_detected:
        return True, "Malicious or injection pattern detected"
    if risk.level == "CRITICAL":
        return True, f"Critical risk triggers: {', '.join(risk.triggers[:3])}"
    if area in ESCALATE_AREAS:
        return True, f"Sensitive area requires human review: {area}"
    if domain == "unknown":
        return True, "Domain could not be confirmed"
    if risk.level == "HIGH" and grounding.coverage_score < 0.3:
        return True, "High-risk issue with insufficient documentation coverage"
    if grounding.coverage_score == 0 and risk.level in {"HIGH", "CRITICAL"}:
        return True, "No corpus coverage for high-risk request"
    return False, ""


# ── Master pipeline ────────────────────────────────────────────────────────────
def process(ticket_id: str, issue: str, subject: str, company: str) -> TriageDecision:
    t0 = time.time()
    dec = TriageDecision()

    # 0. Domain resolution
    dec.domain = resolve_domain(company, issue)

    # 1. Risk scoring (fast, no API needed)
    dec.risk = score_risk(issue, subject)

    # 2. Intent decomposition (API)
    dec.intent = decompose_intent(issue, subject)

    # 3. Corpus retrieval
    dec.grounding = retrieve(dec.intent.noise_removed or issue, dec.domain)

    # 4. Area + type detection
    dec.product_area = detect_area(issue, dec.domain)
    dec.request_type = detect_request_type(issue, dec.risk)

    # 5. Routing
    escalate, reason = routing_decision(dec.risk, dec.grounding, dec.product_area, dec.domain)

    # 6. Response generation
    if escalate:
        dec.status = "escalated"
        dec.response = generate_escalation(dec.intent, reason, dec.domain)
        dec.justification = reason
    else:
        response = generate_response(dec.intent, dec.risk, dec.grounding, dec.domain, dec.product_area)
        if response:
            dec.status = "replied"
            dec.response = response
            dec.justification = (f"Risk: {dec.risk.level} | Coverage: {dec.grounding.coverage_score:.2f} "
                                  f"| Area: {dec.product_area}")
        else:
            dec.status = "escalated"
            dec.response = generate_escalation(dec.intent, "Unable to generate grounded response", dec.domain)
            dec.justification = "API unavailable or insufficient grounding"

    # 7. Confidence
    cov = dec.grounding.coverage_score
    risk_penalty = {"LOW": 0, "MEDIUM": 0.1, "HIGH": 0.25, "CRITICAL": 0.5}[dec.risk.level]
    dec.confidence = round(max(0, min(1, cov - risk_penalty + (0.3 if dec.domain != "unknown" else 0))), 3)

    dec.processing_ms = int((time.time() - t0) * 1000)
    _log(ticket_id, dec)
    return dec


# ── Logging ────────────────────────────────────────────────────────────────────
def _log(tid: str, dec: TriageDecision):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ticket_id": tid,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "domain": dec.domain,
        "status": dec.status,
        "product_area": dec.product_area,
        "request_type": dec.request_type,
        "risk_level": dec.risk.level,
        "risk_score": dec.risk.score,
        "malicious": dec.risk.malicious,
        "coverage": dec.grounding.coverage_score,
        "confidence": dec.confidence,
        "processing_ms": dec.processing_ms,
        "primary_intent": dec.intent.primary,
        "justification": dec.justification,
        "response_preview": dec.response[:120],
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
