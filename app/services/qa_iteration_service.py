"""
Service layer for EPIC 4 — Rubric QA + Iteration Controller.

Responsibilities:
- Evaluate DraftVersions using a six-category rubric (factual_correctness,
  technical_depth, clarity, readability, formatting, style_adherence) and a
  composite score (arithmetic mean of all six dimensions).
- Persist DraftVersion.score and DraftVersion.feedback_text after each evaluation.
- Generate improved drafts by feeding the rubric feedback back to the LLM.
- Iterate up to a configurable maximum number of cycles.
- Transition document status to PASSED (score >= threshold) or BLOCKED (limit hit).
- Write one AuditLog entry per QA iteration.
- Atomic transactions with rollback on any failure.

Settings (qa_llm_model, qa_passing_threshold, max_qa_iterations, max_draft_length)
are now fetched dynamically from the system_settings DB table via
settings_service.get_settings(), so they can be tuned from the Admin UI
without a redeploy.

Production notes:
- Per-document rate limiting / concurrency guard: add a token-bucket upstream of
  _call_llm_evaluate if this endpoint is exposed on a high-traffic path.
- For production PostgreSQL, use SELECT FOR UPDATE to prevent concurrent QA runs
  on the same document:
      db.query(Document).filter(Document.id == document_id).with_for_update().first()
  Omitted here to preserve SQLite compatibility in tests.
- Cost model: max_iterations * 2 LLM calls (evaluate + improve), minus 1 improve
  for the last iteration. Default max_iterations=3 → up to 5 LLM calls per request.
"""

import json
import logging
import os
from typing import Optional

import anthropic
import openai
from pydantic import ValidationError
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential
from sqlalchemy.orm import Session

