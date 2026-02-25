"""
Service layer for Draft Generation.

Provides two generation paths:

1. generate_draft() — Legacy fact-grounded path (EPIC 3).
   Requires an existing FactSheet; builds a structured prompt from its data.

2. generate_draft_from_prompt() — Prompt-first path (new architecture).
   User prompt is the primary driver. A document may be supplied as optional
   supporting context but is never required. No FactSheet or claim_registry
   dependency; never returns 503 due to missing structured data.

Settings are fetched dynamically from system_settings via settings_service so
they can be updated from the Admin UI without a redeploy.
"""

import json
import logging
import os
import time
from typing import Optional

import anthropic
import openai
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.models import AuditLog, Document, DocumentStatus, DraftVersion, FactSheet
from app.services import settings_service, llm_adapter
from app.services.exceptions import NoFactSheetError, NotFoundError, RateLimitError
from app.services.settings_service import ActiveSettings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM Prompt Builder
# ---------------------------------------------------------------------------

def _build_prompt(structured_data: dict, tone: str, max_draft_length: int = 50_000) -> str:
    """
    Build a structured, fact-grounded prompt for the LLM.

    The prompt explicitly instructs the model to:
    - Use only facts present in the FactSheet
    - Avoid superlatives without data backing
    - Produce output in the required seven-section structure

    Args:
        structured_data:  Parsed FactSheet JSON from the DB.
        tone:             One of "formal", "conversational", "technical".
        max_draft_length: Maximum character count for the draft (from DB settings).

    Returns:
        Complete prompt string ready to send to the LLM.
    """
    tone_instruction = {
        "formal": (
            "Use formal, professional language appropriate for enterprise whitepapers. "
            "Maintain an authoritative, objective tone throughout."
        ),
        "conversational": (
            "Use clear, accessible language that is engaging and easy to understand. "
            "Avoid heavy jargon; explain technical terms when used."
        ),
        "technical": (
            "Use precise technical language with detailed specifications and metrics. "
            "Assume a technically proficient audience; include exact values where available."
        ),
    }.get(tone, "Use formal, professional language appropriate for enterprise whitepapers.")

    features = structured_data.get("features", [])
    integrations = structured_data.get("integrations", [])
    compliance = structured_data.get("compliance", [])
    performance_metrics = structured_data.get("performance_metrics", [])
    limitations = structured_data.get("limitations", [])

    features_text = (
        "\n".join(f"- {f.get('name', '')}: {f.get('description', '')}" for f in features)
        or "No features provided."
    )
    integrations_text = (
        "\n".join(
            f"- {i.get('system', '')} via {i.get('method', '')}: {i.get('notes', '')}".strip(" :")
            for i in integrations
        )
        or "No integrations provided."
    )
    compliance_text = (
        "\n".join(
            f"- {c.get('standard', '')} ({c.get('status', '')}): {c.get('details', '')}"
            for c in compliance
        )
        or "No compliance information provided."
    )
    performance_text = (
        "\n".join(
            f"- {p.get('metric', '')}: {p.get('value', '')} {p.get('unit', '')}".rstrip()
            for p in performance_metrics
        )
        or "No performance metrics provided."
    )
    limitations_text = (
        "\n".join(
            f"- [{lim.get('category', '')}] {lim.get('description', '')}"
            for lim in limitations
        )
        or "No limitations provided."
    )

    prompt = f"""You are a technical writer generating a product whitepaper.

STRICT RULES:
1. Only use facts explicitly listed in the FACT SHEET below. Do NOT invent, infer, or add \
any facts not present in this fact sheet.
2. Do NOT use superlatives (e.g., "best", "fastest", "industry-leading") unless the fact \
sheet explicitly states a comparative metric with a source.
3. Structure your output into exactly these seven sections in this order:
   - Introduction
   - Features
   - Integrations
   - Compliance
   - Performance
   - Limitations
   - Conclusion
4. Tone: {tone_instruction}
5. Maximum output length: {max_draft_length} characters.
6. Begin each section with a markdown H1 heading (e.g., # Introduction).

FACT SHEET:

FEATURES:
{features_text}

INTEGRATIONS:
{integrations_text}

COMPLIANCE:
{compliance_text}

PERFORMANCE METRICS:
{performance_text}

LIMITATIONS:
{limitations_text}

Generate the whitepaper now. Begin with '# Introduction'."""

    return prompt


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_retryable_error(exc: BaseException) -> bool:
    """Return True for transient LLM provider errors that warrant an automatic retry.

    Covers both Anthropic and OpenAI-compatible providers (Gemini, xAI, Perplexity).
    Retryable conditions:
    - HTTP 5xx (server error) — APIStatusError with status >= 500 from either SDK

    RateLimitError (429) is intentionally excluded from automatic tenacity retries
    to prevent excessive API hit loops when a quota is truly exhausted. Higher-level
    logic manages document-specific retries.

    Timeouts are intentionally excluded: retrying a timed-out call would compound
    the delay (3 × timeout_seconds). Let timeouts surface immediately.
    """
    if isinstance(exc, anthropic.APIStatusError) and exc.status_code >= 500:
        return True
    if isinstance(exc, openai.APIStatusError) and exc.status_code >= 500:
        return True
    return False


