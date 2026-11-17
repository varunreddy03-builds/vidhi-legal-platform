"""Strategy, reasoning and behaviour analyses (Phases 5-7). AI-assisted, source-grounded and screened in code; see lib/analysis.py."""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from lib import analysis, evidence_class, knowledge, legal_reasoning
from lib.jurisdictions import REGISTRY as JURISDICTIONS, is_live
from lib.library import find_relevant
from lib.query_lang import english_query
from lib.ai import ai_failure, ask_json, log_ai_failure
from lib.auth import audit, require_intelligence
from lib.plans import gate_ai, refund_ai
from lib.ratelimit import AI_LIMIT
from lib.safety import fence

logger = logging.getLogger("vidhi.analysis")
router = APIRouter(tags=["analysis"])


class ClassifyIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


@router.get("/evidence/framework")
async def evidence_framework(user: dict = Depends(require_intelligence)):
    return evidence_class.framework()


@router.post("/evidence/classify")
async def evidence_classify(body: ClassifyIn, user: dict = Depends(require_intelligence)):
    """Code-only screen for unsupported audio / brain-frequency claims. No AI, nothing stored."""
    found = evidence_class.classify(body.text)
    return {"findings": found, "classes": evidence_class.CLASSES, "limits": evidence_class.LIMITS,
            "note": "Nothing was flagged by these rules. That does not make the text true." if not found else None}


class LegalIn(BaseModel):
    question: str = Field(min_length=10, max_length=4000)
    facts: str = Field(default="", max_length=6000)
    jurisdiction: str = Field(default="IN", max_length=4)


async def _after_charge(user: dict, label: str, work):
    """Everything that happens after the daily request was charged runs here. If anything fails (the model, a search, a reply of an unexpected shape), the request is given
    back and the person sees the normal 'AI busy' message instead of a crash that would also have cost them one of their requests."""
    try:
        return await work()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        log_ai_failure(label.lower(), exc)
        await audit(user, label, result="FAILED")
        await refund_ai(user)
        raise ai_failure(exc) from exc


@router.post("/legal-reasoning", dependencies=[Depends(AI_LIMIT)])
async def run_legal_reasoning(body: LegalIn, user: dict = Depends(require_intelligence)):
    """Structured legal reasoning. Law can come only from the verified library; see lib/legal_reasoning.py."""
    code = body.jurisdiction.strip().upper()
    if not is_live(code):
        name = JURISDICTIONS[code].name if code in JURISDICTIONS else body.jurisdiction
        raise HTTPException(status_code=422, detail=f"VIDHI does not cover the law of {name} yet. Only live jurisdictions can be analysed.")
    tier = await gate_ai(user, "analysis")

    async def work():
        entries = [e for e in await find_relevant(await english_query(body.question, f"query-{user['id']}")) if e.get("jurisdiction", "IN") == code]
        prompt = legal_reasoning.build_prompt(body.question, body.facts, code, entries, fence)
        data = await ask_json(f"legal-{user['id']}", prompt, legal_reasoning.SCHEMA, system=legal_reasoning.SYSTEM, purpose="research", tier=tier)
        if not isinstance(data, dict) or not str(data.get("issue") or "").strip():
            raise RuntimeError("the model's reply had no issue")
        result = legal_reasoning.finish(data, entries, code)
        await audit(user, "LEGAL_REASONING", result="OK")
        return result

    return await _after_charge(user, "LEGAL_REASONING", work)


class AnalysisIn(BaseModel):
    question: str = Field(min_length=10, max_length=4000)
    context: str = Field(default="", max_length=6000)


@router.post("/analysis/{kind}", dependencies=[Depends(AI_LIMIT)])
async def run_analysis(kind: Literal["strategy", "reasoning", "behaviour", "philosophy"], body: AnalysisIn, user: dict = Depends(require_intelligence)):
    tier = await gate_ai(user, "analysis")

    async def work():
        hits = (await knowledge.search(body.question, user["organization_id"], k=6))["hits"]
        prompt = analysis.build_prompt(kind, body.question, body.context, hits, fence)
        data = await ask_json(f"analysis-{user['id']}", prompt, analysis.schema_for(kind), system=analysis.SYSTEM, purpose="research", tier=tier)
        usable = isinstance(data, dict) and (bool(data.get("viewpoints")) if kind == "philosophy" else bool(str(data.get("summary") or "").strip()))
        if not usable:
            raise RuntimeError("the model's reply was empty")
        result = {"kind": kind, **analysis.finish(data, hits, body.question + "\n" + body.context, kind)}
        await audit(user, "ANALYSIS", result=kind.upper())
        return result

    return await _after_charge(user, "ANALYSIS", work)
