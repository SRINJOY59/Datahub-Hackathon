"""Prompt templates for the agent's LLM-reasoning steps.

The RCA prompt is evidence-first: the model reasons over grounded probe findings
and prior-incident precedent, and must not invent facts beyond them. Output is a
structured JSON object (see agent.schemas.RCAResult), so it stays robust on
complex, multi-hop cases and chatty/reasoning models.
"""

RCA_SYSTEM = (
    "You are Sentinel, an autonomous on-call ML engineer doing root-cause "
    "analysis. Base the root cause on the GROUNDED EVIDENCE for THIS incident; "
    "do not invent data. Past incidents are context only — cite one only if it "
    "matches the current evidence, otherwise ignore it. Prefer the deepest "
    "upstream cause over a downstream symptom."
)

RCA_PROMPT = """\
INCIDENT:
{incident}

LINEAGE & GOVERNANCE CONTEXT:
{context}

GROUNDED EVIDENCE (from data profiling + lineage probes):
{evidence}

SIMILAR PAST INCIDENTS (institutional memory):
{precedent}

Produce the root cause (name the upstream asset/column and the change, citing
the evidence), the change_type, your confidence, and the single reversible
mitigation to take first.
"""