def _log_token_usage(model: str, tone: str, input_tokens: int, output_tokens: int) -> None:
    """Emit a structured log line for LLM token consumption.

    Used for cost tracking and quota monitoring.
    """
    logger.info(
        "LLM token usage: model=%s tone=%s input_tokens=%d output_tokens=%d total_tokens=%d",
        model,
        tone,
        input_tokens,
        output_tokens,
        input_tokens + output_tokens,
    )


# ---------------------------------------------------------------------------
# LLM Caller
# ---------------------------------------------------------------------------

@retry(
    retry=retry_if_exception(_is_retryable_error),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def _call_llm(prompt: str, tone: str, model_name: str, settings: ActiveSettings, timeout_seconds: float = 120.0) -> str:
    """Call the configured LLM provider to generate a whitepaper draft.

    Behaviour:
    - Routes to the correct provider SDK via llm_adapter.call_llm.
    - Automatically retries up to 3 times (exponential backoff 2–10 s) on
      HTTP 429, 5xx, and timeout errors via the tenacity decorator.

    Args:
        prompt:          Complete structured prompt with injected FactSheet data.
        tone:            Requested prose tone — forwarded to logging for observability.
        model_name:      Model ID (from DB settings).
        settings:        ActiveSettings snapshot with provider API keys.
        timeout_seconds: Request timeout in seconds (from DB settings, default 120).

    Returns:
        Generated markdown string from the LLM.
    """
    logger.info(
        "LLM call start: model=%s tone=%s prompt_length=%d",
        model_name,
        tone,
        len(prompt),
    )

    text = llm_adapter.call_llm(
        prompt=prompt,
        model_name=model_name,
        settings=settings,
        timeout=timeout_seconds,
        max_tokens=8096,
        temperature=0.2,
    )

    logger.info("LLM call complete: model=%s tone=%s output_length=%d", model_name, tone, len(text))
    return text


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_draft(db: Session, document_id: str, tone: str = "formal") -> DraftVersion:
    """
    Generate a fact-grounded whitepaper draft for the given document.

    Workflow:
      1. Fetch active settings from DB (cached, 60 s TTL)
      2. Verify document exists → NotFoundError if not
      3. Fetch latest FactSheet  → NoFactSheetError if none
      4. Build structured LLM prompt from FactSheet data
      5. Call LLM to generate content (re-raises on failure, before any DB writes)
      6. Enforce max_draft_length (truncate if needed)
      7. Auto-increment iteration_number (MAX existing + 1, starts at 1)
      8. Add DraftVersion to session
      9. Transition document status: DRAFT → VALIDATING
      10. Add AuditLog entry
      11. Commit atomically — on failure, rollback all changes and re-raise

    Args:
        db:          Active SQLAlchemy session.
        document_id: UUID string identifying the target Document.
        tone:        Draft prose style — "formal", "conversational", or "technical".

    Returns:
        The newly created and persisted DraftVersion ORM instance.

    Raises:
        NotFoundError:    document_id does not exist.
        NoFactSheetError: The document has no associated FactSheet row.
        Exception:        Any LLM or DB failure — full transaction is rolled back.
    """
    logger.info("generate_draft: document_id=%s tone=%s", document_id, tone)

    # ── 1. Fetch active settings ───────────────────────────────────────────
    active = settings_service.get_settings(db)
    llm_model = active.llm_model_name
    max_length = active.max_draft_length
    timeout_seconds = float(active.llm_timeout_seconds)

    # ── 2. Verify document exists ──────────────────────────────────────────
    doc = db.query(Document).filter(Document.id == document_id).first()
    if doc is None:
        raise NotFoundError(f"Document {document_id} not found")

    # ── 3. Fetch latest FactSheet ──────────────────────────────────────────
    fact_sheet = (
        db.query(FactSheet)
        .filter(FactSheet.document_id == document_id)
        .order_by(FactSheet.created_at.desc())
        .first()
    )
    if fact_sheet is None:
        raise NoFactSheetError(
            f"Document {document_id} has no fact sheet. "
            "Run POST /extract-factsheet before generating a draft."
        )

    # ── 3.5. Pre-generation progress update ────────────────────────────────
    # Commit BEFORE the LLM call so the status-polling endpoint reflects
    # "DRAFT_GENERATING" during the (potentially 60–120 s) generation step
    # instead of appearing idle. Without this the document stays at its
    # previous stage and the UI cannot distinguish "in progress" from "idle".
    doc.current_stage = "DRAFT_GENERATING"
    doc.validation_progress = 10
    db.commit()

    # ── 4. Build LLM prompt ────────────────────────────────────────────────
    prompt = _build_prompt(fact_sheet.structured_data, tone, max_length)
    logger.debug("Prompt built: document_id=%s length=%d", document_id, len(prompt))

    # ── 5. Call LLM ───────────────────────────────────────────────────────
    try:
        content_markdown = _call_llm(prompt, tone, llm_model, active, timeout_seconds)
    except (anthropic.RateLimitError, openai.RateLimitError) as exc:
        reason = llm_adapter.clean_llm_error(exc)
        logger.error("LLM rate limit / quota exceeded: document_id=%s error=%s", document_id, exc)
        raise RateLimitError(f"LLM rate Limit Exceeded: {reason}") from exc
    except Exception as exc:
        logger.error(
            "LLM call failed: document_id=%s error_type=%s error=%s",
            document_id,
            type(exc).__name__,
            exc,
        )
        # Mark the stage as failed so the UI stops showing "Generating…"
        try:
            doc.current_stage = "DRAFT_FAILED"
            doc.validation_progress = 0
            db.commit()
        except Exception:
            pass  # Best-effort — do not mask the original LLM error
        raise

    # ── 6. Enforce max draft length ────────────────────────────────────────
    if len(content_markdown) > max_length:
        content_markdown = content_markdown[:max_length]
        logger.warning(
            "Draft truncated to max_draft_length=%d: document_id=%s",
            max_length,
            document_id,
        )

    # ── 7. Auto-increment iteration_number ────────────────────────────────
    max_iteration = (
        db.query(func.max(DraftVersion.iteration_number))
        .filter(DraftVersion.document_id == document_id)
        .scalar()
    )
    iteration_number = (max_iteration or 0) + 1

    # ── 8. Create DraftVersion ─────────────────────────────────────────────
    draft = DraftVersion(
        document_id=document_id,
        iteration_number=iteration_number,
        content_markdown=content_markdown,
        tone=tone,
        score=None,
        user_prompt="",   # Fact-sheet path: no user-supplied prompt
    )
    db.add(draft)

    # ── 9. Transition document status and record pipeline progress ─────────
    doc.status = DocumentStatus.VALIDATING
    doc.current_stage = "DRAFT_GENERATED"
    doc.validation_progress = 25

    # ── 10. Audit log ───────────────────────────────────────────────────────
    audit_action = (
        f"Draft generated: iteration={iteration_number} tone={tone} "
        f"fact_sheet_id={fact_sheet.id} content_length={len(content_markdown)}"
    )
    db.add(AuditLog(document_id=document_id, action=audit_action[:512]))

    # ── 11. Atomic commit ──────────────────────────────────────────────────
    try:
        db.commit()
        db.refresh(draft)
        logger.info(
            "Draft committed: document_id=%s draft_id=%s iteration=%d",
            document_id,
            draft.id,
            iteration_number,
        )
    except Exception as exc:
        db.rollback()
        logger.error(
            "Transaction rolled back: document_id=%s error=%s",
            document_id,
            exc,
        )
        raise

    return draft


# ---------------------------------------------------------------------------
# Prompt-First Draft Generation (new architecture)
# ---------------------------------------------------------------------------

_DOC_TYPE_TEMPLATES: dict[str, dict] = {
    "whitepaper": {
        "persona": (
            "You are a world-class technical writer and industry analyst — the calibre "
            "of a Gartner or Forrester analyst combined with a senior solutions architect. "
            "Your task is to produce a comprehensive, publication-ready enterprise whitepaper "
            "that would impress a CTO or VP of Engineering."
        ),
        "structure": """\
# Executive Summary
Write 2–3 tight paragraphs: what this document covers, who it is for, and the 3–5 key takeaways. \
End with a bulleted key-takeaways list.

# Introduction
Set the scene: industry context, the problem being solved, why it matters now. \
Include at least one specific market-size figure or industry statistic from your knowledge.

# [Primary Topic — derive from the client request]
The main technical or strategic deep-dive. Use sub-sections. Be specific: \
name real protocols, standards, architectures, and technologies. \
Include a conceptual architecture or workflow described in clear prose.

# Key Features & Capabilities
Present each feature with a **bold feature name** followed by a concise, specific description. \
Group related features under `##` sub-headings.

# Integrations & Ecosystem
List supported integrations, APIs, SDKs, and partner ecosystems. \
Name real products and protocols. Use a markdown table where comparison adds value.

# Performance & Benchmarks
Concrete performance characteristics: throughput, latency, scalability limits, SLA targets. \
Use a markdown table for comparative metrics.

# Compliance, Security & Governance
Applicable standards (ISO 27001, SOC 2, GDPR, HIPAA, FedRAMP, etc.). \
Describe specific security controls, audit capabilities, and data-handling policies.

# Use Cases & Industry Applications
Present 3–5 detailed use cases using this structure:
**Industry / Persona** → **Challenge** → **Solution approach** → **Measurable outcome**

# Limitations & Considerations
Be candid. Prerequisites, known constraints, and scenarios where this solution is not ideal.

# Conclusion & Recommendations
Summarise the top 3–5 points. Provide a clear recommended next step for the reader.""",
        "start_heading": "# Executive Summary",
        "tone_hint": "Authoritative, evidence-based, enterprise-grade. Avoid marketing superlatives without backing data.",
    },
    "blog": {
        "persona": (
            "You are an expert tech blogger and thought leader with deep subject-matter expertise. "
            "Your task is to write an engaging, informative blog post that educates practitioners "
            "while being accessible and shareable. Think: Stripe engineering blog, Netflix tech blog, "
            "or a well-researched Medium article."
        ),
        "structure": """\
# [Compelling Title — derive from the client request]
A hook: open with a surprising stat, a provocative question, or a vivid scenario. \
Draw the reader in immediately. 1–2 paragraphs.

## Background & Context
Why does this topic matter right now? Briefly set the scene for the reader.

## [Main Topic — derive from the client request]
The core of the post. Use `##` sub-sections. Be concrete: real examples, real numbers, \
real tools. Walk the reader through the key concepts or steps.

## Key Takeaways
A tight bulleted list of 4–6 actionable insights the reader should remember.

## Conclusion
Wrap up with a clear call-to-action or next step for the reader.""",
        "start_heading": "# ",
        "tone_hint": "Conversational yet expert. Engaging, direct, and jargon-free where possible. Use 'you' to address the reader.",
    },
    "technical_doc": {
        "persona": (
            "You are a senior software architect and technical writer producing official "
            "product documentation. Your goal is comprehensive, precise, and immediately "
            "actionable technical reference material — think AWS docs, Stripe API docs, "
            "or Kubernetes documentation."
        ),
        "structure": """\
# Overview
What this document covers, the intended audience, and prerequisites.

# Architecture
High-level architecture diagram described in prose. Key components, data flow, \
and design decisions. Use ASCII-art-style diagrams if helpful.

# Core Concepts
Define the key terms, abstractions, and mental models the user needs to understand.

# Getting Started
Step-by-step setup instructions. Number each step. Include realistic command examples \
using `inline code`.

# Configuration Reference
Key configuration parameters in a markdown table: \
| Parameter | Type | Default | Description |

# Usage Examples
At least 3 concrete, realistic code or command examples with explanations.

# Troubleshooting
Common errors and their resolutions in a structured format: \
**Error** → **Cause** → **Resolution**

# API / CLI Reference
Endpoints, commands, or functions. For each: signature, parameters, return values, \
and a short example.

# Limitations & Known Issues
Current constraints, unsupported scenarios, and planned improvements.""",
        "start_heading": "# Overview",
        "tone_hint": "Precise, unambiguous, and direct. Use active voice. Every claim must be specific and verifiable.",
    },
    "case_study": {
        "persona": (
            "You are a business case analyst and solutions consultant producing a compelling "
            "customer case study. Your goal is to tell a credible, specific story that "
            "demonstrates measurable business value — the kind used in analyst briefings, "
            "sales enablement, and conference presentations."
        ),
        "structure": """\
# Executive Summary
One paragraph: who the customer is, what they achieved, and the headline metric.

# Customer Background
Organisation profile: industry, size, technical environment, and key challenges \
they faced before the solution.

## The Challenge
Describe the specific business and technical problem in detail. \
What was the impact of the status quo? Use specific numbers where possible.

# The Solution
How the solution was applied. Architecture, key features used, integration approach. \
Timeline and implementation phases.

# Results & Impact
The measurable outcomes — quantify everything possible. \
Use a table for before/after comparisons: \
| Metric | Before | After | Improvement |

## Customer Perspective
A realistic, attribution-style quote summarising the value delivered.

# Conclusion & Recommendations
What other organisations in similar situations should consider. \
Next steps for the reader.""",
        "start_heading": "# Executive Summary",
        "tone_hint": "Credible, story-driven, and results-focused. Specific numbers over vague claims. Professional but not jargon-heavy.",
    },
    "product_brief": {
        "persona": (
            "You are a product marketing manager and solutions architect writing a concise "
            "product brief for a technical audience. Your goal is to communicate the product's "
            "value proposition, key capabilities, and fit — quickly and clearly."
        ),
        "structure": """\
# Product Overview
What the product does, who it's for, and the core value proposition in 2–3 sentences.

## Key Differentiators
3–5 bullet points that distinguish this product from alternatives.

# Key Features
Present each feature with a **bold name** and a one-sentence description of the benefit. \
Group by category using `##` sub-headings.

# Technical Specifications
A table of technical details: \
| Spec | Value | Notes |

# Supported Integrations
A concise table of integrations: system, method, and notes.

# Use Cases
3 concise use cases (2–3 sentences each): who uses it, for what, with what outcome.

# Requirements & Compatibility
Prerequisites, minimum requirements, and supported platforms/environments.

# Getting Started
The simplest possible path to first value — 3–5 steps.""",
        "start_heading": "# Product Overview",
        "tone_hint": "Clear, benefit-driven, and concise. Every sentence should earn its place. Avoid filler words.",
    },
    "research_report": {
        "persona": (
            "You are a research analyst producing a rigorous, data-driven research report. "
            "Your goal is an authoritative, well-structured analysis with clear findings "
            "and recommendations — the calibre of a Gartner Magic Quadrant, IDC report, "
            "or academic research paper."
        ),
        "structure": """\
# Abstract
A concise summary (150–200 words): research question, methodology, key findings, \
and primary recommendation.

# Introduction
Research context, motivation, scope, and the specific question(s) this report addresses.

# Methodology
How the analysis was conducted. Data sources, evaluation criteria, scope boundaries. \
Be specific about what was and was not included.

# Market & Industry Context
Current state of the market. Key trends, drivers, and headwinds. \
Include quantitative data (market size, growth rates, adoption statistics).

# Findings
The core analytical content. Use `##` sub-sections for each major finding. \
Support each finding with evidence. Use tables and lists to structure complex data.

## Comparative Analysis
Where applicable, compare approaches, vendors, or options using a structured table.

# Discussion
Interpret the findings. What do they mean? What are the implications?

# Conclusions
The top 3–5 conclusions drawn from the analysis.

# Recommendations
Specific, actionable recommendations for different audiences (e.g. CTO, DevOps team). \
Prioritise by impact and urgency.

# References & Further Reading
Cite real, credible sources (organisations, standards bodies, research firms).""",
        "start_heading": "# Abstract",
        "tone_hint": "Analytical, objective, and evidence-based. Academic rigor with practical relevance. Avoid advocacy; present evidence.",
    },
}


def _build_prompt_optimizer_prompt(raw_prompt: str, document_type: str) -> str:
    """Build the meta-prompt that instructs the LLM to refine the user's raw request.

    Stage 1: Internal Prompt Optimization — analyze the raw prompt for clarity,
    specificity, structure, and completeness, then expand and restructure it into
    a precise, detailed generation instruction without altering the user's intent.

    Args:
        raw_prompt:    The user's original natural-language request.
        document_type: Target document type (whitepaper, blog, technical_doc, etc.).

    Returns:
        Meta-prompt string ready to send to the optimizer LLM.
    """
    return f"""You are an expert prompt engineer and document architect specializing in \
{document_type} documents.

Your task is to REFINE and EXPAND the following user request into an optimized \
generation instruction that will produce the highest-quality {document_type} possible.

USER'S RAW REQUEST:
{raw_prompt}

Analyze the raw request across four dimensions:
1. **Clarity** — Is the intent unambiguous? Are there vague terms that need defining?
2. **Specificity** — Are the target audience, depth level, scope, and tone explicit?
3. **Structure** — Are the required sections, topics, or narrative arc clear?
4. **Completeness** — What context is missing that a skilled technical writer would need?

Then produce a REFINED INTERNAL PROMPT that:
- Preserves the user's original intent exactly — do NOT change what they asked for.
- Adds a concrete target audience (e.g., "CTOs at mid-market SaaS companies").
- Specifies required technical depth (conceptual / intermediate / expert-level detail).
- Clarifies any ambiguous terms or topics with precise definitions.
- States the expected output length and formatting expectations.
- Names specific sub-topics, examples, or data types the document should cover.
- Specifies the prose tone (formal / conversational / technical) appropriate for a {document_type}.
- Is written as a direct, imperative instruction to a senior technical writer.

OUTPUT FORMAT:
Return ONLY the refined prompt text. No preamble, no explanation, no labels.
Begin directly with the refined prompt content."""


@retry(
    retry=retry_if_exception(_is_retryable_error),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def _call_llm_optimize(
    raw_prompt: str,
    document_type: str,
    model_name: str,
    settings: ActiveSettings,
    timeout_seconds: float = 60.0,
) -> str:
    """Stage 1: Call the LLM to produce an optimized internal prompt.

    A lightweight call (max_tokens=600, temperature=0.1) that refines the user's
    raw request for maximum generation quality. Lower token budget keeps latency
    acceptable — the optimizer output is a prompt, not a document.

    Args:
        raw_prompt:      The user's original natural-language request.
        document_type:   Target document type (controls optimizer persona).
        model_name:      Model ID (from DB settings).
        settings:        ActiveSettings snapshot with provider API keys.
        timeout_seconds: Request timeout (default 60 s — shorter than generation).

    Returns:
        Refined prompt string. Falls back to raw_prompt if the LLM returns empty.
    """
    optimizer_prompt = _build_prompt_optimizer_prompt(raw_prompt, document_type)

    logger.info(
        "Prompt optimizer call: model=%s document_type=%s raw_prompt_length=%d",
        model_name,
        document_type,
        len(raw_prompt),
    )

    refined = llm_adapter.call_llm(
        prompt=optimizer_prompt,
        model_name=model_name,
        settings=settings,
        timeout=timeout_seconds,
        max_tokens=600,
        temperature=0.1,
    ).strip()

    if not refined:
        logger.warning(
            "Prompt optimizer returned empty response — falling back to raw prompt."
        )
        return raw_prompt

    logger.info(
        "Prompt optimization complete: original_length=%d refined_length=%d",
        len(raw_prompt),
        len(refined),
    )
    return refined


def _build_prompt_from_user_request(
    prompt: str,
    context_text: str,
    max_draft_length: int,
    document_type: str = "whitepaper",
    refined_prompt: Optional[str] = None,
    tone: str = "formal",
) -> str:
    """
    Build a high-quality LLM prompt that drives publication-ready document output.

    The user prompt is the primary driver. When a refined_prompt is supplied
    (from Stage 1 prompt optimization), it is used as the primary generation
    instruction while the original prompt is shown as context. Reference material
    (fact sheet or raw file content), when present, is injected as the authoritative
    source for product-specific claims. Document type controls the persona, required
    sections, and tone. The explicit tone parameter fine-tunes the register.

    Args:
        prompt:           The user's original natural-language document request.
        context_text:     Optional structured context from a FactSheet or TXT file.
        max_draft_length: Character cap for the generated draft (from DB settings).
        document_type:    One of whitepaper, blog, technical_doc, case_study,
                          product_brief, research_report.
        refined_prompt:   Stage 1 optimized prompt, if available. When present this
                          becomes the primary generation instruction.
        tone:             Explicit prose register: formal | conversational | technical.

    Returns:
        Complete prompt string ready for the LLM.
    """
    template = _DOC_TYPE_TEMPLATES.get(document_type, _DOC_TYPE_TEMPLATES["whitepaper"])
    persona = template["persona"]
    structure = template["structure"]
    start_heading = template["start_heading"]
    tone_hint = template["tone_hint"]

    _tone_instructions = {
        "formal": "Formal and professional — authoritative, objective, enterprise-grade prose.",
        "conversational": "Conversational and accessible — engaging, clear, address the reader as 'you'.",
        "technical": "Technical and precise — assume expert audience, use exact specifications and metrics.",
    }
    explicit_tone = _tone_instructions.get(tone, _tone_instructions["formal"])

    context_section = context_text.strip() if context_text else ""
    if context_section:
        reference_block = (
            "## REFERENCE MATERIAL\n"
            "The following verified data is your primary source for all "
            "product-specific facts, figures, and claims. Prefer this over "
            "general knowledge when the two differ.\n\n"
            f"{context_section}"
        )
    else:
        reference_block = (
            "## KNOWLEDGE SOURCE\n"
            "No reference document was provided. Draw on your comprehensive "
            "training knowledge to supply accurate, specific, and well-established "
            "facts — real industry standards, real market data, real benchmarks, "
            "real product capabilities. Every claim must be grounded in knowledge "
            "you are confident is accurate."
        )

    # Stage 1 integration: use refined prompt as primary driver when available
    if refined_prompt and refined_prompt.strip() and refined_prompt.strip() != prompt.strip():
        client_request_block = (
            f"ORIGINAL USER REQUEST:\n{prompt}\n\n"
            f"REFINED INTERNAL PROMPT (use this as your primary generation guide):\n"
            f"{refined_prompt}"
        )
    else:
        client_request_block = prompt

    return f"""{persona}

## CLIENT REQUEST
{client_request_block}

{reference_block}

## REQUIRED DOCUMENT STRUCTURE
Produce the document with the following sections using H1 (`#`) headings. \
Add H2 (`##`) sub-headings freely within each section for clarity. \
Every section must be fully written — no placeholders, no "TBD", no refusals.

{structure}

---

## FORMATTING RULES — MANDATORY
1. **Markdown richness**: Use tables, bold, italic, inline `code`, bullet lists, \
numbered lists, and blockquotes (`>`) for callouts or key statistics.
2. **Specificity**: Never write vague phrases like "high performance" or "large market". \
Write "sub-10 ms p99 latency" or "$12.4 billion addressable market (IDC, 2024)".
3. **No placeholders**: Never write "[Insert X here]", "TBD", "N/A", or similar. \
If specific data is unknown, provide the closest accurate general-knowledge equivalent.
4. **Tone**: {explicit_tone} Style guidance for this document type: {tone_hint}
5. **Key Takeaways**: End every major section (H1) with a blockquote callout:
   > **Key Takeaway**: one specific, compelling insight from that section.
6. **Sentence length**: Every sentence must be ≤ 30 words. \
Split any longer sentence into two shorter ones.
7. **Paragraph length**: Every paragraph must be ≤ 5 sentences. \
Add a blank line between every paragraph and between list items.
8. **Active voice**: Begin each paragraph with an active-voice topic sentence. \
Avoid passive constructions (e.g., prefer "The system processes X" over "X is processed").
9. **Length**: Write a thorough document. Do not cut sections short. \
Maximum output: {max_draft_length} characters.

Generate the complete document now. Begin with `{start_heading}`."""


def _read_file_content(file_path: str) -> str:
    """
    Read plain-text content from a stored file (TXT only).

    PDF and DOCX extraction is handled by the FactSheet pipeline; for those
    formats this helper returns an empty string so the caller falls back
    gracefully to FactSheet structured data or empty context.

    Args:
        file_path: Absolute path to the stored document file.

    Returns:
        Up to 50 000 characters of file content, or "" on any error.
    """
    try:
        if file_path and file_path.lower().endswith(".txt"):
            with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
                return fh.read(50_000)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read file content from %s: %s", file_path, exc)
    return ""


def _extract_context_from_document(db: Session, document: Document) -> str:
    """
    Derive the best available context text from a Document record.

    Priority:
    1. Latest FactSheet structured_data (JSON, already extracted by LLM).
    2. Raw TXT file content (if FactSheet absent and file is plain text).
    3. Empty string (no usable content — caller will skip the context block).

    Args:
        db:       Active SQLAlchemy session.
        document: The Document ORM instance.

    Returns:
        Context string (may be empty).
    """
    fact_sheet = (
        db.query(FactSheet)
        .filter(FactSheet.document_id == document.id)
        .order_by(FactSheet.created_at.desc())
        .first()
    )

    if fact_sheet and fact_sheet.structured_data:
        return json.dumps(fact_sheet.structured_data, indent=2)

    if document.file_path:
        return _read_file_content(document.file_path)

    return ""


def generate_draft_from_prompt(
    db: Session,
    prompt: str,
    document_id: Optional[str] = None,
    document_type: str = "whitepaper",
    tone: str = "formal",
    timeout_override: Optional[float] = None,
    suppress_status_updates: bool = False,
) -> DraftVersion:
    """
    Generate a document draft driven by the user's natural-language prompt.

    This is the prompt-first path. Key differences from generate_draft():
    - No FactSheet required — never raises NoFactSheetError.
    - No claim_registry required — never raises RegistryNotInitializedError /
      RegistryStaleError.
    - Never returns HTTP 503 for missing structured data.
    - document_id is optional context, not a hard prerequisite.

    Pipeline (four-stage Generator + Reviewer model):
      Stage 1 — Prompt Optimization:
        The raw user prompt is passed to the LLM optimizer which analyzes it for
        clarity, specificity, and completeness, then returns a refined internal
        prompt that maximises generation quality without altering intent.

      Stage 2 — Draft Generation:
        The refined prompt (with injected context and formatting rules) drives the
        Generator LLM to produce a structured, publication-ready draft.

      Stages 3 & 4 (Evaluation + Iteration) are handled by QA iteration service
      after this function returns.

    Workflow:
      1. Fetch active settings (DB-backed, cached 60 s).
      2. If document_id provided, fetch document and extract context text.
         If document not found → NotFoundError (caller maps to 404).
      3. Stage 1: Optimize the user's raw prompt via _call_llm_optimize().
         On failure, fall back gracefully to the original prompt (non-fatal).
      4. Build LLM prompt using the refined prompt as the primary driver.
      5. Stage 2: Call Generator LLM (retries on 429, 5xx, timeout — up to 3 attempts).
      6. Enforce max_draft_length (truncate if needed).
      7. Auto-increment iteration_number scoped to document_id (or 1 if standalone).
      8. Persist DraftVersion with user_prompt, tone, and source_document_id fields.
      9. If linked to a document: transition status → VALIDATING, write AuditLog.
      10. Atomic commit; rollback on failure.

    Args:
        db:            Active SQLAlchemy session.
        prompt:        User's document request (required, non-empty).
        document_id:   Optional UUID string of a Document to use as context.
        document_type: Type of document to generate (whitepaper, blog, technical_doc,
                       case_study, product_brief, research_report).
        tone:          Prose style — "formal", "conversational", or "technical".

    Returns:
        The newly created and persisted DraftVersion ORM instance.

    Raises:
        NotFoundError: document_id was supplied but the document does not exist.
        Exception:     Any LLM or DB failure — full transaction is rolled back.
    """
    logger.info(
        "generate_draft_from_prompt: document_id=%s document_type=%s tone=%s prompt_length=%d",
        document_id,
        document_type,
        tone,
        len(prompt),
    )

    # ── 1. Fetch active settings ───────────────────────────────────────────
    active = settings_service.get_settings(db)
    llm_model = active.llm_model_name
    max_length = active.max_draft_length
    timeout_seconds = timeout_override if timeout_override is not None else float(active.llm_timeout_seconds)

    # ── 2. Optional document context ───────────────────────────────────────
    context_text = ""
    doc: Optional[Document] = None

    if document_id:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if doc is None:
            raise NotFoundError(f"Document {document_id} not found.")
        context_text = _extract_context_from_document(db, doc)
        logger.debug(
            "Context extracted: document_id=%s context_length=%d",
            document_id,
            len(context_text),
        )

    # ── 2.5. Pre-generation progress update ────────────────────────────────
    # Commit BEFORE the LLM calls so the status-polling endpoint shows
    # "DRAFT_GENERATING" during the (potentially 60–120 s) generation step.
    # Without this the document stays at its previous stage and the UI
    # cannot distinguish "in progress" from "idle".
    # Skipped when suppress_status_updates=True (background retry task manages it).
    if doc is not None and not suppress_status_updates:
        doc.current_stage = "DRAFT_GENERATING"
        doc.validation_progress = 10
        db.commit()

    # ── 3. Stage 1: Prompt Optimization ───────────────────────────────────
    # Non-fatal: if optimization fails for any reason, fall back to the raw
    # prompt so the generation step is not blocked.
    # Cap at 15 s — the optimizer only refines a short prompt. We also track
    # elapsed time so Stage 2 receives the *remaining* budget from the
    # user-configured llm_timeout_seconds rather than a full second allocation,
    # preventing Stage 1 + Stage 2 from jointly exceeding that setting.
    OPTIMIZER_TIMEOUT = min(timeout_seconds * 0.15, 15.0)
    refined_prompt: Optional[str] = None
    _stage1_start = time.monotonic()
    try:
        refined_prompt = _call_llm_optimize(prompt, document_type, llm_model, active, OPTIMIZER_TIMEOUT)
    except Exception as opt_exc:
        logger.warning(
            "Prompt optimization failed — proceeding with raw prompt: "
            "document_id=%s error=%s",
            document_id,
            opt_exc,
        )
    _stage1_elapsed = time.monotonic() - _stage1_start

    # ── 4. Build LLM prompt ────────────────────────────────────────────────
    llm_prompt = _build_prompt_from_user_request(
        prompt, context_text, max_length, document_type, refined_prompt=refined_prompt, tone=tone
    )
    logger.debug("Prompt built: length=%d prompt_optimized=%s", len(llm_prompt), refined_prompt is not None)

    # ── 5. Stage 2: Call Generator LLM ────────────────────────────────────
    # Subtract Stage 1 elapsed time from the budget so combined latency stays
    # within llm_timeout_seconds. Guarantee at least 30 s for generation.
    _stage2_timeout = max(timeout_seconds - _stage1_elapsed, 30.0)
    logger.debug(
        "Stage 2 timeout budget: total=%.1fs stage1_elapsed=%.1fs stage2=%.1fs",
        timeout_seconds,
        _stage1_elapsed,
        _stage2_timeout,
    )
    try:
        content_markdown = _call_llm(llm_prompt, tone, llm_model, active, _stage2_timeout)
    except (anthropic.RateLimitError, openai.RateLimitError) as exc:
        reason = llm_adapter.clean_llm_error(exc)
        logger.error("LLM rate limit / quota exceeded: document_id=%s error=%s", document_id, exc)
        raise RateLimitError(f"LLM rate Limit Exceeded: {reason}") from exc
    except Exception as exc:
        logger.error(
            "LLM generation failed: document_id=%s error_type=%s error=%s",
            document_id,
            type(exc).__name__,
            exc,
        )
        # Mark the stage as failed so the UI stops showing "Generating…"
        # Skipped when suppress_status_updates=True (background retry task manages it).
        if doc is not None and not suppress_status_updates:
            try:
                doc.current_stage = "DRAFT_FAILED"
                doc.validation_progress = 0
                db.commit()
            except Exception:
                pass  # Best-effort — do not mask the original LLM error
        raise

    # ── 6. Enforce max draft length ────────────────────────────────────────
    if len(content_markdown) > max_length:
        content_markdown = content_markdown[:max_length]
        logger.warning(
            "Draft truncated to max_draft_length=%d: document_id=%s",
            max_length,
            document_id,
        )

    # ── 7. Auto-increment iteration_number ────────────────────────────────
    if document_id:
        # Scoped to the linked document (same as legacy path)
        max_iteration = (
            db.query(func.max(DraftVersion.iteration_number))
            .filter(DraftVersion.document_id == document_id)
            .scalar()
        )
    else:
        # Standalone draft: always iteration 1
        max_iteration = None

    iteration_number = (max_iteration or 0) + 1

    # ── 8. Create DraftVersion ─────────────────────────────────────────────
    draft = DraftVersion(
        document_id=document_id,          # links to document hierarchy (nullable)
        user_prompt=prompt,
        source_document_id=document_id,   # records which doc was used as context
        iteration_number=iteration_number,
        content_markdown=content_markdown,
        tone=tone,
        score=None,
    )
    db.add(draft)

    # ── 9. Side-effects for document-linked drafts ─────────────────────────
    if doc is not None:
        doc.status = DocumentStatus.VALIDATING
        doc.current_stage = "DRAFT_GENERATED"
        doc.validation_progress = 25
        audit_action = (
            f"Prompt-first draft generated: iteration={iteration_number} "
            f"tone={tone} prompt_optimized={refined_prompt is not None} "
            f"prompt_length={len(prompt)} content_length={len(content_markdown)}"
        )
        db.add(AuditLog(document_id=document_id, action=audit_action[:512]))

    # ── 10. Atomic commit ──────────────────────────────────────────────────
    try:
        db.commit()
        db.refresh(draft)
        logger.info(
            "Prompt-first draft committed: document_id=%s draft_id=%s iteration=%d "
            "tone=%s prompt_optimized=%s",
            document_id,
            draft.id,
            iteration_number,
            tone,
            refined_prompt is not None,
        )
    except Exception as exc:
        db.rollback()
        logger.error(
            "Transaction rolled back: document_id=%s error=%s",
            document_id,
            exc,
        )
        raise

    return draft
