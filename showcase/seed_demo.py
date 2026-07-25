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
# Sessions, groups, speakers, and transcript lines go through the product's real
# REST APIs so they acquire genuine derived state. Insights have no POST endpoint,
# so they are written directly with SQL via the compose db service.
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
GROUP = "Northwind Logistics"
MAIN = "Northwind Logistics - segmentation review"


def call(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode()
        return json.loads(body) if body.strip() else None


def env(key):
    for line in (REPO / ".env").read_text(encoding="utf8").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    raise SystemExit(f"{key} not found in .env")


def psql(sql):
    cmd = ["docker", "compose", "exec", "-T", "db", "psql",
           "-U", env("POSTGRES_USER"), "-d", env("POSTGRES_DB")]
    p = subprocess.run(cmd, input=sql, capture_output=True, text=True, cwd=REPO)
    if p.returncode != 0:
        raise SystemExit(f"psql failed:\n{p.stderr}")
    return p.stdout


def q(s):
    return "'" + s.replace("'", "''") + "'"


SPEAKERS = [
    ("Me", "Account Lead", "#0d9488", True, "team"),
    ("Marcus", "Solutions Architect", "#7c3aed", False, "team"),
    ("Dana", "Director of Infrastructure", "#f59e0b", False, "external"),
    ("Priya", "Security Lead", "#10b981", False, "external"),
]

LINES = [
    ("Dana", "Morning. Before we start, is it alright if I record this? I want to get the detail right for our steering pack."),
    ("Me", "Of course, go ahead. I will send my own notes across afterwards either way."),
    ("Dana", "Appreciated. So, quick round of introductions -- Priya heads security for us, Marcus I think you two met on the technical pre-call last week."),
    ("Marcus", "We did. Priya, you had sent through the topology export afterwards, which was genuinely useful."),
    ("Priya", "Good. I would rather you see the real thing than a tidied-up version of it."),
    ("Dana", "Thanks for making time. Before we get into architecture, I should set context on the deadline -- our cyber insurance renews on November 14 and the carrier has flagged flat networks as a finding."),
    ("Me", "That is useful to know up front. Is segmentation a stated condition of renewal, or a recommendation they would like to see progress against?"),
    ("Dana", "It is phrased as a recommendation, but our broker was fairly direct that the premium moves if we cannot show a plan."),
    ("Priya", "And to be blunt, we have been told to expect a twenty percent increase if nothing changes. That is the number that got this project funded."),
    ("Marcus", "Understood. Can you walk me through what the depot network looks like today? Is it one flat space end to end, or are the depots already separated from the core?"),
    ("Dana", "Forty depots, all on one address space. Warehouse scanners, the WMS terminals, HVAC, badge readers, and the office side all share it. It grew that way over about fifteen years."),
    ("Priya", "The part that worries me most is the building systems. The HVAC controllers run firmware we cannot patch and they sit on the same VLAN as the WMS."),
    ("Me", "That is the pattern we see most often in distribution. What would need to be true for you to consider this successful by November?"),
    ("Dana", "Honestly? A defensible plan and at least a couple of sites actually done. I do not think forty is realistic in that window."),
    ("Marcus", "Agreed, and I would not propose it. A two-site pilot with a repeatable template is a stronger story for a carrier than forty half-finished sites."),
    ("Priya", "How disruptive is the cutover? We cannot take a depot offline during peak. Our freeze runs from the last week of October through the new year."),
    ("Marcus", "The cutover itself is a maintenance window per site, typically under four hours. The discovery phase ahead of it is passive and does not touch traffic."),
    ("Dana", "That freeze is the real constraint. If we cannot start until January we lose the insurance argument entirely."),
    ("Me", "Then let us work backwards from the freeze rather than the renewal. If discovery starts in early September, would two sites before the last week of October be achievable on your side?"),
    ("Dana", "Probably, if we can get the depot managers to commit windows. That is a people problem more than a technical one."),
    ("Priya", "There is also the question of who operates it afterwards. My team is four people covering everything. I cannot take on a platform that needs a full-time engineer."),
    ("Me", "That is fair, and worth flagging now rather than at contract. Would a managed option be something you would evaluate, or is that out of scope for this budget?"),
    ("Priya", "I would evaluate it. The budget line is for the project, but operating cost is a separate conversation I would need to start with our CFO."),
    ("Dana", "One more thing -- we are also mid-way through replacing the WMS next year. I do not want to segment around a system we are about to retire."),
    ("Marcus", "That actually argues for doing it now. If we build the template against the current WMS and document the policy intent, the replacement drops into the same structure without a redesign."),
    ("Dana", "That is a good point. I had assumed we would have to wait."),
    ("Me", "Let me summarize what I have: November 14 renewal, October freeze, two-site pilot, passive discovery starting September, and an open question on who operates it. Anything I have missed?"),
    ("Priya", "The unpatched building systems. Whatever we do has to isolate those first, not last."),
    ("Me", "Noted, and I would put that at the front of the design. I will send a two-site scope with the September start and a separate managed-service option so you can take that to your CFO independently."),
    ("Dana", "That works. Send it by end of week and I will get it in front of our director before the next steering call."),
    ("Marcus", "Can I come back to the depot topology for a moment? You said forty sites on one address space. Are they all the same shape, or do the larger distribution centres differ?"),
    ("Dana", "Six of them are proper distribution centres with their own comms rooms. The other thirty-four are cross-dock sites -- a switch, a router, and a cabinet in the corner of a warehouse."),
    ("Priya", "And nobody on site who could tell you what is plugged into what. That is the honest position."),
    ("Marcus", "Then discovery matters more than the design does. If we cannot see the traffic we will be guessing at policy, and a wrong policy at a cross-dock stops trucks moving."),
    ("Dana", "Stopping trucks is the thing that gets people fired here. I want to be very clear about that risk."),
    ("Me", "Understood. What is the actual cost of an hour of downtime at a cross-dock, roughly? It helps size the risk against the pilot approach."),
    ("Dana", "We model it at about eleven thousand an hour at a mid-size site during peak. Less in the summer, much more in December."),
    ("Priya", "Which is why the freeze exists. Nobody will sign off a change window between late October and the new year."),
    ("Marcus", "Then the passive discovery phase becomes the safety net. We tap, we watch for two weeks, and we build policy from observed flows rather than from a diagram someone drew in 2019."),
    ("Dana", "How much kit does the tap require? I do not have budget for forty new appliances."),
    ("Marcus", "For the pilot, two. And we can often use existing switch mirror ports rather than inline taps, which costs nothing but configuration."),
    ("Priya", "Mirror ports are fine on the six big sites. The cross-docks have older switches, some of them unmanaged."),
    ("Marcus", "That is useful to know. Unmanaged switches would change the approach at those sites -- we would need to look at the uplink instead."),
    ("Me", "Let me note that as an open technical question rather than trying to solve it live. Priya, could you get us a model and firmware inventory for the cross-dock switches?"),
    ("Priya", "I can, though it will be partial. We have an asset register that is maybe seventy percent accurate."),
    ("Dana", "Seventy is generous."),
    ("Priya", "It is. Call it sixty."),
    ("Me", "Sixty percent is still a starting point, and discovery will correct it. Better than designing against a register everyone assumes is right."),
    ("Dana", "Moving on -- what does this look like commercially? I need a number to put in front of the steering group, even a rough one."),
    ("Me", "For a two-site pilot with passive discovery, design, and cutover, we would typically be in the region of forty to sixty thousand depending on how much of the operational work your team takes on."),
    ("Dana", "That is within what I expected. The full forty-site rollout is the number that will frighten people."),
    ("Me", "It should, if we quote it now. I would rather the pilot prove the per-site cost so the rollout number is evidence rather than a guess."),
    ("Priya", "That is a more defensible way to present it internally, I agree."),
    ("Dana", "There is a complication. Procurement has us on a preferred-supplier list and you are not on it."),
    ("Me", "How does that normally get handled? Is there a route for a single-source justification, or does it need a full competitive process?"),
    ("Dana", "Under seventy-five thousand we can single-source with a written justification. Above that it goes to tender."),
    ("Marcus", "Which is another argument for scoping the pilot tightly rather than bundling the rollout into it."),
    ("Dana", "Exactly my thinking. Keep the pilot under the threshold and we move in weeks rather than months."),
    ("Me", "Then I will scope the pilot to sit clearly under seventy-five, and price the rollout separately as an indicative figure with no commitment."),
    ("Priya", "Can I raise something about the managed option? If we go that way, where does the data actually sit?"),
    ("Me", "That is the right question to ask. In the managed model the telemetry stays in your environment and we access it; nothing about the flow data leaves your infrastructure."),
    ("Priya", "That matters a lot to our legal team. We had a bad experience with a vendor who was vague about it."),
    ("Dana", "The identity platform evaluation, that was the one."),
    ("Priya", "It was. We got three different answers from three people at the same company."),
    ("Me", "I will put the data-residency position in writing as part of the managed-service document, so there is one answer and it is on paper."),
    ("Marcus", "Coming back to the technical side -- what is the WMS actually running on today?"),
    ("Dana", "It is a vendor package on Windows servers in our primary data centre, with thin clients at the depots."),
    ("Marcus", "And the replacement next year, is that the same vendor or a different platform entirely?"),
    ("Dana", "Different vendor, cloud-hosted. That is part of why I hesitated on segmenting now."),
    ("Marcus", "Cloud-hosted actually simplifies it. The depot side stops talking to your data centre and starts talking to an internet endpoint, which is a cleaner policy boundary, not a messier one."),
    ("Dana", "I had not thought of it that way. So the segmentation work survives the migration."),
    ("Marcus", "It does more than survive it -- it makes the migration safer, because you will know exactly what each depot talks to before you move anything."),
    ("Priya", "That is a good argument for the steering group. It reframes this as migration preparation rather than pure compliance spend."),
    ("Me", "I will make sure that framing is in the document. It is a stronger business case than insurance alone."),
    ("Dana", "What about the badge readers and the HVAC? Priya keeps raising those and I do not think we have addressed them."),
    ("Priya", "Because they are the ones that scare me. The HVAC controllers are on firmware from 2016 with known vulnerabilities and the vendor will not patch them."),
    ("Marcus", "Those go in their own segment on day one, with a deny-by-default policy and a narrow allowance to the building management server. That is a two-hour change per site."),
    ("Priya", "And if the building management server itself is compromised?"),
    ("Marcus", "Then the blast radius is the building systems rather than the WMS and the office network. That is the whole point of the exercise."),
    ("Priya", "Fine. I want that written as an explicit design principle, not left implied."),
    ("Me", "Noted -- OT isolation as a stated design principle in the scope document."),
    ("Dana", "Timeline. Walk me through it week by week, because September is closer than it sounds."),
    ("Me", "Week one and two, passive discovery at the two pilot sites. Week three, policy design and your review. Week four, first site cutover in a maintenance window. Week five, observe and tune. Week six, second site."),
    ("Dana", "That takes us to mid-October with two weeks of margin before the freeze."),
    ("Marcus", "Which we will need. Something always slips, usually the change approval rather than the technical work."),
    ("Priya", "Change approval here takes ten working days minimum. Build that in or the plan is fiction."),
    ("Me", "Then I will show change windows requested at the start of week two, not week three. Thank you, that would have bitten us."),
    ("Dana", "This is why we do these calls properly."),
    ("Me", "Who else needs to see the scope before it goes to the steering group?"),
    ("Dana", "Me first, then our director, then it goes in the pack. Priya sees it in parallel for the security content."),
    ("Priya", "And I will want to send the OT section to our insurer's technical contact. They have been surprisingly helpful."),
    ("Me", "That is a good idea -- if the carrier endorses the approach it strengthens the whole case. Would you like me to write that section so it can be shared externally without edits?"),
    ("Priya", "Yes. That would save me a round trip."),
    ("Dana", "One last thing. If the pilot goes well, what does the rollout actually look like in terms of pace?"),
    ("Marcus", "Realistically, four to six sites a month once the template is proven, assuming your change process can absorb it."),
    ("Dana", "So call it eight months for the estate. That is a 2027 conversation."),
    ("Me", "It is, and I would rather set that expectation now than promise a compressed timeline nobody can deliver."),
    ("Dana", "Appreciated. Right, I think we have what we need. Send the scope, I will get it moving."),
    ("Priya", "And the data-residency note and the OT section written for external sharing."),
    ("Me", "Both included. I will have it with you by Thursday rather than Friday, so you have a day to react before your steering call."),
    ("Dana", "That is better. Thanks both."),
]

# item_type, agent_source, question, rationale, context, speaker, starred,
# answered, answer_summary, needs_followup, followup, offering_match, enhanced
INSIGHTS = [
    ("action_item", "action_tracker", "Send a two-site pilot scope with a September discovery start", "Dana asked for it by end of week so it can go to their director before the next steering call.", "Send it by end of week and I will get it in front of our director", "Me", True, False, "", False, "", "", True),
    ("action_item", "action_tracker", "Package the managed-service option as a separate document", "Priya needs to take operating cost to the CFO on a different budget line than the project.", "The budget line is for the project, but operating cost is a separate conversation", "Priya", True, False, "", False, "", "", True),
    ("action_item", "action_tracker", "Confirm depot maintenance windows with site managers", "Dana called this a people problem and the pilot timeline depends on it.", "if we can get the depot managers to commit windows", "Dana", False, False, "", True, "Which two depots are the best pilot candidates on staffing alone?", "", False),
    ("objection", "objection_handler", "We cannot take a depot offline during the October to January freeze", "The freeze removes the entire window between discovery and the insurance renewal, which is the compelling event.", "We cannot take a depot offline during peak", "Priya", True, True, "Reframed to work backwards from the freeze rather than the renewal: passive discovery in early September, two sites cut over before the last week of October.", False, "", "", True),
    ("objection", "objection_handler", "My team is four people and cannot operate a new platform", "Operational capacity, not price, is the blocker here. Answer with a managed option before it hardens into a no.", "I cannot take on a platform that needs a full-time engineer", "Priya", False, True, "Priya will evaluate a managed option and start a separate CFO conversation about operating cost.", False, "", "Managed detection and response", False),
    ("objection", "objection_handler", "We are replacing the WMS next year, so why segment around it now", "Sequencing objection. The counter is that a documented policy template survives the WMS replacement.", "I do not want to segment around a system we are about to retire", "Dana", False, True, "Marcus reframed it: building the template now means the replacement drops into the same structure without redesign. Dana accepted the point.", False, "", "", True),
    ("opportunity", "opportunity_scout", "Managed operations for the segmentation platform", "Security team is capacity-constrained and Priya explicitly said she would evaluate a managed option.", "I would evaluate it", "Priya", True, False, "", False, "", "Managed detection and response", True),
    ("opportunity", "opportunity_specialist", "OT and building-systems isolation as a distinct workstream", "Unpatchable HVAC controllers on the same VLAN as the WMS is a named, urgent risk with its own budget rationale.", "they run firmware we cannot patch", "Priya", True, False, "", False, "", "OT network assessment", True),
    ("opportunity", "opportunity_scout", "WMS replacement creates a follow-on network design engagement", "A platform migration next year is adjacent scope that the segmentation template directly feeds.", "we are also mid-way through replacing the WMS next year", "Dana", False, False, "", True, "Who owns the WMS replacement programme, and is network design in their scope or yours?", "", False),
    ("question", "question_hunter", "Is segmentation a stated condition of the insurance renewal, or a recommendation?", "The distinction changes how hard the November date really is and how much leverage the deadline carries.", "our cyber insurance renews on November 14", "Dana", False, True, "A recommendation, but the broker was direct that the premium moves without a visible plan -- a twenty percent increase is expected.", False, "", "", True),
    ("question", "question_hunter", "What would need to be true for this to be successful by November?", "Surfaces the customer's own success criteria before proposing scope.", "What would need to be true for you to consider this successful", "Me", False, True, "A defensible plan plus two sites actually completed. Dana does not consider forty realistic in the window.", False, "", "", True),
    ("question", "question_hunter", "Who operates the platform after the pilot, and on whose budget?", "Ownership is unresolved and sits on a different budget line, which affects both the commercial shape and the close.", "who operates it afterwards", "Priya", True, False, "", True, "Would the CFO conversation happen before or after the pilot decision?", "", False),
    ("observation", "observer", "The compelling event is the October freeze, not the November renewal", "Every workable plan has to complete before the last week of October, which compresses the real timeline by three weeks.", "That freeze is the real constraint", "Dana", True, False, "", False, "", "", True),
    ("observation", "observer", "Budget was approved on the basis of an expected twenty percent premium increase", "The project is funded by risk avoidance, so proposals should be framed against that number rather than technical merit.", "we have been told to expect a twenty percent increase", "Priya", False, False, "", False, "", "", True),
    ("observation", "synthesizer", "Priya raises operational capacity three separate times", "Consistent signal across the call: staffing, not price, is the dominant concern and should lead the proposal.", "My team is four people covering everything", "Priya", False, False, "", False, "", "", False),
    ("observation", "observer", "Dana defers to a director for approval", "There is at least one decision-maker not on this call, and the scope document is what reaches them.", "I will get it in front of our director", "Dana", False, False, "", False, "", "", False),
]

OTHERS = [
    (MAIN.replace("segmentation review", "SD-WAN follow-up"), "discovery", "Follow-up on depot connectivity and circuit costs.", True),
    ("Vendor eval - identity platform", "general", "Internal comparison of three identity vendors ahead of a Q4 decision.", False),
    ("Weekly pipeline review", "general", "Standing internal review of open opportunities.", False),
]


def reset():
    psql("DELETE FROM questions; DELETE FROM transcript_entries; DELETE FROM call_segments; "
         "DELETE FROM speakers; DELETE FROM sessions; DELETE FROM session_groups;")
    print("reset: demo tables cleared")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="clear existing sessions first")
    ap.add_argument("--analyze", action="store_true",
                    help="run the real analysis agents over the transcript instead of "
                         "inserting the canned insight set (requires a configured LLM key)")
    args = ap.parse_args()
    if args.reset:
        reset()

    try:
        group = call("POST", "/groups", {"name": GROUP})
    except urllib.error.URLError as e:
        raise SystemExit(f"cannot reach {BASE} -- is the app running? ({e})")

    main_s = call("POST", "/sessions", {
        "name": MAIN, "meeting_type": "discovery",
        "meeting_context": (
            "Second call with Northwind's infrastructure team. They run 40 regional "
            "depots on a flat network and want segmentation before their cyber "
            "insurance renewal in November. Goal: agree scope and land a pilot."),
    })
    call("PATCH", "/sessions/" + main_s["id"], {"group_id": group["id"], "state": "completed"})

    for name, mtype, ctx, grouped in OTHERS:
        s = call("POST", "/sessions", {"name": name, "meeting_type": mtype, "meeting_context": ctx})
        body = {"state": "completed"}
        if grouped:
            body["group_id"] = group["id"]
        call("PATCH", "/sessions/" + s["id"], body)

    sp = {}
    for name, role, color, is_user, stype in SPEAKERS:
        s = call("POST", f"/sessions/{main_s['id']}/speakers", {
            "name": name, "role": role, "color": color,
            "is_user": is_user, "speaker_type": stype})
        sp[name] = s["id"]

    start = datetime.now(timezone.utc) - timedelta(days=3, hours=2)
    for i, (who, text) in enumerate(LINES):
        call("POST", f"/sessions/{main_s['id']}/transcripts", {
            "text": text, "speaker_id": sp[who],
            "timestamp": (start + timedelta(seconds=42 * i)).isoformat(), "sequence": i})

    cols = ("id, session_id, item_type, lens_label, question, rationale, source_context, "
            "speaker_id, directive_id, starred, dismissed, answered, answer_summary, "
            "needs_followup, followup_question, created_at, updated_at, enrichment_notes, "
            "revision_count, agent_source, offering_match, vote, enhanced, "
            "speaker_mapping_revision_id")
    # Timings first, so the post-call header shows a real duration either way.
    timings = (
        "UPDATE sessions SET started_at = created_at - interval '3 days 2 hours',"
        " ended_at = created_at - interval '3 days 2 hours' + interval '47 minutes'"
        " WHERE state = 'completed';\n"
        "INSERT INTO call_segments (id, session_id, segment_number, started_at, ended_at)"
        " SELECT gen_random_uuid(), id, 1, started_at,"
        " started_at + interval '44 minutes 12 seconds' FROM sessions WHERE state = 'completed';\n"
        f"INSERT INTO call_segments (id, session_id, segment_number, started_at, ended_at)"
        f" SELECT gen_random_uuid(), id, 2, started_at + interval '45 minutes',"
        f" started_at + interval '47 minutes' FROM sessions WHERE name = {q(MAIN)};\n"
    )

    if args.analyze:
        psql(timings)
        print("running the real analysis agents over the transcript (this takes a minute)...")
        call("POST", f"/sessions/{main_s['id']}/analyze")
        n = psql(f"SELECT count(*) FROM questions WHERE session_id = {q(main_s['id'])};")
        print(f"seeded: 1 group, {1 + len(OTHERS)} sessions, {len(sp)} speakers, "
              f"{len(LINES)} transcript lines, {n.split()[2]} generated insights")
        return

    base_t = start + timedelta(minutes=6)
    rows = []
    for n, r in enumerate(INSIGHTS):
        (itype, src, qq, rat, ctx, who, star, ans, ansum, nf, fq, om, enh) = r
        rows.append("(" + ", ".join([
            q(str(uuid.uuid4())), q(main_s["id"]), q(itype), q(""), q(qq), q(rat), q(ctx),
            q(sp[who]), "NULL", str(star).lower(), "false", str(ans).lower(), q(ansum),
            str(nf).lower(), q(fq), q((base_t + timedelta(minutes=n * 2)).isoformat()),
            "NULL", q(""), "0", q(src), q(om), "0", str(enh).lower(), "NULL",
        ]) + ")")

    psql(f"INSERT INTO questions ({cols}) VALUES\n" + ",\n".join(rows) + ";\n" + timings)

    print(f"seeded: 1 group, {1 + len(OTHERS)} sessions, {len(sp)} speakers, "
          f"{len(LINES)} transcript lines, {len(INSIGHTS)} canned insights")


if __name__ == "__main__":
    main()