from app.models.models import AuditLog, Document, DocumentStatus, DraftVersion, FactSheet
from app.schemas.schemas import RubricScores
from app.services import settings_service, llm_adapter
from app.services.settings_service import ActiveSettings
from app.services.exceptions import (
    InvalidRubricScoreError,
    LLMInvalidJSONError,
    MaxIterationsReachedError,
    NotFoundError,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM Callers
# ---------------------------------------------------------------------------

def _is_retryable_error(exc: BaseException) -> bool:
    """Return True for transient LLM provider errors that warrant an automatic retry.

    Covers both Anthropic and OpenAI-compatible providers (Gemini, xAI, Perplexity).
    Timeouts are intentionally excluded: retrying a timed-out call would compound
    the delay (3 × timeout_seconds). Let timeouts surface immediately.
    """
    if isinstance(exc, (anthropic.RateLimitError, openai.RateLimitError)):
        return True
    if isinstance(exc, anthropic.APIStatusError) and exc.status_code >= 500:
        return True
    if isinstance(exc, openai.APIStatusError) and exc.status_code >= 500:
        return True
    return False


@retry(
    retry=retry_if_exception(_is_retryable_error),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def _call_llm_evaluate(
    draft_content: str, fact_sheet_data: dict, qa_model: str,
    settings: ActiveSettings, timeout_seconds: float = 120.0
) -> dict:
    """Call the configured LLM provider to evaluate a draft against the rubric.

    Builds the evaluation prompt via ``_build_evaluation_prompt``, calls the
    specified ``qa_model`` via llm_adapter, and parses the JSON response.

    Args:
        draft_content:   Markdown content of the DraftVersion to evaluate.
        fact_sheet_data: Structured FactSheet data used as ground truth.
        qa_model:        Model ID for QA evaluation (from DB settings).
        settings:        ActiveSettings snapshot with provider API keys.
        timeout_seconds: Request timeout in seconds (from DB settings, default 120).

    Returns:
        Dict with keys: factual_correctness, technical_depth, clarity,
        readability, formatting, style_adherence, composite_score
        (all float 0–10), and improvement_suggestions (list[str]).
    """
    prompt = _build_evaluation_prompt(draft_content, fact_sheet_data)

    logger.info(
        "LLM evaluate call start: model=%s draft_length=%d prompt_length=%d",
        qa_model,
        len(draft_content),
        len(prompt),
    )

    raw = llm_adapter.call_llm(
        prompt=prompt,
        model_name=qa_model,
        settings=settings,
        timeout=timeout_seconds,
        max_tokens=2048,
        temperature=0.0,
    )
    logger.info("LLM evaluate raw response: model=%s raw_response=%s", qa_model, raw)

    raw = raw.strip()
    if not raw:
        raise ValueError("LLM returned empty response")

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("Invalid LLM JSON", extra={"raw_response": raw})
        raise LLMInvalidJSONError(
            "LLM returned invalid JSON during QA evaluation"
        ) from exc


@retry(
    retry=retry_if_exception(_is_retryable_error),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def _call_llm_improve(prompt: str, qa_model: str, settings: ActiveSettings, timeout_seconds: float = 120.0) -> str:
    """Call the configured LLM provider to generate an improved draft.

    Args:
        prompt:          Complete improvement prompt (built by ``_build_improvement_prompt``).
        qa_model:        Model ID (from DB settings).
        settings:        ActiveSettings snapshot with provider API keys.
        timeout_seconds: Request timeout in seconds (from DB settings, default 120).

    Returns:
        Improved draft content as a markdown string.
    """
    logger.info("LLM improve call start: model=%s prompt_length=%d", qa_model, len(prompt))
    return llm_adapter.call_llm(
        prompt=prompt,
        model_name=qa_model,
        settings=settings,
        timeout=timeout_seconds,
        max_tokens=8096,
        temperature=0.1,
    )


# ---------------------------------------------------------------------------
# Prompt Builders
# ---------------------------------------------------------------------------

def _build_evaluation_prompt(draft_content: str, fact_sheet_data: dict) -> str:
    """Build a rubric evaluation prompt instructing the LLM to return JSON scores.

    When fact_sheet_data is empty the rubric replaces fact-sheet grounding with
    a knowledge-accuracy criterion — the LLM uses its own training knowledge as
    the reference instead of a supplied fact sheet.
    """
    has_fact_sheet = bool(fact_sheet_data)

    if has_fact_sheet:
        factual_criterion = (
            "- factual_correctness: Does the draft accurately reflect the facts "
            "in the fact sheet below? Penalise any claims that contradict or are "
            "absent from the fact sheet."
        )
        ground_truth_block = f"FACT SHEET (ground truth):\n{json.dumps(fact_sheet_data, indent=2)}"
    else:
        factual_criterion = (
            "- knowledge_accuracy: Are all claims, statistics, and technical details "
            "in the draft accurate based on well-established knowledge? Penalise "
            "vague, incorrect, or unsupported statements. Use your training knowledge "
            "as the reference."
        )
        ground_truth_block = (
            "NOTE: No fact sheet was provided. Evaluate factual accuracy against "
            "your own training knowledge. Reward specific, verifiable facts and "
            "penalise vague or incorrect claims."
        )

    return f"""You are a strict JSON generator and expert document evaluator.

Evaluate the draft below and return ONLY valid JSON.
Do NOT include markdown.
Do NOT include explanation.
Do NOT include code fences.
Return ONLY raw JSON — the response must begin with {{ and end with }}.

Score the draft on SIX dimensions (each 0–10). Use the calibration anchors exactly — do NOT compress all scores into a narrow band. Scores of 9–10 must be genuinely earned.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DIMENSION 1 — factual_correctness
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{factual_criterion}
  9–10: Every claim is specific, verifiable, and precise. Exact metrics, version numbers, and authoritative figures appear throughout. Zero vague or unsubstantiated statements.
  7–8:  Most claims are accurate; a few are vague, unquantified, or lack supporting evidence. Some generic phrases ("industry-leading", "high performance") appear without values.
  5–6:  Several claims are imprecise or unsupported. Notable gaps in factual grounding; placeholders or hedging language is common.
  0–4:  Many inaccuracies, direct contradictions with the fact sheet, or significant unsupported assertions.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DIMENSION 2 — technical_depth
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Does the draft provide sufficient technical detail, concrete metrics, and specifics?
  9–10: Comprehensive specifications with real numbers, concrete examples, benchmarks, and architecture details. Every claim is backed by a specific data point or mechanism.
  7–8:  Generally detailed but some sections are vague or use filler language ("fast", "scalable", "efficient") without quantified values.
  5–6:  Limited depth. Several sections stay at surface level without supporting metrics, diagrams, or worked examples.
  0–4:  Minimal technical content. Reads like a marketing blurb; no substantive technical information present.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DIMENSION 3 — clarity
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Is the draft well-structured, logically organised, and free of ambiguity?
  9–10: Exceptionally clear. Each section opens with a strong topic sentence, transitions flow naturally, sentences are concise (≤30 words), and no reader confusion is possible.
  7–8:  Generally clear but some sections are dense, poorly transitioned, or contain redundant phrasing.
  5–6:  Noticeable clarity issues: inconsistent heading hierarchy, paragraphs that mix multiple ideas, or convoluted sentence construction.
  0–4:  Difficult to follow. Logical flow is absent, structure is incoherent, or the document is self-contradictory.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DIMENSION 4 — readability
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Assess sentence length variation, paragraph rhythm, active-voice usage, and prose flow.
  9–10: Sentences vary naturally between short punchy ones and medium-length explanatory ones. Paragraphs are 3–5 sentences max, separated by blank lines. Active voice dominates (>80%). Reading requires zero re-reading.
  7–8:  Mostly readable but has occasional run-on sentences (>40 words), passive-voice clusters, or wall-of-text paragraphs that slow reading pace.
  5–6:  Frequent readability issues: monotonous sentence length, dense paragraphs (6+ sentences), heavy nominalisation ("the utilisation of" instead of "using"), or excessive jargon without explanation.
  0–4:  Very poor readability. Sentences are consistently too long or too choppy, passive voice throughout, or paragraph structure is absent.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DIMENSION 5 — formatting
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Evaluate headings, bullet lists, tables, spacing, and overall visual hierarchy.
  9–10: Consistent H1/H2/H3 hierarchy with no skipped levels. Technical comparisons use tables. Feature lists use bullets. Procedures use numbered lists. Blank lines separate every block element. Code/commands are in fenced blocks. Visual scan reveals structure instantly.
  7–8:  Mostly well-formatted but some inconsistencies: occasional skipped heading levels, a list where a table would be clearer, or sparse blank-line separation.
  5–6:  Several formatting problems: dense prose where lists or tables are needed, mixed heading styles, or important code presented as inline text.
  0–4:  Poor formatting. No visual hierarchy, walls of prose, no use of lists/tables/headings, or heading levels used arbitrarily.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DIMENSION 6 — style_adherence
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Measure alignment with the document's stated tone, template structure, and brand guidelines (professional polish, consistent terminology, and presentation standards).
  9–10: Tone is perfectly consistent with the document type (e.g. formal/authoritative for whitepapers, accessible for blogs). All expected template sections are present and in the correct order. Terminology is consistent throughout. No casual or off-brand language.
  7–8:  Generally on-brand but minor inconsistencies: one or two sections that drift in tone, a missing minor template element, or a few inconsistent product/feature name capitalisations.
  5–6:  Noticeable style drift: mixed formal/casual registers, missing required template sections, inconsistent capitalisation, or product names written differently across sections.
  0–4:  Style is significantly off-brand or mismatched to the document type. Template structure is largely absent or ignored.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SCORING RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- composite_score = arithmetic mean of all six dimension scores, rounded to 4 decimal places.
- improvement_suggestions: for EACH dimension that scores below 9, provide ONE specific, actionable instruction that names the exact section to change and what the change must be. If a dimension scores 9 or above, omit its suggestion. The array may therefore have 0–6 items. Each entry must follow this pattern: "[DIMENSION] — Section '<section name>': <concrete change required>." If ALL six dimensions score 9 or above, output an empty array: [].

{ground_truth_block}

Draft:
{draft_content}

Return ONLY this exact JSON object — no preamble, no explanation, no markdown fences:
{{
  "factual_correctness": <float 0-10>,
  "technical_depth": <float 0-10>,
  "clarity": <float 0-10>,
  "readability": <float 0-10>,
  "formatting": <float 0-10>,
  "style_adherence": <float 0-10>,
  "composite_score": <float 0-10>,
  "improvement_suggestions": []
}}"""


def _build_improvement_prompt(
    draft_content: str,
    feedback: str,
    fact_sheet_data: dict,
    tone: str,
    max_draft_length: int,
    previous_scores: Optional[dict] = None,
    cumulative_feedback: Optional[list] = None,
    improvement_suggestions: Optional[list] = None,
    iteration_number: int = 1,
    effective_max: int = 3,
    document_type: str = "whitepaper",
) -> str:
    """Build an improvement prompt that incorporates rubric feedback.

    When fact_sheet_data is empty the LLM is instructed to draw on its own
    training knowledge to supply accurate, specific facts instead of being
    restricted to a supplied fact sheet.

    Args:
        previous_scores:     Dict with factual_correctness, technical_depth, clarity,
                             composite_score from the current draft's evaluation.
        cumulative_feedback: Ordered list of all feedback strings from iteration 1
                             through the current iteration (inclusive). Used to
                             prevent improvements from undoing prior fixes.
        iteration_number:    The iteration that just failed (1-based). The next
                             draft will be iteration_number + 1.
        effective_max:       Total allowed iterations, so the LLM knows urgency.
        document_type:       Document type (whitepaper, blog, technical_doc, etc.)
                             Controls which section structure the LLM must maintain.
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

    has_fact_sheet = bool(fact_sheet_data)

    # ── Document-type-specific canonical section structure ─────────────────
    # Applied only when a fact sheet is present (fact-grounded path). The
    # prompt-first path (no fact sheet) preserves whatever structure the
    # Generator LLM created — avoids breaking non-whitepaper layouts.
    _DOC_TYPE_SECTIONS: dict[str, str] = {
        "whitepaper": (
            "Introduction, Features, Integrations, Compliance, Performance, "
            "Limitations, Conclusion"
        ),
        "blog": "Title, Background & Context, Main Topic, Key Takeaways, Conclusion",
        "technical_doc": (
            "Overview, Architecture, Core Concepts, Getting Started, "
            "Configuration Reference, Usage Examples, Troubleshooting, "
            "API / CLI Reference, Limitations & Known Issues"
        ),
        "case_study": (
            "Executive Summary, Customer Background, The Challenge, "
            "The Solution, Results & Impact, Conclusion & Recommendations"
        ),
        "product_brief": (
            "Product Overview, Key Features, Technical Specifications, "
            "Supported Integrations, Use Cases, Requirements & Compatibility, "
            "Getting Started"
        ),
        "research_report": (
            "Abstract, Introduction, Methodology, Market & Industry Context, "
            "Findings, Discussion, Conclusions, Recommendations, "
            "References & Further Reading"
        ),
    }

    if has_fact_sheet:
        facts_rules = (
            "1. Only use facts explicitly listed in the FACT SHEET below. "
            "Do NOT invent or infer any facts not present in the fact sheet.\n"
            f"FACT SHEET (ground truth):\n{json.dumps(fact_sheet_data, indent=2)}"
        )
        section_list = _DOC_TYPE_SECTIONS.get(
            document_type, _DOC_TYPE_SECTIONS["whitepaper"]
        )
        structure_rule = (
            f"3. Maintain the required section structure for a {document_type}: "
            f"{section_list}.\n"
            "   Begin each section with a markdown H1 heading."
        )
        closing = (
            f"Generate the improved {document_type} now. "
            "Begin with the first section heading."
        )
    else:
        facts_rules = (
            "1. No fact sheet is provided. Draw on your comprehensive training knowledge "
            "to supply accurate, specific, and well-known facts, figures, and technical details. "
            "Include real metrics, industry-standard values, and verifiable information. "
            "Do NOT generate vague placeholders or refuse to write content — produce a "
            "complete, information-rich document using your knowledge."
        )
        structure_rule = (
            "3. Preserve the existing document structure and all section headings from "
            "the previous draft. Do NOT change the document type or restructure sections — "
            "only improve the content within each section."
        )
        closing = "Generate the improved document now, beginning with the same first heading as the previous draft."

    # ── Score context block ────────────────────────────────────────────────
    # Identify the weakest scoring area so the LLM knows where to focus.
    if previous_scores:
        fc   = previous_scores.get("factual_correctness", 0.0)
        td   = previous_scores.get("technical_depth", 0.0)
        cl   = previous_scores.get("clarity", 0.0)
        rd   = previous_scores.get("readability", 0.0)
        fm   = previous_scores.get("formatting", 0.0)
        sa   = previous_scores.get("style_adherence", 0.0)
        comp = previous_scores.get("composite_score", 0.0)

        # Rank all six dimensions from weakest to strongest
        category_scores = [
            ("Factual Correctness", fc),
            ("Technical Depth",     td),
            ("Clarity",             cl),
            ("Readability",         rd),
            ("Formatting",          fm),
            ("Style Adherence",     sa),
        ]
        category_scores.sort(key=lambda x: x[1])
        weakest  = category_scores[0]
        strongest = category_scores[-1]

        score_block = (
            f"\nCURRENT DRAFT SCORES (from rubric evaluation — iteration {iteration_number}/{effective_max}):\n"
            f"  • Factual Correctness : {fc:.1f}/10\n"
            f"  • Technical Depth     : {td:.1f}/10\n"
            f"  • Clarity             : {cl:.1f}/10\n"
            f"  • Readability         : {rd:.1f}/10\n"
            f"  • Formatting          : {fm:.1f}/10\n"
            f"  • Style Adherence     : {sa:.1f}/10\n"
            f"  • Composite Score     : {comp:.2f}/10  ← must INCREASE in the next version\n\n"
            f"WEAKEST AREA  → {weakest[0]} ({weakest[1]:.1f}/10): prioritise improvements here first.\n"
            f"STRONGEST AREA → {strongest[0]} ({strongest[1]:.1f}/10): preserve this quality — "
            "do NOT regress content in this area.\n"
        )
        iterations_remaining = effective_max - iteration_number
        urgency = (
            f"You have {iterations_remaining} improvement attempt(s) remaining. "
            "Every section must be meaningfully better than the previous draft."
        )
    else:
        score_block = ""
        urgency = ""

    # ── Cumulative feedback block ──────────────────────────────────────────
    # Show all previous feedback so the LLM doesn't undo already-fixed issues.
    if cumulative_feedback and len(cumulative_feedback) > 1:
        prior_items = cumulative_feedback[:-1]  # All iterations except the current one
        prior_block = "\n\nPREVIOUS ITERATIONS' FEEDBACK (already addressed — do NOT regress these):\n"
        for idx, prior_fb in enumerate(prior_items, start=1):
            prior_block += f"  [Iteration {idx}]: {prior_fb}\n"
    else:
        prior_block = ""

    # ── Fact sheet display block ───────────────────────────────────────────
    if has_fact_sheet:
        fact_sheet_block = f"FACT SHEET (ground truth):\n{json.dumps(fact_sheet_data, indent=2)}"
    else:
        fact_sheet_block = (
            "FACT SHEET: None provided — draw on authoritative training knowledge "
            "to supply accurate, specific, and verifiable facts."
        )

    # ── Feedback block — structured list when available, string fallback ──────
    if improvement_suggestions:
        feedback_block = "\n".join(
            f"{i + 1}. {s}" for i, s in enumerate(improvement_suggestions)
        )
    else:
        feedback_block = feedback

    # Safety fallback: if both improvement_suggestions and feedback are empty
    # (e.g. all dimensions ≥ 9 individually but composite just below threshold),
    # give the LLM a concrete direction rather than leaving the section blank.
    if not feedback_block:
        feedback_block = (
            "All six evaluation dimensions scored 9.0 or above individually, "
            "but the composite score is still below the passing threshold. "
            "Focus on further raising the weakest-scoring dimension — even "
            "small improvements across multiple areas lift the composite. "
            "Prioritise the dimension shown as WEAKEST AREA above."
        )

    return f"""You are a senior technical writer and document improvement engine. \
Your task is to produce a **strictly improved version** of the draft below, \
using reviewer feedback and rubric scores to increase the composite score.

CRITICAL MANDATE: The revised document MUST score higher than the previous composite score.
Do NOT simply rephrase — make substantive, meaningful improvements to every weak section.
{urgency}
{score_block}
---

CURRENT FEEDBACK TO ADDRESS:
{feedback_block}
{prior_block}
---

PREVIOUS DRAFT (to improve upon):
{draft_content}

---

{fact_sheet_block}

TONE: {tone}
{tone_instruction}

MAX LENGTH: {max_draft_length} characters

---

STRICT IMPROVEMENT RULES:
{facts_rules}
2. Address ALL feedback points in CURRENT FEEDBACK TO ADDRESS above.
   Also ensure you have not regressed any issue from PREVIOUS ITERATIONS' FEEDBACK.
{structure_rule}
4. Tone instruction above is binding for every sentence you write.
5. Maximum output length: {max_draft_length} characters.
6. PRESERVE all content in sections that already score well. Only enhance weak sections.

FORMATTING & READABILITY (publication-ready output required):
7. Use consistent, hierarchical headings throughout:
   - H1 (#) for top-level sections.
   - H2 (##) and H3 (###) for subsections and supporting detail.
   Every section must open with a descriptive heading.
8. Break long paragraphs into short, focused blocks (3–5 sentences maximum).
   Add a blank line between every paragraph and between list items.
9. Present technical information using structured elements — NEVER dense prose:
   - Bullet lists for features, capabilities, or options.
   - Numbered lists for sequential steps or ranked priorities.
   - Markdown tables for comparisons, specifications, or multi-attribute metrics.
   - Fenced code blocks (```) for commands, configuration snippets, or code examples.
10. Highlight key insights: open or close each major section with a 1–2 sentence
    bold **Key Takeaway** or **Summary** callout that captures the section's core message.
11. Sentence clarity is non-negotiable: every sentence must be ≤30 words.
    If a sentence exceeds 30 words, split it into two.
    Begin each paragraph with a strong, active-voice topic sentence.
12. Technical depth must not compromise clarity: when adding metrics, examples, or
    specifications, always use bullets, numbered lists, or labelled sub-sections.

MANDATE:
Produce a **polished, factually accurate, content-rich, and professionally formatted** draft.
Do NOT include any explanations, commentary, or code fences wrapping the entire document.
Begin directly with the first section heading of the original draft.

{closing}"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_quality_trend(history: list[dict]) -> str:
    """Return a human-readable quality trend string based on iteration history.

    Returns one of:
        "N/A"       — Only one iteration (no trend to compute).
        "IMPROVING" — Final composite score > first composite score by > 0.1.
        "DECLINING" — Final composite score < first composite score by > 0.1.
        "STABLE"    — Score changed by <= 0.1 across all iterations.
    """
    if len(history) < 2:
        return "N/A"
    first = history[0]["score"]
    last = history[-1]["score"]
    delta = last - first
    if delta > 0.1:
        return "IMPROVING"
    if delta < -0.1:
        return "DECLINING"
    return "STABLE"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate_draft(
    db: Session,
    draft_id: str,
    fact_sheet_data: dict,
    qa_model: str = "claude-sonnet-4-6",
    timeout_seconds: float = 120.0,
) -> RubricScores:
    """
    Evaluate a draft using the LLM rubric and persist the scores in-memory.

    Workflow:
      1. Fetch the DraftVersion — NotFoundError if missing.
      2. Call _call_llm_evaluate (no DB mutations yet; fails fast on LLM error).
      3. Parse response into RubricScores — InvalidRubricScoreError on malformed output.
      4. Update DraftVersion.score and .feedback_text in the session (no commit).

    Note: This function does NOT commit. The caller controls the transaction boundary.

    Args:
        db:              Active SQLAlchemy session.
        draft_id:        UUID string of the DraftVersion to evaluate.
        fact_sheet_data: Structured FactSheet dict used as rubric ground truth.
        qa_model:        Anthropic model ID for QA evaluation (from DB settings).

    Returns:
        Validated RubricScores instance.

    Raises:
        NotFoundError:          draft_id does not exist in the database.
        InvalidRubricScoreError: LLM returned malformed, missing, or out-of-range scores.
        Exception:               LLM call failure — no DB mutations have occurred.
    """
    draft = db.query(DraftVersion).filter(DraftVersion.id == draft_id).first()
    if draft is None:
        raise NotFoundError(f"DraftVersion {draft_id} not found")

    active = settings_service.get_settings(db)

    # ── Call LLM (no DB mutations yet — fails fast) ────────────────────────
    try:
        raw_scores = _call_llm_evaluate(draft.content_markdown, fact_sheet_data, qa_model, active, timeout_seconds)
    except Exception as exc:
        logger.error("LLM evaluation failed: draft_id=%s error=%s", draft_id, exc)
        raise

    # ── Validate and parse scores ──────────────────────────────────────────
    # RubricScores enforces ge=0.0 / le=10.0 on all six dimension scores.
    # Override the LLM's composite_score with our own arithmetic to eliminate
    # any rounding or calculation drift from the LLM's output.
    # composite_score = mean of all SIX rubric dimensions.
    try:
        fc = float(raw_scores.get("factual_correctness", 0))
        td = float(raw_scores.get("technical_depth", 0))
        cl = float(raw_scores.get("clarity", 0))
        rd = float(raw_scores.get("readability", 0))
        fm = float(raw_scores.get("formatting", 0))
        sa = float(raw_scores.get("style_adherence", 0))
        raw_scores["composite_score"] = round((fc + td + cl + rd + fm + sa) / 6, 4)
    except (TypeError, ValueError):
        pass  # Let RubricScores validation catch the malformed data below

    try:
        scores = RubricScores(**raw_scores)
    except (ValidationError, TypeError) as exc:
        raise InvalidRubricScoreError(
            f"LLM returned invalid rubric scores for draft {draft_id}: {exc}"
        ) from exc

    # ── Persist scores in-memory (caller commits) ──────────────────────────
    draft.score = scores.composite_score
    draft.feedback_text = scores.feedback

    logger.info(
        "Draft evaluated: draft_id=%s factual=%.1f depth=%.1f clarity=%.1f "
        "readability=%.1f formatting=%.1f style=%.1f composite=%.2f",
        draft_id,
        scores.factual_correctness,
        scores.technical_depth,
        scores.clarity,
        scores.readability,
        scores.formatting,
        scores.style_adherence,
        scores.composite_score,
    )
    return scores


def improve_draft(
    db: Session,
    draft_id: str,
    feedback: str,
    fact_sheet_data: dict,
    tone: str,
    qa_model: str = "claude-sonnet-4-6",
    max_draft_length: int = 50_000,
    timeout_seconds: float = 120.0,
    previous_scores: Optional[dict] = None,
    cumulative_feedback: Optional[list] = None,
    improvement_suggestions: Optional[list] = None,
    iteration_number: int = 1,
    effective_max: int = 3,
    document_type: str = "whitepaper",
) -> DraftVersion:
    """
    Generate an improved DraftVersion based on rubric feedback.

    Workflow:
      1. Fetch the current DraftVersion — NotFoundError if missing.
      2. Build an improvement prompt incorporating feedback, score context, and history.
      3. Call _call_llm_improve (no DB mutations yet; fails fast on LLM error).
      4. Enforce max_draft_length (truncate if needed).
      5. Create a new DraftVersion with iteration_number + 1 and add to session (no commit).

    Note: This function does NOT commit. The caller controls the transaction boundary.

    Args:
        db:               Active SQLAlchemy session.
        draft_id:         UUID string of the DraftVersion to improve upon.
        feedback:         Actionable feedback text from the preceding rubric evaluation.
        fact_sheet_data:  Structured FactSheet dict used as ground truth.
        tone:             Prose tone for the improved draft (formal/conversational/technical).
        qa_model:         Anthropic model ID (from DB settings).
        max_draft_length: Maximum draft character length (from DB settings).
        previous_scores:  Dict with factual_correctness, technical_depth, clarity,
                          readability, formatting, style_adherence, and composite_score
                          from the current draft's evaluation — used to guide the LLM
                          toward the weakest areas and away from regressing strong ones.
        cumulative_feedback: All feedback strings from iteration 1 through the current
                          iteration (inclusive), ordered chronologically. Used to
                          prevent improvements from undoing previously fixed issues.
        iteration_number: The iteration that just failed (1-based).
        effective_max:    Total allowed iterations, conveyed to the LLM for urgency.
        document_type:    Document type (whitepaper, blog, technical_doc, etc.) passed
                          to the improvement prompt to enforce correct section structure.

    Returns:
        The newly created (uncommitted) DraftVersion ORM instance.

    Raises:
        NotFoundError: draft_id does not exist in the database.
        Exception:     LLM call failure — no new DraftVersion is added to the session.
    """
    old_draft = db.query(DraftVersion).filter(DraftVersion.id == draft_id).first()
    if old_draft is None:
        raise NotFoundError(f"DraftVersion {draft_id} not found")

    active = settings_service.get_settings(db)

    prompt = _build_improvement_prompt(
        old_draft.content_markdown,
        feedback,
        fact_sheet_data,
        tone,
        max_draft_length,
        previous_scores=previous_scores,
        cumulative_feedback=cumulative_feedback,
        improvement_suggestions=improvement_suggestions,
        iteration_number=iteration_number,
        effective_max=effective_max,
        document_type=document_type,
    )

    # ── Call LLM (no DB mutations yet — fails fast) ────────────────────────
    try:
        new_content = _call_llm_improve(prompt, qa_model, active, timeout_seconds)
    except Exception as exc:
        logger.error("LLM improvement failed: draft_id=%s error=%s", draft_id, exc)
        raise

    if len(new_content) > max_draft_length:
        new_content = new_content[:max_draft_length]
        logger.warning(
            "Improved draft truncated to max_draft_length=%d: draft_id=%s",
            max_draft_length,
            draft_id,
        )

    new_draft = DraftVersion(
        document_id=old_draft.document_id,
        iteration_number=old_draft.iteration_number + 1,
        content_markdown=new_content,
        tone=tone,
        score=None,
        feedback_text=None,
        user_prompt="",           # Improved drafts are LLM-generated; no user prompt
        source_document_id=old_draft.source_document_id,
    )
    db.add(new_draft)

    logger.info(
        "Improved draft staged: document_id=%s new_iteration=%d based_on_draft=%s",
        old_draft.document_id,
        new_draft.iteration_number,
        draft_id,
    )
    return new_draft


def evaluate_and_iterate(
    db: Session,
    document_id: str,
    max_iterations: Optional[int] = None,
    document_type: str = "whitepaper",
) -> dict:
    """
    Main QA controller: evaluate → improve → repeat until PASSED or BLOCKED.

    Workflow:
      1. Fetch active settings from DB (cached, 60 s TTL).
      2. Validate max_iterations (>= 1 if provided); resolve effective limit.
      3. Fetch Document — NotFoundError if missing.
      4. Fetch latest FactSheet — optional; uses empty dict when absent (prompt-first support).
      5. Fetch latest DraftVersion — NotFoundError if none.
      6. For each iteration up to effective_max:
         a. Call evaluate_draft → updates draft.score and feedback_text in session.
         b. Append iteration record and write AuditLog (in session).
         c. Score >= qa_passing_threshold → set PASSED, commit atomically, return dict.
         d. iteration == effective_max → set BLOCKED, commit atomically,
            raise MaxIterationsReachedError.
         e. Otherwise → call improve_draft → new DraftVersion in session,
            commit atomically, advance current_draft.
      7. On any exception other than MaxIterationsReachedError →
         rollback all pending session mutations and re-raise.

    Transaction model:
      Each iteration is ONE atomic commit: score update + audit log + (new draft or status).
      A rollback clears all in-session mutations for the current iteration.

    Args:
        db:             Active SQLAlchemy session.
        document_id:    UUID string of the Document to process.
        max_iterations: Override the configured default. Must be >= 1 if provided.
                        Uses settings.max_qa_iterations when None.
        document_type:  Document type (whitepaper, blog, technical_doc, case_study,
                        product_brief, research_report). Passed to improve_draft()
                        so the Reviewer LLM enforces the correct section structure
                        when generating improved drafts.

    Returns:
        dict with keys: document_id, final_status, iterations_completed,
                        final_score, final_draft_id, iteration_history,
                        quality_trend.

    Raises:
        ValueError:                 max_iterations < 1.
        NotFoundError:              Document or latest DraftVersion not found.
        MaxIterationsReachedError:  Draft did not pass within the iteration limit.
        InvalidRubricScoreError:    LLM returned invalid rubric scores.
        Exception:                  Any LLM or DB failure — transaction is rolled back.
    """
    # ── 1. Fetch active settings ───────────────────────────────────────────
    active = settings_service.get_settings(db)
    qa_model = active.qa_llm_model
    qa_threshold = active.qa_passing_threshold
    max_length = active.max_draft_length
    timeout_seconds = float(active.llm_timeout_seconds)

    # ── 2. Validate max_iterations ────────────────────────────────────────
    if max_iterations is not None and max_iterations < 1:
        raise ValueError("max_iterations must be >= 1 if provided")

    effective_max = max_iterations if max_iterations is not None else active.max_qa_iterations

    logger.info(
        "evaluate_and_iterate: document_id=%s effective_max=%d qa_model=%s qa_threshold=%.1f",
        document_id,
        effective_max,
        qa_model,
        qa_threshold,
    )

    # ── 3. Fetch Document ─────────────────────────────────────────────────
    # NOTE: In production with PostgreSQL, add .with_for_update() here to prevent
    # concurrent QA runs from racing on the same document status update.
    doc = db.query(Document).filter(Document.id == document_id).first()
    if doc is None:
        raise NotFoundError(f"Document {document_id} not found")

    # ── 4. Fetch latest FactSheet (optional — prompt-only drafts may have none) ──
    fact_sheet = (
        db.query(FactSheet)
        .filter(FactSheet.document_id == document_id)
        .order_by(FactSheet.created_at.desc())
        .first()
    )
    fact_sheet_data = fact_sheet.structured_data if fact_sheet is not None else {}

    # ── 5. Fetch latest DraftVersion ──────────────────────────────────────
    current_draft = (
        db.query(DraftVersion)
        .filter(DraftVersion.document_id == document_id)
        .order_by(DraftVersion.iteration_number.desc())
        .first()
    )
    if current_draft is None:
        raise NotFoundError(
            f"Document {document_id} has no draft versions. "
            "Run POST /generate-draft before running QA."
        )

    iteration_history: list[dict] = []
    iterations_completed: int = 0
    final_score: Optional[float] = None
    final_draft_id: str = current_draft.id
    # Track scores and feedback across iterations for progressive improvement
    previous_scores: Optional[dict] = None
    cumulative_feedback: list[str] = []

    # ── 6. QA Iteration Loop ──────────────────────────────────────────────
    for iteration in range(1, effective_max + 1):
        logger.info(
            "QA iteration %d/%d: document_id=%s draft_id=%s",
            iteration,
            effective_max,
            document_id,
            current_draft.id,
        )

        try:
            # ── Evaluate (LLM call first — no DB mutations until it succeeds) ──
            scores = evaluate_draft(db, current_draft.id, fact_sheet_data, qa_model, timeout_seconds)

            final_score = scores.composite_score
            final_draft_id = current_draft.id
            iterations_completed = iteration
            passed = scores.composite_score >= qa_threshold

            # Calculate score delta vs previous iteration (None on first pass)
            score_delta: Optional[float] = None
            if previous_scores is not None:
                score_delta = round(scores.composite_score - previous_scores["composite_score"], 4)

            # Capture current scores for use in the improvement prompt
            current_scores = {
                "factual_correctness": scores.factual_correctness,
                "technical_depth":     scores.technical_depth,
                "clarity":             scores.clarity,
                "readability":         scores.readability,
                "formatting":          scores.formatting,
                "style_adherence":     scores.style_adherence,
                "composite_score":     scores.composite_score,
            }

            # Accumulate feedback so each improvement sees the full history
            cumulative_feedback.append(scores.feedback)

            iteration_history.append(
                {
                    "iteration":            iteration,
                    "draft_id":             current_draft.id,
                    "factual_correctness":  scores.factual_correctness,
                    "technical_depth":      scores.technical_depth,
                    "clarity":              scores.clarity,
                    "readability":          scores.readability,
                    "formatting":           scores.formatting,
                    "style_adherence":      scores.style_adherence,
                    "score":                scores.composite_score,
                    "score_delta":          score_delta,
                    "feedback":             scores.feedback,
                    "improvement_suggestions": scores.improvement_suggestions,
                    "passed":               passed,
                }
            )

            # ── Audit log for this iteration (in-session, committed below) ──
            delta_str = f" delta={score_delta:+.2f}" if score_delta is not None else ""
            audit_action = (
                f"QA iteration {iteration}/{effective_max}: "
                f"score={scores.composite_score:.2f}{delta_str} "
                f"factual={scores.factual_correctness:.1f} "
                f"depth={scores.technical_depth:.1f} "
                f"clarity={scores.clarity:.1f} "
                f"readability={scores.readability:.1f} "
                f"formatting={scores.formatting:.1f} "
                f"style={scores.style_adherence:.1f} "
                f"draft_id={current_draft.id} "
                f"passed={passed}"
            )
            db.add(AuditLog(document_id=document_id, action=audit_action[:512]))

            # ── PASSED ─────────────────────────────────────────────────────
            if passed:
                doc.status = DocumentStatus.PASSED
                doc.current_stage = "QA_COMPLETED"
                doc.validation_progress = 50
                db.commit()
                db.refresh(current_draft)
                logger.info(
                    "QA PASSED: document_id=%s score=%.2f iterations=%d",
                    document_id,
                    scores.composite_score,
                    iterations_completed,
                )

                # ── Auto-pipeline: claim validation → governance → HUMAN_REVIEW ──
                # After QA passes, automatically run the remaining governance
                # pipeline so documents flow to HUMAN_REVIEW without manual steps.
                final_status = DocumentStatus.PASSED
                try:
                    from app.services import claim_validation_service, governance_service  # noqa: PLC0415

                    logger.info(
                        "Auto-pipeline: running claim validation for document_id=%s",
                        document_id,
                    )
                    validation_report = claim_validation_service.validate_draft_claims(
                        db, document_id
                    )

                    if validation_report.is_valid:
                        # Update progress to reflect claim validation passed
                        doc_mid = db.query(Document).filter(
                            Document.id == document_id
                        ).first()
                        if doc_mid:
                            doc_mid.validation_progress = 75
                            db.commit()

                        logger.info(
                            "Auto-pipeline: claims valid, running governance check "
                            "for document_id=%s",
                            document_id,
                        )
                        governance_result = governance_service.enforce_governance(
                            db, document_id
                        )
                        final_status = governance_result.final_status
                        if final_status == DocumentStatus.HUMAN_REVIEW:
                            doc_final = db.query(Document).filter(
                                Document.id == document_id
                            ).first()
                            if doc_final:
                                doc_final.validation_progress = 90
                                db.commit()
                        logger.info(
                            "Auto-pipeline complete: document_id=%s final_status=%s",
                            document_id,
                            final_status.value,
                        )
                    else:
                        final_status = DocumentStatus.BLOCKED
                        logger.info(
                            "Auto-pipeline: claims invalid — document_id=%s blocked",
                            document_id,
                        )
                except Exception as auto_exc:
                    # Auto-pipeline failure must not mask the QA success result.
                    # The document stays at PASSED; operators can manually trigger
                    # validate-claims and governance-check.
                    logger.warning(
                        "Auto-pipeline failed (document remains at PASSED): "
                        "document_id=%s error=%s",
                        document_id,
                        auto_exc,
                    )

                return {
                    "document_id": document_id,
                    "final_status": final_status,
                    "iterations_completed": iterations_completed,
                    "final_score": final_score,
                    "final_draft_id": final_draft_id,
                    "iteration_history": iteration_history,
                    "quality_trend": _compute_quality_trend(iteration_history),
                }

            # ── BLOCKED — max iterations reached ───────────────────────────
            # Check BEFORE calling improve_draft so no wasted LLM call is made
            # on the final iteration. Score and audit log are committed here.
            if iteration >= effective_max:
                doc.status = DocumentStatus.BLOCKED
                db.commit()
                logger.info(
                    "QA BLOCKED: document_id=%s score=%.2f after %d/%d iterations",
                    document_id,
                    scores.composite_score,
                    iterations_completed,
                    effective_max,
                )
                raise MaxIterationsReachedError(
                    f"Document {document_id} did not pass QA after {effective_max} "
                    f"iteration(s). Final score: {scores.composite_score:.2f} "
                    f"(threshold: {qa_threshold})."
                )

            # ── Update pipeline progress for this intermediate iteration ────
            # Interpolate validation_progress between 25 (draft generated) and
            # 50 (QA completed) so the UI progress bar advances each iteration.
            doc.current_stage = f"QA_ITERATION_{iteration}"
            doc.validation_progress = int(25 + (iteration / effective_max) * 25)

            # ── Improve (only when more iterations remain) ──────────────────
            new_draft = improve_draft(
                db,
                current_draft.id,
                scores.feedback,
                fact_sheet_data,
                tone=current_draft.tone,
                qa_model=qa_model,
                max_draft_length=max_length,
                timeout_seconds=timeout_seconds,
                previous_scores=current_scores,
                cumulative_feedback=cumulative_feedback,
                improvement_suggestions=scores.improvement_suggestions,
                iteration_number=iteration,
                effective_max=effective_max,
                document_type=document_type,
            )
            db.commit()
            db.refresh(new_draft)

            # Advance tracking for next iteration
            previous_scores = current_scores
            current_draft = new_draft

        except MaxIterationsReachedError:
            # Status already committed as BLOCKED — propagate without rollback.
            raise
        except Exception as exc:
            # LLM failures, DB errors, InvalidRubricScoreError, NotFoundError, etc.
            # Roll back all in-session mutations for this iteration and re-raise.
            db.rollback()
            logger.error(
                "QA iteration %d failed: document_id=%s error=%s",
                iteration,
                document_id,
                exc,
            )
            raise

    # The loop always returns or raises — this line is unreachable.
    raise RuntimeError(  # pragma: no cover
        f"Unexpected state in evaluate_and_iterate for document {document_id}"
    )
