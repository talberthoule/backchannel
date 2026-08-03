# Seeds the fictional demo workspace used for marketing and docs screenshots.
#
# Usage:  python showcase/seed_demo.py            (app running at localhost:3000)
#         python showcase/seed_demo.py --reset    (delete existing demo data first)
#
# Every company, person, figure, and quote below is invented. No real customer,
# employer, or individual appears anywhere in this file, and none should ever be
# added: these rows become public screenshots. See the Curation rules in
# showcase/screenshots/README.md before changing anything here.
#
# Sessions, groups, speakers, transcripts, offerings, and knowledge records go
# through real APIs. Insights and the deterministic briefing use SQL because
# neither has a fixture-oriented write endpoint.
import argparse
import json
import subprocess
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = "http://localhost:3000/api"
REPO = Path(__file__).resolve().parent.parent
GROUP = "Alderwake Health Network"
MAIN = "Alderwake Health Network - recovery readiness review"


def call(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        body = response.read().decode()
        return json.loads(body) if body.strip() else None


def env(key):
    for line in (REPO / ".env").read_text(encoding="utf8").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    raise SystemExit(f"{key} not found in .env")


def psql(sql):
    cmd = [
        "docker",
        "compose",
        "exec",
        "-T",
        "db",
        "psql",
        "-U",
        env("POSTGRES_USER"),
        "-d",
        env("POSTGRES_DB"),
    ]
    result = subprocess.run(cmd, input=sql, capture_output=True, text=True, cwd=REPO)
    if result.returncode != 0:
        raise SystemExit(f"psql failed:\n{result.stderr}")
    return result.stdout


def q(value):
    return "'" + value.replace("'", "''") + "'"


SPEAKERS = [
    ("Me", "Account Lead", "#0d9488", True, "team"),
    ("Leah", "Solutions Architect", "#7c3aed", False, "team"),
    ("Owen", "Director of Infrastructure", "#f59e0b", False, "external"),
    ("Maya", "Security and Resilience Lead", "#10b981", False, "external"),
]

LINES = [
    ("Owen", "Thanks for joining from home today. Before we start, is everyone comfortable with me recording so the recovery commitments are captured accurately?"),
    ("Me", "Yes. I will also send a written decision log after the call so nobody has to rely on the recording."),
    ("Maya", "Good. The board risk committee meets September 18, and our cyber insurer wants evidence of a tested recovery plan by September 30."),
    ("Me", "What did the latest exercise show, and which result is driving the urgency?"),
    ("Owen", "The electronic health record interface tier took eight hours to recover. Our stated objective is two hours, so the gap is six."),
    ("Leah", "Was the delay data restore, application sequencing, identity, or validation by the clinical owners?"),
    ("Owen", "All four, but sequencing was the largest problem. The runbook assumed three people were in the data center, and two of them now work remotely."),
    ("Maya", "Identity was second. The recovery vault worked, but nobody had confirmed who could authorize the emergency accounts."),
    ("Me", "So success is not just a faster restore. It is a remote-ready operating model with named authority and evidence the board and insurer can use."),
    ("Maya", "Exactly. I need something defensible, not a polished diagram."),
    ("Leah", "Which services are tier zero for the pilot? We should keep the first proof narrow enough to finish before September."),
    ("Owen", "Identity, the interface engine, and the medication reconciliation feed. If those are down, the hospitals fall back to manual work."),
    ("Maya", "I need to be explicit: there can be no production failover during the pilot. Clinical operations will not approve that risk in August."),
    ("Leah", "We do not need a production failover. We can restore into an isolated recovery network, replay synthetic transactions, and have clinical owners validate the sequence there."),
    ("Owen", "That removes my biggest objection. A test that touches production would stop this immediately."),
    ("Me", "Would an isolated pilot covering identity plus the interface tier give the board enough evidence if the clinical validation is documented?"),
    ("Maya", "Yes, provided the evidence includes timings, owners, exceptions, and the next remediation decision."),
    ("Owen", "The other issue is capacity. My infrastructure team has seven people, five are remote, and they are already carrying the data center exit."),
    ("Me", "Should we price managed recovery operations separately so the project decision is not blocked by a long-term staffing decision?"),
    ("Owen", "Yes. I can fund a pilot from resilience, but ongoing operations would come from a different cost center."),
    ("Maya", "I would evaluate a managed option if our team keeps approval authority and the evidence stays in our tenant."),
    ("Leah", "That is workable. The service can maintain runbooks, schedule validation, and coordinate tests while Alderwake owns the recovery declaration."),
    ("Owen", "Procurement may be awkward. You are not yet an approved services supplier, although we can buy the recovery software through our existing reseller agreement."),
    ("Me", "Is there a professional-services threshold that allows a time-boxed pilot while the full supplier review runs?"),
    ("Owen", "Under ninety thousand dollars, with a written single-source justification. Above that requires a competitive event."),
    ("Me", "Then we will keep the pilot below ninety, show software and services separately, and treat managed operations as an optional follow-on."),
    ("Maya", "Please do not make the proposal look cheaper by moving required work into the optional line. The insurer will notice gaps."),
    ("Me", "Agreed. The pilot will be complete on its own; the optional line is only the recurring operating model."),
    ("Leah", "What recovery tooling is already licensed? Reusing it is safer than adding a platform during a deadline."),
    ("Owen", "Veeam Data Platform for the core workloads and Microsoft Entra for identity. Both are current, but the orchestration is mostly manual."),
    ("Leah", "Good. This is an integration and runbook problem, not a product replacement. We can use the licenses you already own."),
    ("Maya", "Where will the synthetic transaction data come from? Legal will reject a test dataset copied from production."),
    ("Leah", "We will generate a minimal fictional dataset and keep it inside the isolated recovery network. No patient or employee records are needed."),
    ("Maya", "Put that in the scope as a hard guardrail."),
    ("Me", "Noted: synthetic data only, isolated network, no production failover, and Alderwake retains approval authority."),
    ("Owen", "What does the timeline look like if the scope is approved next Thursday?"),
    ("Leah", "Week one for discovery and access validation, week two for runbook design, week three for the isolated restore, and week four for clinical validation and the evidence pack."),
    ("Maya", "Our change advisory board needs ten working days even for isolated tests because identity is involved."),
    ("Me", "Then the change request opens on day one, in parallel with discovery, and we reserve a second validation window as contingency."),
    ("Owen", "That puts the evidence pack in the first week of September, which leaves time before the board meeting."),
    ("Maya", "Who owns the exception list if the two-hour objective is still missed?"),
    ("Leah", "We will draft it with severity, decision owner, and due date. Owen owns infrastructure exceptions; you own risk acceptance; we own remediation recommendations."),
    ("Owen", "That split works, but the clinical application owners must sign the validation result."),
    ("Me", "Who can confirm those owners and secure their test window?"),
    ("Owen", "I can send the names tomorrow. Dr. Vale owns the interface workflow, but use the role in the public plan, not the person's name."),
    ("Maya", "Thank you. Keep named individuals out of the insurer pack unless they have approved it."),
    ("Me", "We will use accountable roles in every external artifact and keep personal details in Alderwake's internal RACI only."),
    ("Owen", "Commercially, what range should I reserve?"),
    ("Me", "The fixed pilot should land between seventy-two and eighty-four thousand dollars, including the evidence pack and one contingency validation window."),
    ("Owen", "That is within the resilience allocation and below the procurement threshold."),
    ("Maya", "I still need data residency and support-access language before I endorse the managed option."),
    ("Me", "We will include a one-page operating boundary: evidence remains in your tenant, access is time-bound, and Alderwake approves every recovery declaration."),
    ("Leah", "I also want a ninety-minute technical working session with the identity and interface owners before we lock the runbook."),
    ("Owen", "Tuesday at two Central works for the infrastructure side. I will confirm the clinical owner."),
    ("Me", "I will send the fixed pilot scope, separate managed-operations option, and operating boundary by Thursday noon."),
    ("Maya", "Add the board-ready evidence outline. If I can see the final shape now, I can clear it with the insurer before the test."),
    ("Me", "Included. Owen sends the owner list tomorrow, we hold Tuesday at two, and I deliver the full package Thursday noon."),
    ("Owen", "That is clear. If the scope holds those guardrails, I can sponsor it."),
]

# item_type, agent_source, question, rationale, context, speaker, starred,
# answered, answer_summary, needs_followup, followup, offering_match, enhanced
CURATED_INSIGHTS = [
    ("action_item", "action_tracker", "Send the fixed recovery pilot scope by Thursday noon", "Owen can sponsor the pilot once the stated guardrails and commercial boundary are in writing.", "I will send the fixed pilot scope, separate managed-operations option, and operating boundary by Thursday noon", "Me", False, False, "", False, "", "Recovery Implementation Pilot", True),
    ("action_item", "action_tracker", "Open the identity change request on day one", "The ten-working-day approval clock must run in parallel with discovery to protect the September evidence date.", "the change request opens on day one, in parallel with discovery", "Me", False, False, "", False, "", "", True),
    ("action_item", "action_tracker", "Confirm accountable clinical owners and their validation window", "Clinical sign-off is required for the evidence pack, but the role list is not complete yet.", "I can send the names tomorrow", "Owen", False, False, "", True, "Which accountable role will sign the medication reconciliation validation?", "", False),
    ("action_item", "action_tracker", "Hold the technical working session Tuesday at 2:00 Central", "Identity and interface owners need to validate access and sequence before the runbook is locked.", "Tuesday at two Central works", "Owen", False, False, "", False, "", "", False),
    ("action_item", "action_tracker", "Include a board-ready evidence outline in the proposal", "Maya wants the insurer to clear the evidence shape before the recovery test.", "Add the board-ready evidence outline", "Maya", False, False, "", False, "", "Recovery Readiness Assessment", True),
    ("objection", "objection_handler", "Clinical operations will not allow a production failover during the pilot", "A production-impacting test would stop the project before procurement.", "there can be no production failover during the pilot", "Maya", True, True, "Leah proposed an isolated recovery network with synthetic transactions and clinical validation, which Owen accepted.", False, "", "Recovery Implementation Pilot", True),
    ("objection", "objection_handler", "The infrastructure team cannot absorb another operating platform", "Seven people, five remote, are already committed to the data center exit.", "My infrastructure team has seven people, five are remote", "Owen", False, True, "The pilot stays self-contained and managed recovery operations will be priced separately as an optional operating model.", False, "", "Managed Recovery Operations", True),
    ("objection", "objection_handler", "The services integrator is not yet an approved supplier", "Supplier onboarding could miss the board deadline even though software can use an existing reseller agreement.", "You are not yet an approved services supplier", "Owen", True, True, "Keep the fixed pilot below the ninety-thousand-dollar single-source threshold while the broader supplier review continues.", False, "", "Recovery Implementation Pilot", True),
    ("objection", "objection_handler", "Legal will not allow production data in a recovery test", "Using copied clinical data would invalidate the safe pilot design.", "Legal will reject a test dataset copied from production", "Maya", False, True, "Use a minimal fictional dataset inside the isolated recovery network; no patient or employee records are required.", False, "", "", True),
    ("opportunity", "opportunity_scout", "Recovery Readiness Assessment", "Alderwake needs an evidence-backed gap analysis before committing to broader remediation.", "I need something defensible, not a polished diagram", "Maya", False, False, "", False, "", "Recovery Readiness Assessment", True),
    ("opportunity", "opportunity_specialist", "Recovery Implementation Pilot", "The customer has budget, a deadline, a narrow technical scope, and accepted non-disruptive validation guardrails.", "If the scope holds those guardrails, I can sponsor it", "Owen", False, False, "", False, "", "Recovery Implementation Pilot", True),
    ("opportunity", "opportunity_scout", "Managed Recovery Operations", "Remote staffing and a separate operating budget create a credible managed-services follow-on.", "I would evaluate a managed option", "Maya", False, False, "", True, "Who owns the recurring cost center and when can that owner review the service boundary?", "Managed Recovery Operations", True),
    ("opportunity", "opportunity_specialist", "Quarterly recovery validation program", "The board and insurer need repeatable evidence, not a one-time restore result.", "schedule validation, and coordinate tests", "Leah", False, False, "", True, "What evidence cadence will the insurer accept after September?", "Managed Recovery Operations", False),
    ("observation", "observer", "The real failure was remote operating readiness, not backup integrity", "The vault restored data, but sequencing and authority assumptions broke when responders were not onsite.", "The recovery vault worked, but nobody had confirmed who could authorize", "Maya", False, False, "", False, "", "", True),
    ("observation", "observer", "The board deadline is earlier than the insurer deadline", "September 18 is the effective compelling event because the risk committee must review evidence first.", "The board risk committee meets September 18", "Maya", False, False, "", False, "", "", True),
    ("observation", "synthesizer", "Existing licenses make this an integration engagement", "Alderwake already owns current recovery and identity platforms, reducing change risk under the deadline.", "This is an integration and runbook problem, not a product replacement", "Leah", False, False, "", False, "", "", True),
    ("observation", "observer", "Pilot funding and ongoing operations have different owners", "Separating the fixed pilot from recurring service avoids turning one approval into two.", "ongoing operations would come from a different cost center", "Owen", False, False, "", False, "", "", False),
    ("observation", "observer", "External evidence must use accountable roles, not personal names", "The customer explicitly limited personally identifying details in board and insurer artifacts.", "use accountable roles in every external artifact", "Me", False, False, "", False, "", "", True),
    ("question", "question_hunter", "Which failure created most of the six-hour recovery gap?", "The answer determines whether the pilot should prioritize tooling, sequencing, identity, or clinical validation.", "What did the latest exercise show", "Me", False, True, "Application sequencing was the largest delay; emergency-account authority was second.", False, "", "", True),
    ("question", "question_hunter", "Which services are tier zero for the pilot?", "A narrow critical-service boundary is required to finish before September.", "Which services are tier zero for the pilot", "Leah", False, True, "Identity, the interface engine, and the medication reconciliation feed.", False, "", "", True),
    ("question", "question_hunter", "Will isolated validation satisfy the board and insurer?", "The pilot only works if evidence from a non-production environment is accepted.", "give the board enough evidence", "Me", False, True, "Yes, if the evidence records timings, owners, exceptions, and the next remediation decision.", False, "", "", True),
    ("question", "question_hunter", "Who approves emergency identity access during a recovery?", "The last exercise exposed an authority gap even though the recovery vault worked.", "nobody had confirmed who could authorize the emergency accounts", "Maya", False, False, "", True, "Which role is primary and who is the after-hours delegate?", "", False),
    ("question", "question_hunter", "Who owns exceptions when the two-hour objective is missed?", "Unowned remediation would weaken both the board decision and insurer evidence.", "Who owns the exception list", "Maya", False, True, "Infrastructure owns technical exceptions, security owns risk acceptance, and the integrator owns remediation recommendations.", False, "", "", True),
    ("question", "question_hunter", "What evidence cadence will be required after September?", "A recurring requirement changes the managed-service scope and operating cost.", "The board and insurer need evidence of a tested recovery plan", "Maya", False, False, "", True, "Will quarterly validation satisfy both governance groups?", "Managed Recovery Operations", False),
]

# Questions asked through the call's command bar (ALP-178). The product stores
# them as `asked` insights: starred on creation so they pin to the top of the
# live feed, answered from the running transcript, with the answering model and
# latency carried in `rationale` exactly as backend/app/routers/ask.py writes
# it. They carry no speaker, because the person asking is the operator.
ASKED_INSIGHTS = [
    ("asked", "live_chat", "What exactly does Maya need in the evidence pack?", "Answered by Gemini 3.6 Flash in 2.3s", "", "", True, True, "Timings, owners, exceptions, and the next remediation decision. She also asked that external artifacts name accountable roles rather than individuals.", False, "", "", False),
    ("asked", "live_chat", "Have we agreed a commercial ceiling for the pilot?", "Answered by Gemini 3.6 Flash in 1.8s", "", "", True, True, "Yes. Owen named a ninety-thousand-dollar single-source threshold, and the fixed pilot is scoped at seventy-two to eighty-four thousand with managed operations priced separately.", False, "", "", False),
]

# Volume filler beyond the curated rows: a dense 46-minute call plausibly
# yields ~123 insights at the agents' 10-40s cadences, and the marketing copy
# quotes that total. Filler rows are seeded with earlier timestamps than every
# curated row, so the cards visible in screenshots stay the hand-written ones;
# filler only raises the per-type counts. Every phrase stays inside the
# fictional Alderwake story (see the Curation rules in screenshots/README.md).
_FILLER_TOPICS = [
    ("identity change approval", "the ten-working-day clock gates the validation window", "Owen"),
    ("interface engine restore order", "dependent applications restore in strict sequence", "Leah"),
    ("medication reconciliation feed", "the accountable clinical role signs the restored feed", "Owen"),
    ("synthetic transaction set", "no patient or employee records enter the test", "Maya"),
    ("evidence pack format", "timings, owners, and exceptions belong in one artifact", "Me"),
    ("emergency account authority", "the after-hours delegate is still unnamed", "Maya"),
    ("runbook sequencing", "the last exercise lost hours to ordering, not data loss", "Leah"),
    ("insurer pre-clearance", "the evidence outline is reviewed before the test runs", "Maya"),
    ("board risk committee date", "September 18 fixes the last defensible evidence date", "Maya"),
    ("procurement threshold", "the fixed pilot stays below single-source review", "Owen"),
    ("remote staffing model", "five of the seven infrastructure engineers are remote", "Owen"),
    ("data residency language", "recovery evidence remains in the customer tenant", "Maya"),
    ("isolated recovery network", "restores never touch production services", "Leah"),
    ("reseller agreement", "software procurement can reuse an existing vehicle", "Owen"),
    ("contingency validation window", "a reserved second window absorbs a failed first run", "Leah"),
    ("exception ownership split", "infrastructure, risk, and remediation have separate owners", "Me"),
    ("quarterly validation cadence", "governance evidence must be repeatable after September", "Maya"),
    ("recovery vault integrity", "the data restore already meets its timing objective", "Owen"),
    ("internal RACI", "personal names stay out of every external artifact", "Me"),
    ("tier-zero service list", "identity, the interface engine, and the reconciliation feed", "Leah"),
]

_FILLER_FRAMES = {
    "question": ("question_hunter", 28, 0, [
        ("What is the current state of the {t}?", "The answer shapes how much pilot time the {t} consumes."),
        ("Who is accountable for the {t} during the pilot?", "Unowned work on the {t} would surface as an exception in the evidence pack."),
        ("Does the {t} change before or after the September test?", "Sequencing the {t} against the board date protects the contingency window."),
        ("What does the insurer expect to see for the {t}?", "Governance reviewers will ask how the {t} was validated."),
    ]),
    "observation": ("observer", 26, 7, [
        ("The {t} shapes the pilot more than the tooling does", "In the fixture story, {d}."),
        ("The {t} was raised without prompting", "Unprompted detail on the {t} signals real internal attention: {d}."),
        ("The team already has a working position on the {t}", "As stated in the call, {d}."),
        ("The {t} connects the pilot to the managed-operations option", "Recurring ownership matters because {d}."),
    ]),
    "action_item": ("action_tracker", 19, 3, [
        ("Document the {t} in the pilot plan", "The written plan must reflect that {d}."),
        ("Review the {t} in the Tuesday working session", "The working session is the agreed forum; {d}."),
        ("Confirm the {t} before the scope freeze", "Thursday's package should state plainly that {d}."),
    ]),
    "objection": ("objection_handler", 12, 11, [
        ("The {t} could slip the September date", "Raised as a delivery concern: {d}."),
        ("The {t} is not yet approved internally", "Approval risk, because {d}."),
        ("The {t} may not satisfy the auditors", "Evidence concern raised in passing: {d}."),
    ]),
    "opportunity": ("opportunity_scout", 14, 15, [
        ("Fold the {t} into the recovery evidence pack", "Packaging the {t} strengthens the board narrative: {d}."),
        ("Extend the pilot to cover the {t}", "A bounded extension is credible because {d}."),
    ]),
}


def _filler_insights():
    rows = []
    for item_type, (source, count, offset, frames) in _FILLER_FRAMES.items():
        for index in range(count):
            topic, detail, who = _FILLER_TOPICS[(offset + index) % len(_FILLER_TOPICS)]
            title_frame, rationale_frame = frames[index % len(frames)]
            rows.append((
                item_type,
                source,
                title_frame.format(t=topic),
                rationale_frame.format(t=topic, d=detail),
                detail,
                who,
                False, False, "", False, "", "",
                index % 2 == 0,
            ))
    return rows


FILLER_INSIGHTS = _filler_insights()
# Asked rows sit at the end of the hand-written block so they take the newest
# timestamps in it and lead the live feed, the way a question asked a moment
# ago does in a real call.
HAND_WRITTEN = CURATED_INSIGHTS + ASKED_INSIGHTS
INSIGHTS = HAND_WRITTEN + FILLER_INSIGHTS

OTHERS = [
    ("Alderwake Health Network - identity recovery workshop", "client_sales", "Technical follow-up on emergency identity authority and isolated validation.", True),
    ("Alderwake Health Network - managed operations due diligence", "client_sales", "Operating-boundary review for a recurring recovery service.", True),
    ("Quarterly services pipeline review", "internal_checkin", "Distributed account team review of open services opportunities.", False),
]

BRIEFING = {
    "top_outcomes": [
        {"title": "Sponsor aligned on a non-disruptive pilot", "summary": "Owen can sponsor a fixed pilot that restores into an isolated network and stays below the procurement threshold.", "owner": "Owen", "status": "Aligned"},
        {"title": "Remote operating gaps are now explicit", "summary": "Runbook sequencing and emergency-access authority caused more delay than the data restore.", "owner": "Alderwake", "status": "Confirmed"},
        {"title": "September evidence path is achievable", "summary": "A four-week pilot leaves contingency before the September 18 board risk meeting.", "owner": "Joint team", "status": "On track"},
    ],
    "client_objectives": [
        {"title": "Close the six-hour recovery gap", "summary": "Move the interface tier from an observed eight-hour recovery toward the stated two-hour objective."},
        {"title": "Produce defensible board and insurer evidence", "summary": "Record timings, owners, exceptions, and remediation decisions without exposing personal details."},
        {"title": "Keep clinical operations insulated", "summary": "Use synthetic data and an isolated recovery network with no production failover."},
    ],
    "top_opportunities": [
        {"title": "Recovery Implementation Pilot", "summary": "Fixed-scope integration, runbook, isolated restore, clinical validation, and evidence pack.", "status": "$72K-$84K"},
        {"title": "Managed Recovery Operations", "summary": "Optional recurring runbook maintenance, validation coordination, and evidence production."},
        {"title": "Quarterly recovery validation", "summary": "Extend the pilot into repeatable governance evidence across critical services."},
    ],
    "risks_blockers": [
        {"title": "Ten-day identity change approval", "summary": "Open the request on day one and reserve a contingency validation window.", "owner": "Owen"},
        {"title": "Clinical owner not yet confirmed", "summary": "The accountable role must approve the validation result.", "owner": "Owen"},
        {"title": "Managed-service boundary needs legal review", "summary": "Data residency, time-bound access, and declaration authority must be explicit.", "owner": "Maya"},
    ],
    "action_plan": [
        {"title": "Send scope and operating boundary", "owner": "Account Lead", "status": "Thursday noon"},
        {"title": "Confirm clinical validation owner", "owner": "Owen", "status": "Tomorrow"},
        {"title": "Hold technical working session", "owner": "Leah", "status": "Tuesday 2:00 Central"},
        {"title": "Pre-clear evidence outline with insurer", "owner": "Maya", "status": "Before pilot start"},
    ],
    "unresolved_discovery_questions": [
        {"title": "Who is the after-hours emergency-access delegate?", "summary": "Primary and backup identity authority must be named in the internal RACI."},
        {"title": "Which accountable role signs clinical validation?", "summary": "The public evidence pack will use a role, not a person's name."},
        {"title": "What recurring evidence cadence will the insurer accept?", "summary": "The answer shapes managed-operations scope and price."},
    ],
    "strategic_signals": [
        {"title": "Compelling event", "summary": "September 18 board risk committee"},
        {"title": "Commercial boundary", "summary": "Fixed pilot below $90K"},
    ],
}

# The live strategic-signal cycle keeps its own `mode='live'` synthesis row.
# One item per section is what the call view renders as the five signal cards.
LIVE_SIGNALS = {
    "strategic_signals": [
        {"title": "September 18 board risk committee is the real deadline", "summary": "Evidence must clear the insurer before the committee reviews it.", "rationale": "Maya named the committee date first and returned to it three times."},
    ],
    "risks_blockers": [
        {"title": "Ten-day identity change approval", "summary": "The change advisory board gates every isolated test that touches identity.", "owner": "Owen", "status": "Open"},
    ],
    "unresolved_discovery_questions": [
        {"title": "Who is the after-hours emergency-access delegate?", "summary": "The last exercise stalled because nobody could authorize emergency accounts."},
    ],
    "top_opportunities": [
        {"title": "Managed Recovery Operations", "summary": "Remote staffing plus a separate cost center make a recurring service credible.", "status": "Follow-on"},
    ],
    "action_plan": [
        {"title": "Keep the fixed pilot below $90K", "summary": "Single-source justification holds under the threshold; above it needs a competitive event.", "owner": "Account Lead", "status": "Before Thursday"},
    ],
    "top_outcomes": [],
    "client_objectives": [],
}

# Signals raised earlier in the call and kept (ALP-244). Before v0.5.0 each
# cycle overwrote the last, so anything not on screen was gone; these rows are
# what "strategic signals persist" means in the product.
SIGNAL_HISTORY = [
    {"section": "strategic_signals", "title": "September 18 board risk committee is the real deadline", "summary": "Evidence must clear the insurer before the committee reviews it.", "count": 6, "first_seen": "", "last_seen": ""},
    {"section": "risks_blockers", "title": "No production failover during the pilot", "summary": "Clinical operations will not approve a production-impacting test in August.", "owner": "Maya", "count": 4, "first_seen": "", "last_seen": ""},
    {"section": "strategic_signals", "title": "Sequencing, not backup integrity, caused the gap", "summary": "The vault met its timing objective; the runbook assumed staff were onsite.", "count": 3, "first_seen": "", "last_seen": ""},
    {"section": "top_opportunities", "title": "Quarterly recovery validation program", "summary": "Governance evidence has to repeat after September, not just exist once.", "count": 2, "first_seen": "", "last_seen": ""},
    {"section": "unresolved_discovery_questions", "title": "Which accountable role signs clinical validation?", "summary": "The public evidence pack will name a role rather than a person.", "count": 3, "first_seen": "", "last_seen": ""},
    {"section": "action_plan", "title": "Pre-clear the evidence outline with the insurer", "summary": "Maya can clear the shape before the test if she sees it now.", "owner": "Maya", "count": 2, "first_seen": "", "last_seen": ""},
]


def signal_history_rows(start):
    """Stamp the kept signals with plausible first/last sighting times."""
    rows = []
    for index, item in enumerate(SIGNAL_HISTORY):
        first_seen = start + timedelta(minutes=8 + index * 4)
        rows.append({
            **item,
            "first_seen": first_seen.isoformat(),
            "last_seen": (first_seen + timedelta(minutes=6 + index)).isoformat(),
        })
    return rows


KNOWLEDGE_RECORDS = [
    {
        "title": "Recovery readiness pilot",
        "body": "A four-week engagement covering discovery, access validation, recovery sequencing, an isolated restore with synthetic data, accountable-owner validation, and a board-ready evidence pack.",
        "meta": json.dumps({"service": "Recovery Implementation Pilot", "phase": "pilot"}),
    },
    {
        "title": "Clinical change-window guardrails",
        "body": "Use an isolated recovery network, synthetic records only, no production failover, an approved identity change, a reserved contingency window, and sign-off by the accountable clinical role.",
        "meta": json.dumps({"service": "Recovery Implementation Pilot", "control": "change"}),
    },
    {
        "title": "Managed recovery operations",
        "body": "Maintain remote-ready runbooks, coordinate scheduled validation, produce governance evidence, and document exceptions while the customer retains approval authority and recovery declaration ownership.",
        "meta": json.dumps({"service": "Managed Recovery Operations", "phase": "operate"}),
    },
]


def reset():
    psql(
        "DELETE FROM insight_clusters; DELETE FROM session_syntheses; "
        "DELETE FROM questions; DELETE FROM transcript_entries; DELETE FROM call_segments; "
        "DELETE FROM speakers; DELETE FROM sessions; DELETE FROM session_groups;"
    )
    print("reset: demo tables cleared")


def seed_catalog_and_knowledge():
    call("POST", "/offerings/seed?replace=true")
    for source in call("GET", "/knowledge"):
        if source["name"] == "Recovery Delivery Playbooks":
            call("DELETE", f"/knowledge/{source['id']}")
    source = call(
        "POST",
        "/knowledge",
        {
            "name": "Recovery Delivery Playbooks",
            "source_type": "collection",
            "description": "Fictional delivery patterns used by the public recovery-readiness demo.",
            "config": "{}",
            "active": True,
        },
    )
    for record in KNOWLEDGE_RECORDS:
        call("POST", f"/knowledge/{source['id']}/records", {**record, "active": True})


def briefing_sql(session_id, created_at, payload=None, mode="post_call", history=()):
    fields = (
        "top_outcomes",
        "client_objectives",
        "top_opportunities",
        "risks_blockers",
        "action_plan",
        "unresolved_discovery_questions",
        "strategic_signals",
    )
    payload = BRIEFING if payload is None else payload
    values = [q(json.dumps(payload[field])) + "::json" for field in fields]
    return (
        "INSERT INTO session_syntheses ("
        "id, session_id, mode, status, "
        + ", ".join(fields)
        + ", signal_history, evidence_refs, lens_meeting, lens_discovery, arbiter_notes, "
        "model_ids, error_message, created_at, updated_at, speaker_mapping_revision_id) VALUES ("
        + ", ".join(
            [
                q(str(uuid.uuid4())),
                q(session_id),
                q(mode),
                q("completed"),
                *values,
                q(json.dumps(list(history))) + "::json",
                q("[]") + "::json",
                q(json.dumps({"notes": "Deterministic fixture-backed meeting lens."})) + "::json",
                q(json.dumps({"notes": "Deterministic fixture-backed discovery lens."})) + "::json",
                q("The decision, risks, and next steps are supported by the fictional transcript."),
                q(json.dumps({"fixture": "showcase.seed_demo"})) + "::json",
                q(""),
                q(created_at.isoformat()),
                q(created_at.isoformat()),
                "NULL",
            ]
        )
        + ");\n"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="clear existing sessions first")
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="run the real analysis agents over the transcript instead of inserting canned insights",
    )
    args = parser.parse_args()
    if args.reset:
        reset()

    try:
        group = call("POST", "/groups", {"name": GROUP})
    except urllib.error.URLError as error:
        raise SystemExit(f"cannot reach {BASE} -- is the app running? ({error})")

    main_session = call(
        "POST",
        "/sessions",
        {
            "name": MAIN,
            "meeting_type": "client_sales",
            "meeting_context": (
                "Recovery-readiness review with a distributed health-network infrastructure "
                "team. A failed exercise exposed an eight-hour recovery against a two-hour "
                "objective. Goal: agree a non-disruptive pilot before September governance dates."
            ),
        },
    )
    call(
        "PATCH",
        f"/sessions/{main_session['id']}",
        {"group_id": group["id"], "state": "completed"},
    )

    for name, meeting_type, context, grouped in OTHERS:
        session = call(
            "POST",
            "/sessions",
            {"name": name, "meeting_type": meeting_type, "meeting_context": context},
        )
        update = {"state": "completed"}
        if grouped:
            update["group_id"] = group["id"]
        call("PATCH", f"/sessions/{session['id']}", update)

    speakers = {}
    for name, role, color, is_user, speaker_type in SPEAKERS:
        speaker = call(
            "POST",
            f"/sessions/{main_session['id']}/speakers",
            {
                "name": name,
                "role": role,
                "color": color,
                "is_user": is_user,
                "speaker_type": speaker_type,
            },
        )
        speakers[name] = speaker["id"]

    start = datetime.now(timezone.utc) - timedelta(days=3, hours=2)
    for sequence, (who, text) in enumerate(LINES):
        call(
            "POST",
            f"/sessions/{main_session['id']}/transcripts",
            {
                "text": text,
                "speaker_id": speakers[who],
                "timestamp": (start + timedelta(seconds=48 * sequence)).isoformat(),
                "sequence": sequence,
            },
        )

    seed_catalog_and_knowledge()

    timings = (
        "UPDATE sessions SET started_at = created_at - interval '3 days 2 hours',"
        " ended_at = created_at - interval '3 days 2 hours' + interval '47 minutes'"
        " WHERE state = 'completed';\n"
        "INSERT INTO call_segments (id, session_id, segment_number, started_at, ended_at)"
        " SELECT gen_random_uuid(), id, 1, started_at,"
        " started_at + interval '44 minutes 12 seconds' FROM sessions WHERE state = 'completed';\n"
        "INSERT INTO call_segments (id, session_id, segment_number, started_at, ended_at)"
        " SELECT gen_random_uuid(), id, 2, started_at + interval '45 minutes',"
        f" started_at + interval '47 minutes' FROM sessions WHERE name = {q(MAIN)};\n"
    )

    if args.analyze:
        psql(timings + briefing_sql(main_session["id"], start + timedelta(minutes=47)))
        print("running the real analysis agents over the transcript...")
        call("POST", f"/sessions/{main_session['id']}/analyze")
        count = psql(
            f"SELECT count(*) FROM questions WHERE session_id = {q(main_session['id'])};"
        )
        print(
            f"seeded: 1 group, {1 + len(OTHERS)} sessions, {len(speakers)} speakers, "
            f"{len(LINES)} transcript lines, {count.split()[2]} generated insights"
        )
        return

    columns = (
        "id, session_id, item_type, lens_label, question, rationale, source_context, "
        "speaker_id, directive_id, starred, dismissed, answered, answer_summary, "
        "needs_followup, followup_question, created_at, updated_at, enrichment_notes, "
        "revision_count, agent_source, offering_match, vote, enhanced, "
        "speaker_mapping_revision_id"
    )
    insight_rows = []
    # Hand-written rows take the newest window (minutes 20-45) so they top
    # every newest-first section; filler spreads across minutes 2-20 underneath.
    curated_count = len(HAND_WRITTEN)

    def insight_timestamp(index):
        if index < curated_count:
            return start + timedelta(minutes=20 + index)
        return start + timedelta(seconds=120 + (index - curated_count) * 11)

    for index, insight in enumerate(INSIGHTS):
        (
            item_type,
            source,
            question,
            rationale,
            context,
            who,
            starred,
            answered,
            answer_summary,
            needs_followup,
            followup,
            offering_match,
            enhanced,
        ) = insight
        insight_rows.append(
            "("
            + ", ".join(
                [
                    q(str(uuid.uuid4())),
                    q(main_session["id"]),
                    q(item_type),
                    q(""),
                    q(question),
                    q(rationale),
                    q(context),
                    q(speakers[who]) if who else "NULL",
                    "NULL",
                    str(starred).lower(),
                    "false",
                    str(answered).lower(),
                    q(answer_summary),
                    str(needs_followup).lower(),
                    q(followup),
                    q(insight_timestamp(index).isoformat()),
                    "NULL",
                    q(""),
                    "0",
                    q(source),
                    q(offering_match),
                    "0",
                    str(enhanced).lower(),
                    "NULL",
                ]
            )
            + ")"
        )

    history = signal_history_rows(start)
    psql(
        f"INSERT INTO questions ({columns}) VALUES\n"
        + ",\n".join(insight_rows)
        + ";\n"
        + timings
        + briefing_sql(
            main_session["id"], start + timedelta(minutes=47), history=history
        )
        + briefing_sql(
            main_session["id"],
            start + timedelta(minutes=45),
            payload=LIVE_SIGNALS,
            mode="live",
            history=history,
        )
    )
    print(
        f"seeded: 1 group, {1 + len(OTHERS)} sessions, {len(speakers)} speakers, "
        f"{len(LINES)} transcript lines, {len(CURATED_INSIGHTS)} curated + "
        f"{len(ASKED_INSIGHTS)} asked + {len(FILLER_INSIGHTS)} filler insights, "
        f"{len(history)} kept signals, {len(KNOWLEDGE_RECORDS)} knowledge records"
    )


if __name__ == "__main__":
    main()
