"""Prompt for synthesising a runbook from resolved incidents.

The model is summarising evidence, not inventing procedure: everything it writes
has to be traceable to something that actually happened and actually worked. A
runbook that recommends a step nobody has ever taken here is worse than no
runbook, because it will be followed.
"""

RUNBOOK_SYSTEM = (
    "You are Sentinel, writing an on-call runbook from incidents that have "
    "already been resolved. Generalise only from what the incidents show: every "
    "diagnosis step and mitigation must be grounded in what actually worked. Do "
    "not invent tools, commands or steps that do not appear in the history. Be "
    "concise and imperative — this is read at 3am."
)

RUNBOOK_PROMPT = """\
INCIDENT CLASS: {change_type}
RESOLVED INCIDENTS ON RECORD: {count}

{incidents}

Write the runbook an on-call engineer should follow the next time this class of
incident occurs. Cover how to recognise it, how to confirm the diagnosis, the
mitigation that has actually worked here, and how to verify the pipeline is
healthy again.
"""
