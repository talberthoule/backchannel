# Revenue intelligence - competitive research (2026-07-24)

Category lead: Lead A. Targets: Gong (primary), Clari Copilot (formerly
Wingman), Chorus by ZoomInfo (formerly Chorus.ai), plus one added peer --
Attention (attention.com), justified in its profile below.

All competitor facts were gathered by live web research on 2026-07-24. Every
load-bearing claim carries a source and a confidence grade in the QA/QC table at
the end. Backchannel capability claims are verified against the repository at
`master` (v0.3.6) and cited to file paths, not marketing copy. Where the only
available source is a blog operated by a company selling against the product
described, the claim is labelled competitor-blog and marked do-not-publish.

## Category summary

Revenue intelligence is a different market from the note-taker segment that
Backchannel's existing comparison pages address (Otter, Fireflies, Granola). The
buyer is a VP of Sales, RevOps, or enablement leader. The unit of value is the
deal and the pipeline, not the meeting. The purchase is an annual or multi-year
contract sized in the tens of thousands of dollars, deployed org-wide by an
admin against calendar and CRM.

Five structural findings define the category, and they all point the same way.

**1. The category is post-call by construction.** Gong -- the leader by a wide
margin at 5,000+ customers and ARR past $500M as of 2026-05-12 -- documents its
coaching workflow entirely as review of recorded calls: Feedback Request,
comments and tagging, call sharing, call scoring, and AI Call Reviewer. Its own
coaching documentation contains zero references to real-time or in-call rep
guidance. The only live-call capability Gong documents is manager listen-in on
an "ON AIR" call, capped at two listeners. Chorus markets the word "real-time"
but defines it on its own product page as "delivers in real-time -- so you can
access call insights within minutes after your call ends." Minutes after the
call ends is post-call.

**2. Real-time in-call objection help is now table stakes, not novel -- but the
mechanism is still ours alone.** Clari Copilot inherited Wingman's live
battlecards. Attention markets "AI powered battlecards help you answer any
prospect question while on the call." And as of **2026-07-22 Zoom took Sales
Assist to general availability** inside Zoom Revenue Accelerator, surfacing
"competitive intelligence, objection guidance, discovery prompts, battlecards,
and configurable framework capture in real time." None of the three generates a
situation-specific response by reasoning over what was actually just said; all
surface prepared content. Zoom's is the clearest documented case: its support KB
has an admin configure the talking points for each topic category (discovery,
objection handling, pricing, competitor talking points, functionalities) ahead
of time, with knowledge collections attached as reference and rule-based "live
signals" and timer reminders driving display. **The positioning consequence is
that our claim must be about mechanism -- we generate a response to the
objection actually raised -- not about novelty.**

**3. Every target is cloud-only, bot-mediated, and org-deployed.** None of the
four offers self-hosted, on-premises, single-tenant, or customer-VPC deployment.
All four capture by putting a recorder into the participant list. A SERP scan
for self-hosted or open-source conversation intelligence returns only commercial
cloud vendors -- there is no open-source participant in this category at all.

**4. The bot is the category's shared structural flaw, and it is
independently documented.** Both Clari Copilot and Chorus have verbatim reviewer
complaints that the bot is hard to remove mid-call when a prospect objects
("Wish it was faster to kick off Wingman from a call when a customer doesn't
want to be recorded"; "Disengaging Chorus from a call can be a cumbersome
process"). Gong's version is the mirror image: reviewers report there is no way
to invite the recorder into a call already in progress. All three fail at the
same seam -- the recorder is a meeting participant, so consent is an
all-or-nothing decision made before the call starts. Late-joining recorders that
miss the opening of a call are a complaint for all three.

**5. Gong's privacy posture is genuinely strong, which rules out the lazy
attack.** Gong publishes a US-or-EU AWS data residency choice, SOC 2 Type II,
ISO 27001/27017/27018/27701, EU-US DPF, CSA STAR, irreversible deletion within
30 days of contract termination, and the statement that "your data is never used
to train generative models." Any page implying Gong is careless with audio would
be false and would destroy the credibility this brand's comparison pages depend
on. The deployment difference is real but it is about *who the tool serves*, not
about Gong being unsafe.

**Where Backchannel actually sits.** It is not a revenue intelligence platform
and cannot become one on this roadmap. It has no CRM sync, no deal, account, or
pipeline object, no forecasting, no call library, no scorecards, no talk-time
analytics, no manager rollup, and no user accounts at all -- there is no `User`
model in `backend/app/models.py` and no authentication dependency in any router.
What it has is the live seller-side layer this category deliberately does not
build: an `objection_handler` running every 10 seconds over the trailing 90
seconds of transcript, emitting a `response_now` (what to say in the next ten
seconds) plus a `bigger_picture` (the underlying concern and the strategic
angle), alongside `consolidated_analyst`, `strategic_signals`, `synthesizer`,
and `opportunity_specialist`.

That asymmetry -- they own the deal record after the call, Backchannel owns the
seller's next sentence during it -- is the positioning thesis, and it is why the
Gong page must be ecosystem fit rather than an alternative page.

## Per-competitor profiles

### Gong

**Positioning and ICP.** Gong positions as the "Revenue AI Operating System,"
not a call recorder: Gong Engage, Gong Forecast, Gong Enable, Revenue Graph, and
Gong AI. The buyer is an enterprise or upper-mid-market revenue org. 5,000+
customers, ARR past $500M, 55%+ YoY growth as of the 2026-05-12 press release.
It is also genuinely well-liked: Capterra 4.8/5 across 561 reviews;
SoftwareReviews (Info-Tech) composite 9.0/10 across 199 reviews with 95% planning
to renew and a Net Emotional Footprint of +93. Any page that attacks Gong head-on
will read as dishonest to the reader who actually uses it.

**Pricing (as of 2026-07-24).** Gong publishes no prices. Its pricing page states
only that "Licenses are priced per user" and "There is a platform fee based on
the number of users supported," with team-size brackets (1-50, 51-1,000,
1,001-9,999, 10,000+) behind a form. Independent procurement data from Vendr
(n = 1,126 purchases, page last updated March 2026) reports a **median annual
contract value of $54,900**, range $11,352-$204,036, average savings 14.17%, and
per-seat bands of $1,600-$2,400/yr at 10-25 seats, $1,400-$2,200 at ~50 seats,
and $1,200-$1,800 at 100+ seats. Vendr additionally reports typical seat
minimums of 10-15, auto-renewal escalation of 5-10%/yr, mid-contract seat
true-ups at a 10-20% premium, and Forecast/Engage modules adding 20-40% of base
per seat. Note the direct conflict worth handling carefully: **Gong's own
`plans-and-seats` documentation states no minimum seat requirement and does not
mention a platform fee at all**, while the pricing page does confirm a platform
fee exists. Unassigned team members are free "Collaborators" with limited
access.

**Capture model.** Two documented methods. Bot recording -- "A virtual
participant, responsible for recording the call, is added to the meeting" --
"Available for all web conferencing integrations" (11 platforms including Zoom,
Meet, Teams, Webex, RingCentral). And native recording using "the provider's
native recording functionality, with no additional participant added to the
call," which is "only available with Zoom." With a waiting room enabled, "the
host must admit the bot to start the recording." Bot-free capture therefore
exists, but only if the whole org is on Zoom with appropriate licensing.

**Where data is processed.** Gong's cloud, on AWS. "New Gong customers can decide
to store their data in data centers in either the US or EU," default US. "Gong
holds offices in the United States, Israel, and Ireland, where data may be
processed," plus sub-processors in the US, UK, and EMEA. Certifications: SOC 2
Type II, ISO 27001/27017/27018/27701, ISO 42001 (AI management), PCI DSS SAQ-D,
EU-US DPF, CSA STAR, HIPAA mapping in the SOC 2 report. Model training: "your
data is never used to train generative models" -- note the wording is scoped to
generative models. Retention: default the lesser of three years or the customer
relationship, admin-adjustable; "If you cease being a Gong customer, your data
will be irreversibly deleted in 30 days." **No on-premises, self-hosted,
single-tenant, or customer-VPC option is published anywhere.**

**Real-time vs post-call.** Post-call. See finding 1 above. Gong Assistant (the
successor to AI Ask Anything) is documented as arriving "on the call page in
March 2026" -- a post-call surface requiring a Foundation seat. The October 2025
Revenue AI OS announcement added AI Data Extractor, AI Deep Researcher, expanded
Ask Anything, and Gong Orchestrate; its "just-in-time guidance across customers'
buying journey" language refers to workflow orchestration, not in-call prompting.

**Diarization.** Yes. Gong's own documentation notes native Zoom recording gives
"better audio quality and more accurate speaker identification" than bot
recording, which implies bot capture degrades diarization. Language coverage is
marketed as 70+ languages. Reviewers report diarization failures specifically on
uploaded files: "Occasionally have to upload mp4 files and it is hit or miss at
splitting up voices."

**Overlaps with Backchannel.** Speaker-attributed transcription; automated
objection and topic detection; action-item extraction; post-call written
summaries; question-answering over past conversations (Gong Assistant vs
Backchannel's `POST /api/chat` across selected sessions); and audio import of
externally recorded calls (Gong's `add new call` API vs Backchannel's
`POST /api/sessions/{id}/import/audio`).

**What Backchannel lacks that Gong has.** Effectively the whole platform: CRM
sync and auto-population; deal, account, and pipeline objects; forecasting; call
library and shareable snippets; scorecards and AI Call Reviewer; talk-time and
team analytics; manager coaching workflow; multi-user access control of any kind;
calendar-driven auto-join; 70+ language coverage; mobile apps; every compliance
attestation; a large integration ecosystem; and 5,000 reference customers.

**What Gong lacks that Backchannel has.** Rep-facing guidance while the call is
happening; self-hosting; any deployment where audio does not enter a vendor
cloud; configurable per-agent models and prompts; MIT-licensed inspectable
source; a zero-dollar cost basis; and adoptability by one individual seller
without an org-wide contract and admin deployment.

**Recurring complaints (independently sourced).**
- *Cost*, the single most-cited negative: "It's a little bit expensive for
  everything it do"; "kinda expensive compared with other similar tools." Value
  for money is Capterra's lowest sub-score at 4.6/5.
- *Premium modules gated behind extra seat costs*: "Hidden Features: Premium
  features like Forecasting and Engage are behind additional seat costs."
- *Recorder timing*: "Sometimes the recorder doesn't join the meeting right away
  and will randomly join a few minutes in"; reviewers say it "throws off the
  groove of the call." And the inverse gap: "There is no option to invite the
  Gong recorder to a Zoom call already in progress."
- *Prospect opt-out*: "Prospects can opt out of recording" is a top listed
  frustration; Gong stops recording on non-consent.
- *Internal surveillance* (a distinct complaint class): "At first felt like big
  brother was watching"; "Management can definitely use as a tool to
  micro-manage"; "anyone at your company can listen to the call/recording."
- *Transcription accuracy*: "The auto transcription isn't always accurate";
  degrades on accents, dialects, jargon, and low-quality audio.
- *Latency*: "Calls take a long time to import and can frustrating when looking
  for immediate feedback."
- *Search reliability*: "The search doesn't always work when searching for a
  specific keyword."
- *Admin burden*: weakest measured capabilities are Ease of Customization
  81/100, Ease of Data Integration 84/100, Training 83/100.

**Positive consensus.** Call recording, playback, and film-room coaching are
best-in-class; strong Salesforce/Zoom/Outreach integration; eliminates manual
note-taking; easy end-user adoption; 95% plan to renew.

**Sources.** gong.io/pricing; help.gong.io docs for web-conferencing-integrations,
listen-to-a-call, introduction-to-coaching, plans-and-seats,
uploading-calls-from-a-non-integrated-telephony-system,
ai-ask-anything-is-evolving-into-gong-assistant,
faqs-for-security-privacy-and-compliance, data-retention-policy;
gong.io/language-support; gong.io/trust-center; gong.io press 2026-05-12;
vendr.com/marketplace/gong; capterra.com Gong reviews;
softwarereviews.com Gong.

### Clari Copilot (formerly Wingman)

**Corporate status change -- handle carefully.** Clari and Salesloft completed a
merger announced **2025-12-03**, with Steve Cox as CEO of the combined
organization; `assurance.clari.com` now redirects to `trust.salesloft.com`,
branded "Clari/Salesloft Trust Center." The merger announcement does not mention
Clari Copilot by name, describing instead a unified "Predictive Revenue System."
Clari Copilot still exists as a marketed product at clari.com/products/copilot/
and still carries published Capterra pricing, but **the roadmap risk is real and
any page must be dated**. This also means Salesloft Conversations is now the same
vendor, not a separate peer.

**Positioning and ICP.** The conversation-intelligence module of the Clari
revenue platform. Clari's Copilot page leads with "Real-time transcription,
instant insights, and live battlecards empower reps to respond to objections"
and claims to "increase win rates by 20%+." Clari's pricing page takes a direct
swipe at Gong: the platform is priced "with no extra platform fees for
integrations or continuous support."

**Pricing (as of 2026-07-24).** Clari publishes no prices. Capterra lists two
Clari Copilot tiers: **Accelerator at $1,080 per user per year** (activity
dashboard, call sharing, snippet creation and sharing, custom bot name, smart
summaries) and **Enterprise at $1,320 per user per year** (advanced security, API
access, coaching as a service, dedicated CSM, SSO and SAML). Free trial, no free
version, no credit card required, no stated seat minimum. Vendr (n = 287
purchases, last updated February 2026) reports a **median contract value of
$75,488**, range $18,931-$408,424, average savings 14.71%, volume discount
thresholds at 50/100/250 users, 2-3 year commitments pushed by the vendor,
annual escalation clauses typically 5-8%, and -- specific to Copilot -- **data
storage overages**. The Vendr figure spans the whole Clari platform, not Copilot
standalone.

**Capture model.** A bot plus a desktop app. The "Copilot Notetaker will
automatically join any external call on your calendar" for Zoom, Teams, and
Google Meet; it joins when the meeting organizer joins and leaves when the
organizer leaves; meetings can be added manually by pasting a URL. Clari's own
community documentation warns admins to ensure the bot is not "left in the
waiting room too long," is admitted to the room, and that "nobody kicks it out
midway," and notes it auto-leaves after 10 minutes of silence. **"Custom bot
name" being a paid-tier feature tells you the bot's visibility is a known
friction point.**

**Where data is processed.** Clari's cloud. Clari's own pages do not state
regions; the merged Salesloft security page states platforms run on AWS and GCP
"in the US and the EU" but does not mention Clari or Copilot, so EU residency for
Copilot workloads is **not confirmed**. Certifications published: SOC 2 Type II,
ISO 27001, ISO 27701, CSA, GDPR/CCPA, EU-US/UK/Swiss DPF. **No FedRAMP and no
HIPAA** -- a third-party aggregator claims both, but no Clari or Salesloft page
supports it and the same aggregator quotes Clari's MSA saying the Services are
"not intended to comply with HIPAA." Model training: Clari's privacy policy
carries the broadest statement of the three -- "Clari does not use, or allow our
vendors to use, the data collected through these interactions to train or
improve any AI models." Retention is admin-configurable from 30 days to 5 years.
No self-hosted option.

**Real-time vs post-call.** The one genuine real-time competitor among the
original three, with a significant asterisk. "Clari Copilot populates relevant
information on screen, in real time, when certain trigger phrases are spoken by
buyers" -- the pricing card fires on "too expensive," "cost," "budget," "ROI."
Clari Labs claims sellers using real-time battlecards "see 10% more wins, on
average" (Clari's own data, June 2023, methodology not independently
verifiable). **The asterisk: live battlecards require the desktop app.** Per
Clari's own community documentation, "Calls that go through the desktop app are
transcribed in real-time, allowing for features like battle cards to detect
specific words and trigger relevant cue cards during the call," whereas for
calls without the app transcription happens only after completion and "battle
cards and monologue alerts are disabled for such calls." The bot alone does not
get you real-time.

**Diarization.** Yes, but it is the weakest of the group by reviewer account --
see complaints.

**Overlaps with Backchannel.** The heaviest overlap of any target: live in-call
objection support, live transcription, monologue and talk-balance alerts, and a
desktop capture path running on the seller's own machine.

**What Backchannel lacks that Clari Copilot has.** CRM auto-capture of intent,
objections, contacts and next steps; buyer signals feeding forecasting and
pipeline inspection; Gametapes and Playbooks (call library and enablement
content); coaching-as-a-service; SSO/SAML; a battlecard authoring UI with
document-derived Smart Battlecards; admin-configurable retention; mobile; and
compliance attestations.

**What Clari Copilot lacks that Backchannel has.** Self-hosting; audio that never
leaves your machine; generative situation-specific objection responses rather
than pre-authored cards on keyword triggers; configurable per-agent models and
prompts; open source; and free.

**The mechanism difference is the whole argument.** A Clari battlecard is content
a human, or RevAI extracting from an uploaded document, authored in advance,
displayed when a configured trigger phrase is detected. Backchannel's
`objection_handler` sends the trailing 90 seconds of real transcript to a
low-latency model (`gemini-3.5-flash-lite` by default) with a prompt requiring
both a `response_now` -- "1-2 conversational sentences the user could say in the
next ten seconds" -- and a `bigger_picture` naming the underlying concern (cost
justification, risk aversion, change fatigue, competing priority, missing
stakeholder, past failure) plus the strategic angle for later in the call. It
also carries meeting context, the speaker roster, active directives, and a
do-not-repeat list of recently surfaced objections. Keyword triggers cannot do
that; they fire on "budget" regardless of what was actually said. **The honest
counterpoint, which the page must state: a curated battlecard is deterministic
and enablement-approved, and an LLM is neither.**

**Recurring complaints (independently sourced).**
- *Transcription accuracy is the #1 complaint by volume and worse than Gong's*:
  "The call transcription is quite poor to be honest"; "The transcript, often it
  doesn't pick the right words"; non-native speakers are a specific failure mode
  ("Words are not identified if it is not a native speaker"); speaker
  misattribution: "It doesn't always recognise the right person on the call as
  speaking."
- *The bot is disruptive and hard to remove*: "Wingman pops at random times
  during calls and becomes a bit of distraction"; "Call recording announcement
  kicks in randomly"; and the sharpest quote in the entire research set: **"Wish
  it was faster to kick off Wingman from a call when a customer doesn't want to
  be recorded."**
- *Bot reliability*: "Sometimes it doesn't join the meetings and you need to add
  it manually"; "Sometimes, even if you add them manually it still doesn't join."
- *Latency*: "there can be long delays in processing audio and transcription."
- *Access control confusion in both directions*: "Not possible to restrain who is
  going to watch the recording" alongside "I dislike that Wingman won't allow
  users to listen in on other co-workers calls." Role-based access scores 75/100.
- *Weakest measured capabilities*: Mobile Support 71/100, Breadth of Features
  72/100, Product Strategy and Rate of Improvement 73/100. Cost-relative-to-value
  77%, the lowest of the three originals.

**Positive consensus.** Cheaper than Gong and Chorus -- the recurring stated
reason for choosing it -- plus game-tape clipping and sharing, easy onboarding,
and the highest ease-of-use sub-score in the group at 4.8/5.

**Ratings.** Capterra 4.7/5 across 314 reviews. SoftwareReviews composite
7.6/10 across only 35 reviews -- the weakest composite of the three originals.

**Sources.** clari.com/products/copilot; clari.com/pricing; clari.com/privacy;
clari.com/gdpr; clari.com/security; clari.com/blog/clari-labs-battlecards;
community.clari.com desktop app post (2023-05-09) and battlecards best-practices
post and mistakes-to-avoid post; clari.my.site.com Copilot recording and
retention articles; salesloft.com/company/newsroom/clari-salesloft-merger;
trust.salesloft.com; capterra.com/p/194117/Wingman/pricing and reviews;
vendr.com/marketplace/clari; softwarereviews.com Clari Copilot.

### Chorus by ZoomInfo (formerly Chorus.ai)

**Positioning and ICP.** Acquired by ZoomInfo in 2021 for a widely reported ~$575M
and now sold as a module of the ZoomInfo go-to-market platform rather than
standalone. The natural buyer is a team already committed to ZoomInfo data.
Multiple 2026 reviews observe the standalone roadmap has slowed; SoftwareReviews
scores Product Strategy and Rate of Improvement at 78/100, among its lowest
measured capabilities.

**Pricing (as of 2026-07-24).** Not published; all figures are quote-based. Vendr
reports ZoomInfo (Chorus is an add-on module) at a **median ACV of $33,500/yr
across 1,012 deals**, range $7,200-$155,460, with auto-renewal escalation
commonly 5-10%/yr, "restricted seat adjustment rights," and average savings of
**21.81%** -- the largest discount gap of the group, implying the most inflated
opening quotes. **This is the weakest pricing evidence of the four targets; any
Chorus per-seat number must be hedged or omitted.**

**Capture model.** A recorder joins meetings as a participant on Zoom, Teams, and
Meet; there is additionally a native Zoom path that fires Zoom's own recording
notification, a post-meeting import path from Zoom cloud recordings, manual
recording import, and a mobile app. ZoomInfo's help center is JavaScript-rendered
and returned only error shells to direct fetch, and the implementation-guide PDF
would not parse, so bot mechanics are medium confidence.

**Where data is processed.** ZoomInfo's cloud, **US only**: "Our services are
hosted on the three major cloud providers with hosting data centers in the U.S."
No EU residency option is published anywhere on ZoomInfo's site -- the sharpest
compliance wedge across the group, given Gong publishes a real US-or-EU choice.
Certifications named on the security overview: ISO 27001, ISO 27701, TRUSTe, SOC
2 Type II. **No statement about using customer data to train AI models exists
anywhere** -- not on the security overview, trust center, Chorus product pages,
or zoominfo.com/ai-information -- while ZoomInfo's own marketing describes a
"machine learning feedback loop." The absence of a no-training commitment is
itself the finding. Retention on termination is not published. No self-hosted
option.

**Real-time vs post-call.** Post-call, despite the marketing word. The exact
claim is that Chorus "records, transcribes, and analyzes your calls using cutting
edge proprietary technology that delivers in real-time -- so you can access call
insights within minutes after your call ends." No rep-facing live guidance is
documented.

**Diarization.** Yes, and marketed aggressively: "Industry-First Same Room
Speaker Separation: Identify multiple speakers in the same room." Reviewer
sentiment on accuracy is genuinely split -- some praise accents and crosstalk
handling; others report "misattributed statements" and "participant
identification gaps," with one independent reviewer measuring 80-90% accuracy,
"good enough for gist, not for verbatim quotes."

**Overlaps with Backchannel.** Speaker-separated transcription; topic and
competitor-mention detection; action items and next steps; post-call summaries;
recording import.

**What Backchannel lacks that Chorus has.** Salesforce activity logging;
scorecards; deal and relationship intelligence; market and competitor
intelligence rollups; email capture alongside calls; ZoomInfo contact enrichment
on every call participant (genuinely unique); a compliance center; mobile apps.

**What Chorus lacks that Backchannel has.** Anything in-call; self-hosting; open
source; agent configurability; EU data residency; a published no-model-training
commitment; and standalone purchasability at a sane price for a small team.

**Recurring complaints.** Contract and auto-renewal conduct is the
best-documented complaint of anything in this research, and it is a
ZoomInfo-corporate problem rather than a Chorus-product one: a shareholder
derivative suit alleged leadership concealed "manipulative and coercive"
auto-renewal strategies, and a March 2022 Washington State AG complaint describes
a small business locked into a $27,000 renewal by "hidden language about an
auto-renewal policy requiring customers to cancel 60 days in advance." Related
securities class actions were filed on the same disclosure theory. Product-level
complaints: latency ("AI summaries take excessive time to process"), recording
reliability ("Recordings occasionally lost due to unforeseen bugs"), cumbersome
call removal ("Disengaging Chorus from a call can be a cumbersome process"),
limited customization (Ease of Customization 78/100), tedious keyword setup,
weakest vendor support of the three (78/100), and post-acquisition stagnation.

**Ratings.** Capterra 4.5/5 across only 67 reviews; SoftwareReviews composite
8.3/10 across 358 reviews with plan-to-renew 98/100 -- the highest renewal intent
of the group, which sits in genuine tension with the auto-renewal allegations and
may partly reflect them.

**Assessment.** The weakest of the four as a comparison target: no longer
independently marketed, least verifiable pricing, and the buyer is usually inside
a ZoomInfo decision rather than a conversation-intelligence decision. Does not
warrant its own page.

**Sources.** zoominfo.com/products/chorus and /call-recording;
zoominfo.com/legal/security-overview; zoominfo.com/ai-information;
trust.zoominfo.com; vendr.com/marketplace/zoominfo; capterra.com Chorus reviews;
softwarereviews.com Chorus by ZoomInfo; Bloomberg Law and Washington State AG
reporting on ZoomInfo renewals.

### Attention (attention.com) -- the added peer

**Why it is included.** The brief allows one addition if genuinely important. The
selection criterion is which product most directly competes on live, in-call,
seller-side assistance. Attention is the only vendor found with vendor-primary
during-call battlecard language *and* current commercial momentum: a **$30M
Series B led by RTP Global announced 2026-06-24** (~$46.9M total raised), **500+
customers** including Abridge, Scale, Lovable, Preply, and BambooHR, 4x ARR YoY,
and roughly 94 employees. It is the name a buyer evaluating Gong, Clari Copilot,
and Chorus in late 2026 is most likely to also have on the shortlist. Sybill --
the other candidate named in the brief -- was evaluated and **rejected**: it is
post-call only, with no live guidance anywhere on its site, and commercially flat
(no funding since March 2024, ~54 employees). Its one interesting property,
bot-free desktop capture, is worth one line of prior-art acknowledgement, not a
column.

**Positioning and ICP.** "The AI system that runs revenue teams, not just records
them." Founded 2021, New York. Sells to AEs and sales leaders.

**Pricing.** **Not published.** Book-a-demo only. This is the main reason it does
not merit a comparison page: an honest price row cannot be written.

**Capture model.** A meeting bot, built on the third-party Recall.ai
bot-as-a-service across Zoom, Meet, and Teams, plus Zoom Phone. So Attention's
real-time capability arrives via a recorder in the participant list operated by a
fourth party.

**Where data is processed.** Attention's cloud, plus Recall.ai in the capture
path. No meaningful published compliance posture was found. No self-hosted
option.

**Real-time vs post-call.** Genuinely real-time, on vendor-primary pages: "AI
powered battlecards help you answer any prospect question while on the call" and
"Never face an objection alone" on the sales-reps solution page; "Real-time
objection handling" and "Real-time coaching" on the sales-leaders page.
**Important caveat for the writer:** Attention's 2026 positioning has drifted
toward agentic post-call automation -- the Series B release quotes CEO Anis
Bennaceur saying "Most software in this space watches the call and writes up what
happened. We take the next best action," and the homepage headline is now
"Sellers get feedback minutes after every single call." Real-time is still
shipped and marketed, but it is no longer the headline. Cite the solutions pages,
with the date.

**Overlaps with Backchannel.** Live in-call battlecards and objection handling;
live transcription; automatic action items.

**What Backchannel lacks that Attention has.** CRM write-back and 1-click CRM
updates; agentic post-call workflow automation; funded product velocity; a
managed service.

**What Attention lacks that Backchannel has.** Self-hosting; bot-free capture;
open source; published pricing; agent and prompt configurability; and any
published deployment or data-processing story.

**Sources.** attention.com/solutions/sales-reps; attention.com/solutions/sales-leaders;
attention.com/integrations/zoom; PRNewswire Series B 2026-06-24;
recall.ai/customers/attention.

## Overlap and novelty matrix

| Dimension | Gong | Clari Copilot | Chorus (ZoomInfo) | Attention | Backchannel |
| --- | --- | --- | --- | --- | --- |
| Category | Revenue AI platform | CI module of a revenue platform (Clari/Salesloft) | CI module of a GTM data platform | Agentic revenue AI, real-time capable | Live seller-side meeting assistant |
| Published price | None (per-user + platform fee) | $1,080-$1,320/user/yr (Capterra) | None | None | $0 (MIT) + your own API usage |
| Independent contract data | Median ACV $54,900 (Vendr, n=1,126) | Median ACV $75,488 platform-wide (Vendr, n=287) | ZoomInfo median ACV $33,500 (Vendr, n=1,012) | None | N/A |
| Contract | Annual prepay; multi-year common | Annual per-user; 2-3 yr pushed | Annual, bundled, auto-renew | Unknown | None |
| Seat minimum | None per Gong docs; 10-15 typical per Vendr | None stated | Not sourced | Unknown | None |
| Capture | Bot on all platforms; native Zoom only | Bot notetaker + desktop app | Recorder + native Zoom + import + mobile | Bot via third-party Recall.ai | Browser capture of mic + tab/system audio; nothing joins |
| Recorder visible to prospect | Yes (unless native Zoom) | Yes (custom bot name is a paid feature) | Yes | Yes | No |
| Can be ejected mid-call cleanly | Cannot be added mid-call | Reviewers say removal is slow | "Cumbersome process" per reviewers | Unknown | Nothing to eject |
| Where audio is processed | Gong cloud (AWS), US or EU choice | Clari cloud; region not confirmed for Copilot | ZoomInfo cloud, **US only** | Attention cloud + Recall.ai | Your machine; diarization always local; transcription local or via your API key |
| No-model-training commitment | Yes, scoped to generative models | Yes, broadest wording of the group | **None published** | Not found | N/A -- you choose the provider and key |
| Self-hosting | No | No | No | No | Yes, Docker Compose or desktop bundle |
| Live in-call rep guidance | No (manager listen-in only) | Yes, desktop app only, trigger-phrase cards | No | Yes, battlecards | Yes, generative, every 10s over trailing 90s |
| Objection mechanism | Post-call detection and review | Pre-authored cards on keyword triggers | Post-call detection | Battlecards (mechanism not published) | LLM reasoning over live transcript; emits response_now + bigger_picture |
| Diarization | Yes, 70+ languages | Yes, weakest by reviewer account | Yes, incl. same-room separation | Yes | Yes, local Silero VAD + WeSpeaker ResNet152 ONNX |
| CRM sync | Yes, deep | Yes | Yes | Yes | No |
| Forecasting / pipeline | Yes | Yes (Clari core) | Partial | Partial | No |
| Scorecards / call library | Yes | Yes (Gametapes, Playbooks) | Yes | Partial | No |
| Team analytics / manager rollup | Yes | Yes | Yes | Yes | No |
| Multi-user, roles, SSO | Yes | Yes (SSO/SAML at Enterprise) | Yes | Yes | **No -- no user model at all** |
| Compliance attestations | SOC 2 II, ISO 27001/17/18/701, ISO 42001, PCI, DPF, CSA | SOC 2 II, ISO 27001/27701, CSA, DPF; no HIPAA, no FedRAMP | ISO 27001/27701, SOC 2 II, TRUSTe | None found | None; architectural argument only |
| Open source | No | No | No | No | Yes, MIT |
| Agent/prompt configurability | No | Battlecard content only | No | No | Yes: per-agent model, prompt, interval |
| Individual seller can adopt alone | No | No | No | No | Yes |
| Offline / air-gapped operation | No | No | No | No | Partial -- Privacy First gives local transcription and diarization but disables all LLM agents |

### Late addition: Zoom Revenue Accelerator "Sales Assist" (GA 2026-07-22)

Surfaced by Lead C two days after GA and verified vendor-primary. It is the most
direct commercial analog to `objection_handler` found in this research, and it
strengthens rather than weakens the thesis: it is another pre-configured card
system, tied to one vendor's platform and licensing.

| Dimension | Zoom Sales Assist | Backchannel |
| --- | --- | --- |
| GA date | 2026-07-22 (Premium at launch; Essentials from August 2026) | Shipping since v0.1 |
| Published price | **$66/user/mo Essentials, $99.99/user/mo Premium, billed annually** -- the only competitor in this whole research with fully public real-time pricing | $0 |
| Live capability | "competitive intelligence, objection guidance, discovery prompts, battlecards, and configurable framework capture in real time" | objection_handler every 10s over trailing 90s, plus 4 more live agents |
| Mechanism | Admin pre-configures talking points per topic category; knowledge collections attached; rule-based live signals and timer reminders | Generated per objection from the actual transcript window |
| Platform lock | Requires a Pro/Business/Enterprise account plus a Zoom Workplace license with Phone, or a standalone Zoom Phone plan | Any meeting app; browser capture |
| Consumption model | Essentials meters Sales Assist usage; Premium is unlimited | No metering |
| Where processed | Zoom cloud | Your machine |

Notes for the writer. Zoom's is the **best-documented example of the
pre-authored pattern** in the entire research set, and unlike Clari it is
current (July 2026) rather than 2023-dated -- so **use Zoom, not Clari, as the
concrete illustration whenever the copy needs to show how the rest of the
category produces its in-call guidance.** Do not overstate the platform lock as
"Zoom Meetings only": the prerequisite is Zoom Phone licensing and the feature
spans Zoom sales conversations, and Zoom simultaneously shipped an MCP server to
push its intelligence into other tools. Cite "$66 to $99.99 per user per month,
billed annually, as of July 2026."

## Positioning recommendation

**Recommended page type for Gong: ecosystem fit, not alternative. The research
strongly supports the pre-made decision.** Four independent lines of evidence:

1. *Capability asymmetry is not close.* Backchannel has no CRM sync, no deal or
   pipeline object, no forecasting, no scorecards, no call library, no team
   analytics, and no user accounts. A "Gong alternative" page invites a
   feature-parity comparison Backchannel loses on roughly fifteen dimensions,
   against a product rated 4.8/5 on Capterra and 9.0/10 by Info-Tech with 95%
   renewal intent. The fireflies-alternative page works because Backchannel
   genuinely beats Fireflies on the axis that page is about. No such axis carries
   a whole Gong page.
2. *Search intent is mismatched.* The "gong alternatives" SERP is saturated by
   vendor listicles selling cheaper full CI platforms (Avoma, Jiminny, Chorus,
   Salesloft, tl;dv, and a long tail of AI-written competitor blogs). Buyers on
   that query want a cheaper Gong, not a different category. Ranking for it
   produces bounce, not conversion, and burns the credibility the honest-
   comparison template is built on.
3. *The obvious attack is unavailable.* Gong's published privacy posture -- US or
   EU AWS residency, SOC 2 II, ISO 27001/27017/27018/27701/42001, EU-US DPF,
   irreversible 30-day deletion on termination, and "your data is never used to
   train generative models" -- is stronger than most buyers assume. A page
   insinuating Gong is careless with audio would be false.
4. *The complementary story is technically real, not a rhetorical dodge.* Gong's
   public API exposes an `add new call` endpoint accepting WAV, MP3, MP4, MKV,
   and FLAC up to 1.5GB, explicitly for "uploading calls from telephony systems
   with which Gong does not have a pre-built integration," requiring
   `clientUniqueId` and `primaryUser`, minimum 60 seconds, rate-limited to 3
   req/s and 10,000/day. Backchannel already writes per-segment WAV to
   `DATA_DIR/audio/<session_id>/segment_<n>.wav` and serves it at
   `GET /api/sessions/{id}/segments/{n}/audio`. So "your Backchannel recordings
   can still land in Gong so the team's revenue record stays complete" is
   architecturally true. **Critical honesty constraint: no such integration is
   shipped.** The page must say this is possible via Gong's API and the recorded
   WAV files, and that building it is custom work. Do not imply a connector
   exists.

**Recommended page: `/gong-and-backchannel/`.** Angle: "Gong knows what happened.
Backchannel helps you while it is happening." Frame Backchannel as the live
seller-side layer beneath a team's post-call revenue intelligence platform, on
the seller's own machine, with no second bot in the room and no second contract.

**Target keywords and search intent.** Deliberately avoid "gong alternative."
Target question-intent and gap-intent where Backchannel is genuinely the right
answer:

- "does gong give real-time coaching during calls" / "does gong help during the
  call" -- question intent, answerable definitively from Gong's own docs, high
  AI-Overview and LLM-citation potential because the answer resolves cleanly.
- "real-time objection handling during sales calls" -- the core capability
  keyword, currently contested mostly by contact-center agent-assist vendors
  (Balto and peers) rather than B2B seller tools.
- "live sales coaching without a bot in the meeting" / "sales AI that does not
  join the call" -- the bot-aversion intent that already converts on the
  Fireflies page, and now backed by independently sourced complaints that all
  three incumbents handle mid-call consent badly.
- "self-hosted conversation intelligence" / "open source conversation
  intelligence" -- a genuinely unoccupied SERP; no self-hosted product exists in
  this category.
- "gong for individual sales reps" / "conversation intelligence for one person"
  -- the individual-adoption gap; none of the four can be bought by one seller.
- "sales call AI that keeps audio on my machine" -- privacy intent.

**The sharpest true differentiator (one sentence).** Backchannel is the only tool
in this comparison set that *generates* a specific suggested response to the
objection that was actually just raised, within seconds, on hardware you own,
with nothing joining the meeting -- Gong and Chorus tell you about the objection
after the call, and Clari Copilot, Attention, and Zoom Sales Assist surface
content that was prepared before the call started.

**Do not claim novelty, claim mechanism.** As of 2026-07-22 real-time in-call
objection guidance is purchasable from Clari, Attention, and Zoom, with Zoom
publishing a price for it. A page implying Backchannel invented live objection
help would be false and datable. The durable claim is generated-versus-prepared,
plus self-hosted-versus-cloud, plus no-recorder-in-the-room.

**The second differentiator, newly supported by independent evidence:** every
competitor's recorder is a meeting participant, so recording consent is an
all-or-nothing decision made before the call starts. Reviewers of Clari Copilot
and Chorus both complain that removing the bot mid-call when a prospect objects
is slow and awkward, and Gong reviewers complain the recorder cannot be invited
into a call already in progress. Backchannel's browser-side capture has nothing
to admit, nothing to eject, and nothing in the participant list.

**The honest concessions we must make, and must lead with rather than bury:**

1. **Backchannel is not a revenue intelligence platform and cannot replace one.**
   No CRM sync, no pipeline or forecast, no scorecards, no call library, no team
   analytics, no manager rollup, and -- most bluntly -- no user accounts, roles,
   or permissions of any kind. If your team runs on Gong, keep running on Gong.
2. **Privacy First mode and the live agents are mutually exclusive.** Local ONNX
   Whisper/Parakeet models carry `"supports_text": False` in the model registry,
   so Privacy First gives fully local transcription and diarization but turns off
   every LLM agent, including `objection_handler`. The realistic privacy-
   preserving configuration is local batch transcription plus a disabled
   `audio_gateway`, which keeps audio on your machine while transcript *text*
   still goes to Gemini or OpenAI on your own key. That is meaningfully better
   than shipping all audio to a vendor cloud, and it is not "nothing leaves." Say
   so plainly.
3. **No compliance attestations.** Gong, Clari/Salesloft, and ZoomInfo all
   publish certifications procurement recognizes; Gong's are the most extensive
   in the category and include ISO 42001 for AI management. Backchannel publishes
   source code. For some buyers that is stronger; for procurement it is usually
   weaker. Reuse the Fireflies page's paragraph.
4. **A generative objection response is not enablement-approved content.** Clari's
   curated battlecards are deterministic and reviewed; Backchannel's are neither.
   Concede it in the same breath as the differentiator.

**Framing guardrails for the writer.**
- Do not claim Backchannel replaces Gong. Do not claim a Gong integration exists.
- Do not use a slug or H1 that reads as an alternatives page.
- Do not cite Gong contract terms (multi-year lock-in, renewal uplifts, no seat
  true-down, platform fee dollar ranges) as fact from competitor blogs. Use
  Gong's own "per user plus a platform fee" language, or Vendr's median ACV and
  seat-band data, both of which are defensible.
- **Do not use the "big brother" / manager-surveillance complaint.** It is real
  and independently sourced from Capterra, but leaning on it positions
  Backchannel as shadow IT and surveillance evasion, which directly contradicts
  an ecosystem-fit page and is a brand risk. Skip it.
- Date every pricing and corporate-status claim, and note the Clari/Salesloft
  merger on any Clari Copilot page.

## Page recommendation and priority

| Target | Decision | Rationale | Effort |
| --- | --- | --- | --- |
| **Gong** | **BUILD** -- ecosystem-fit page, priority 1 | Highest-authority name in the category, best keyword surface, and the only framing that is both true and credible. Also the page that best explains what Backchannel *is* to a sales reader, which the note-taker comparison pages do not. | ~1 day: one HTML page on the existing `site/` template, plus FAQPage and BreadcrumbList JSON-LD matching the Fireflies pattern, plus `site/llms.txt` and footer-compare updates. |
| **Clari Copilot** | **BUILD** -- head-to-head comparison page, priority 2 | The only original target that is truly real-time, and the mechanism difference (generative vs trigger-phrase battlecards, desktop-app-only) is a sharp, verifiable argument Backchannel wins. It is also the only target with published per-seat pricing, which makes an honest price row possible, and it has the worst independently sourced transcription-accuracy and bot-friction complaints in the category. | ~1 day, same template. Must concede that curated battlecards are deterministic and enablement-approved, and must date the Clari/Salesloft merger status. |
| **Chorus (ZoomInfo)** | **FOLD IN** -- one matrix row on the Gong page plus a short "what about Chorus" paragraph | No longer independently marketed, least verifiable pricing, buyer is inside a ZoomInfo decision. A standalone page would rank thinly and force unsourceable claims. Its one genuinely sharp fact -- US-only hosting with no published no-model-training commitment -- fits neatly in a row. | ~1 hour within the Gong page. |
| **Attention** | **FOLD IN** -- matrix row plus two sentences on the Clari Copilot page | Genuinely the closest live competitor and commercially hot, but it publishes no pricing (no honest price row possible), has no published compliance posture, and is mid-pivot toward post-call agentic automation -- a dedicated page would age badly within two quarters. | ~1 hour within the Clari page. Revisit in 6 months. |
| **Sybill** | **SKIP** | Post-call only; fails the live-assistance selection criterion. Commercially flat. Worth at most one line acknowledging bot-free desktop capture as prior art. | -- |

**Sequencing.** Build Gong first; it establishes the category vocabulary
("revenue intelligence," "conversation intelligence," "in-call vs post-call")
that the Clari Copilot page reuses and internally links to. Add both to the site
footer `footer-compare` block and to `site/llms.txt` under `## Compare`. Two
well-sourced pages beat four thin ones.

**Worth considering later, not now.** A non-versus **capability page** on
real-time in-call objection handling would target the strongest keyword cluster
found in this research without naming a competitor, would not age when vendors
pivot, and would consolidate the live-assistance story that is currently split
across the Fireflies page and these two proposed pages. Recommend this as the
follow-up to the two comparison pages rather than a fifth versus page.

## QA/QC pass

Access date is 2026-07-24 for every row. "Vendor-primary" means the vendor's own
site, help center, or trust center. "Independent" means a review platform,
procurement marketplace, or news source with no stake in the comparison.
"Competitor-blog" means a page operated by a company selling against the product
described; those are structurally biased and marked do-not-publish.

Standing caveats that apply to the whole table: g2.com and reddit.com were
blocked to the fetcher; TrustRadius product pages returned HTTP 403, so any
TrustRadius figure below is from a search snippet and is second-hand; Capterra,
SoftwareAdvice, and GetApp share one Gartner Digital Markets review pool and are
**one** dataset, not three corroborating ones; ZoomInfo's help center is
JavaScript-rendered and returned error shells; the Chorus implementation-guide
PDF would not parse.

### Claim verification table

| # | Claim | Source | Type | Verified | Confidence |
| --- | --- | --- | --- | --- | --- |
| 1 | Gong publishes no prices; "Licenses are priced per user"; "There is a platform fee based on the number of users supported" | gong.io/pricing/ | vendor-primary | Yes | High |
| 2 | Gong median ACV $54,900, n=1,126, range $11,352-$204,036, savings 14.17%, per-seat $1,200-$2,400/yr by band, typical seat minimums 10-15, 5-10% renewal escalation, modules +20-40% | vendr.com/marketplace/gong (updated March 2026) | independent | Yes | High for median/ranges; Medium for the qualitative terms |
| 3 | Gong's own docs state no minimum seat requirement; unassigned members are free "Collaborators" | help.gong.io/docs/plans-and-seats | vendor-primary | Yes | High. **Note the conflict with row 2** -- present both, do not assert one |
| 4 | Gong bot recording adds "a virtual participant," available for all web conferencing integrations; native recording has "no additional participant added" and is "only available with Zoom" | help.gong.io/docs/web-conferencing-integrations | vendor-primary | Yes | High |
| 5 | Gong live manager listen-in/join on ON AIR calls, max 2 listeners, not registered as participants; no AI guidance on that page | help.gong.io/docs/listen-to-a-call | vendor-primary | Yes | High |
| 6 | Gong coaching is post-call (Feedback Request, comments, sharing, scoring, AI Call Reviewer); zero references to real-time or in-call rep guidance | help.gong.io/docs/introduction-to-coaching | vendor-primary | Yes | High |
| 7 | Gong Assistant requires a Foundation seat and "will be available on the call page in March 2026" | help.gong.io/docs/ai-ask-anything-is-evolving-into-gong-assistant | vendor-primary | Yes | High |
| 8 | Gong `add new call` API accepts WAV/MP3/MP4/MKV/FLAC to 1.5GB; requires clientUniqueId and primaryUser; min 60s; 3 req/s and 10,000/day limits; intended for non-integrated telephony | help.gong.io/docs/uploading-calls-from-a-non-integrated-telephony-system | vendor-primary | Yes | High |
| 9 | Gong supports 70+ languages | gong.io/language-support | vendor-primary | Yes | Medium-high -- marketing figure; per-feature coverage not broken out and other Gong pages reference 30+ |
| 10 | Gong ARR past $500M, 55%+ YoY, "more than 5,000 companies"; released 2026-05-12 | gong.io/press/gong-growth-accelerates-past-55-yoy-arr-tops-500m | vendor-primary | Yes | High |
| 11 | Gong data stored in US or EU AWS data centers, US default; processed in US, Israel, Ireland; sub-processors US/UK/EMEA; SOC 2 II, ISO 27001/27017/27018/27701, EU-US DPF, CSA STAR; no on-prem option mentioned | help.gong.io/docs/faqs-for-security-privacy-and-compliance | vendor-primary | Yes | High |
| 12 | Gong: "your data is never used to train generative models"; ISO 42001 certified | gong.io/trust-center | vendor-primary | Yes | High. Note the wording is scoped to *generative* models |
| 13 | Gong retention default is the lesser of 3 years or the customer relationship; "If you cease being a Gong customer, your data will be irreversibly deleted in 30 days" | help.gong.io/docs/data-retention-policy | vendor-primary | Yes | High |
| 14 | Gong Capterra 4.8/5, 561 reviews, value-for-money lowest sub-score at 4.6 | capterra.com/p/157969/Gong-io/reviews/ | independent | Yes | High |
| 15 | Gong SoftwareReviews composite 9.0/10, 199 reviews, 95% plan to renew, NEF +93; weakest capabilities Ease of Customization 81, Data Integration 84, Training 83 | softwarereviews.com/products/gong | independent | Yes | High |
| 16 | Gong TrustRadius 9.1/10, ~1,128 reviews | trustradius.com/products/gong-io/reviews | independent (snippet) | Partial -- page 403s | Medium |
| 17 | Gong reviewer complaints: cost, late-joining recorder, cannot add recorder to in-progress call, prospect opt-out, transcription accuracy, search reliability, module gating | capterra.com Gong reviews (multiple pages); softwareadvice.com Gong profile | independent | Yes | High (direct verbatim quotes) |
| 18 | Gong reviewer complaints about internal surveillance and weak internal access control ("big brother," "anyone at your company can listen") | capterra.com/p/157969/Gong-io/reviews/?page=5, ?page=8 | independent | Yes | High for the quotes; **flagged do-not-use for brand reasons, see guardrails** |
| 19 | Gong Oct 2025 announcement: AI Data Extractor, AI Deep Researcher, expanded Ask Anything, Gong Orchestrate; MCP support | gong.io/blog/new-product-announcements-gong-revenue-ai-operating-system; PRNewswire 2025-10-21 | vendor-primary | Yes for the feature list | High for features; Medium for the interpretation that "just-in-time guidance" is not in-call |
| 20 | Gong contract terms: mandatory $5K-$50K platform fee, 15-seat minimum, $15K-$65K implementation, 5-15% renewal uplifts, no seat true-down | sybill.ai, claap.io, oliv.ai, marketbetter.ai, revenuegrid.com, tldv.io | competitor-blog | **No** | **Low -- DO NOT PUBLISH.** Contradicted in part by Gong's own plans-and-seats page |
| 21 | Gong "support collapsed post-2024, tickets take weeks" | sybill.ai, oliv.ai | competitor-blog | **No** | **Low -- DO NOT PUBLISH.** Capterra rates Gong support 4.7/5 |
| 22 | Gong processes a call in 20-30 minutes | competitor blogs; not found in Gong's help center | competitor-blog | **No** | **Low -- DO NOT PUBLISH.** Reviewer complaints about slowness are real and citable; the number is not |
| 23 | Clari and Salesloft merger announced 2025-12-03, Steve Cox CEO of the combined organization; announcement does not name Clari Copilot | salesloft.com/company/newsroom/clari-salesloft-merger | vendor-primary | Yes | High |
| 24 | assurance.clari.com redirects to trust.salesloft.com, branded "Clari/Salesloft Trust Center" | observed redirect | vendor-primary | Yes | Medium-high (single observation) |
| 25 | Clari Copilot: "Real-time transcription, instant insights, and live battlecards empower reps to respond to objections"; claims "increase win rates by 20%+" | clari.com/products/copilot/ | vendor-primary | Yes | High for the quote; the 20% figure is their marketing claim -- attribute it |
| 26 | Clari Copilot Accelerator $1,080/user/yr, Enterprise $1,320/user/yr; free trial, no free version, no stated seat minimum | capterra.com/p/194117/Wingman/pricing | independent (listing) | Yes | Medium -- listings lag vendor changes; label "list pricing as of mid-2026, verify with Clari" |
| 27 | Clari median ACV $75,488, n=287, range $18,931-$408,424, savings 14.71%, 2-3 yr terms pushed, 5-8% escalation, Copilot-specific storage overages; figure spans the Clari platform not Copilot alone | vendr.com/marketplace/clari (updated Feb 2026) | independent | Yes | High for the figures, High for the caveat |
| 28 | Clari battlecards fire on trigger phrases: "populates relevant information on screen, in real time, when certain trigger phrases are spoken by buyers"; pricing card triggers on "too expensive", "cost", "budget", "ROI"; posted 2023-06-22 | clari.com/blog/clari-labs-battlecards/ | vendor-primary | Yes | High for the quote. **Post is from 2023 -- re-check before publish** |
| 29 | Live battlecards require the desktop app: "Calls that go through the desktop app are transcribed in real-time... battle cards to detect specific words and trigger relevant cue cards during the call"; without it, "battle cards and monologue alerts are disabled for such calls"; posted 2023-05-09 | community.clari.com desktop app announcement | vendor-primary (community) | Yes | Medium-high. **2023 post and load-bearing for the whole Clari page -- re-verify immediately before publish** |
| 30 | Battlecards are manually authored, or Smart Battlecards derived by RevAI from an uploaded file; best practice "Define specific keywords that will activate your cards" | community.clari.com battlecards best-practices post | vendor-primary (community) | Yes | Medium-high |
| 31 | Copilot Notetaker bot auto-joins external calendar calls on Zoom/Teams/Meet, joins and leaves with the organizer, can be invited by URL; admins warned it may be left in a waiting room or kicked out midway; auto-leaves after 10 min silence | clari.my.site.com and community.clari.com recording articles | vendor-primary | Yes | Medium-high (some Clari pages are JS-rendered; parts obtained via snippets) |
| 32 | Clari privacy policy: "Clari does not use, or allow our vendors to use, the data collected through these interactions to train or improve any AI models" | clari.com/privacy/ | vendor-primary | Yes | High |
| 33 | Clari Copilot retention configurable 30 days to 5 years | clari.my.site.com Copilot Data Retention Policy | vendor-primary | Yes | Medium-high |
| 34 | Clari/Salesloft publish SOC 2 II, ISO 27001, ISO 27701, CSA, GDPR/CCPA, DPF; no FedRAMP, no HIPAA | clari.com/security/, trust.salesloft.com, salesloft.com/security-compliance | vendor-primary | Yes | Medium-high. A third-party aggregator claims FedRAMP and HIPAA; **rejected** -- no vendor page supports it and the same aggregator quotes Clari's MSA saying the Services are "not intended to comply with HIPAA" |
| 35 | EU data residency for Clari Copilot workloads | salesloft.com/security-compliance says AWS/GCP "in the US and the EU" but does not mention Clari or Copilot | vendor-primary (inconclusive) | **No** | **Low -- do not claim EU residency for Copilot either way** |
| 36 | Clari Copilot Capterra 4.7/5, 314 reviews, ease-of-use 4.8; SoftwareReviews composite 7.6/10 on only 35 reviews, cost-value 77%, Mobile 71, Breadth 72, Strategy 73 | capterra.com/p/194117/Wingman/reviews/; softwarereviews.com/products/clari-copilot | independent | Yes | High |
| 37 | Clari Copilot complaint quotes: transcription accuracy, non-native speaker failures, speaker misattribution, "Wingman pops at random times during calls," "Wish it was faster to kick off Wingman from a call when a customer doesn't want to be recorded," bot fails to join, processing delays | capterra.com and softwareadvice.com Wingman reviews (multiple pages) | independent | Yes | High (direct verbatim quotes) |
| 38 | Clari Copilot standalone $120-$160/user/mo, bundled $400+/user/mo; Growth ~$720/user/yr; $15,000-$75,000 professional services | marketbetter.ai, agenticsalescall.com, outdoo.ai, oliv.ai, docket.io, leadhaste.com | competitor-blog | **No** | **Low -- DO NOT PUBLISH** |
| 39 | Chorus acquired by ZoomInfo in 2021 for ~$575M; now sold within the ZoomInfo platform | zoominfo.com/products/chorus; pipeline.zoominfo.com | vendor-primary for packaging | Yes for packaging | High for packaging; Medium for the exact $575M figure (widely reported, not re-verified against the 2021 filing) |
| 40 | Chorus "delivers in real-time -- so you can access call insights within minutes after your call ends" | zoominfo.com/products/chorus/call-recording | vendor-primary | Yes | High -- the strongest evidence Chorus is post-call |
| 41 | Chorus markets "Industry-First Same Room Speaker Separation" | zoominfo.com/products/chorus/call-recording | vendor-primary | Yes | High that the claim is made; "industry-first" is theirs, not ours |
| 42 | ZoomInfo hosting: "Our services are hosted on the three major cloud providers with hosting data centers in the U.S."; no EU residency published; certifications ISO 27001, ISO 27701, TRUSTe, SOC 2 II; **no AI-training statement anywhere** | zoominfo.com/legal/security-overview; trust.zoominfo.com; zoominfo.com/ai-information | vendor-primary | Yes | High for hosting and certifications; High for the absence of a training statement across the pages checked, though absence is inherently harder to prove -- phrase as "publishes no commitment" |
| 43 | Chorus captures via a recorder joining the meeting as a participant | search snippets + independent roundups; help.zoominfo.com JS-rendered, PDF unparseable | mixed | Partial | **Medium -- phrase as "a Chorus recorder joins the meeting"; avoid specific bot-naming claims** |
| 44 | Chorus supports post-meeting import from Zoom cloud recordings | help.zoominfo.com article "How to Set Up Meeting Import with Chorus" (slug: How-to-Set-Up-Post-Meeting-Downloading-with-Chorus-and-Zoom); body not fetchable | vendor-primary (title/slug only) | Partial | Medium |
| 45 | ZoomInfo median ACV $33,500, n=1,012, range $7,200-$155,460, savings 21.81%, 5-10% renewal escalation, restricted seat adjustment | vendr.com/marketplace/zoominfo | independent | Yes | Medium-high |
| 46 | ZoomInfo auto-renewal conduct: shareholder derivative suit alleging "manipulative and coercive" auto-renewal strategies; March 2022 Washington State AG complaint describing a $27,000 renewal and "hidden language about an auto-renewal policy requiring customers to cancel 60 days in advance" | news.bloomberglaw.com; thebearcave.substack.com (FOIA-obtained complaints); ktmc.com and rosenlegal.com case filings | independent (legal trade press, investigative newsletter, law firm filings) | Yes | Medium-high. **Allegations, not findings -- if published, must be phrased as allegations with the source named.** Recommend omitting entirely; it is off-thesis for an ecosystem page |
| 47 | Chorus Capterra 4.5/5 on 67 reviews; SoftwareReviews composite 8.3/10 on 358 reviews, plan-to-renew 98/100, Vendor Support 78/100, Ease of Customization 78/100, Product Strategy 78/100 | capterra.com/p/253713/Chorus/reviews/; softwarereviews.com/products/chorus-by-zoominfo | independent | Yes | High |
| 48 | Chorus complaints: "AI summaries take excessive time to process," "Recordings occasionally lost due to unforeseen bugs," "Disengaging Chorus from a call can be a cumbersome process," "Inaccurate Transcription... misattributed statements" | capterra.com Chorus reviews; selecthub.com | independent | Yes | High for the quotes; Medium for selecthub as a source |
| 49 | Chorus pricing ~$8K/yr for 3 seats then ~$1,200/seat; $8,000-$25,000+/yr; 180-day auto-delete | competitor blogs; alexberman.com for the 180-day figure | competitor-blog / independent-unverified | **No** | **Low -- DO NOT PUBLISH** |
| 50 | Attention: "AI powered battlecards help you answer any prospect question while on the call" | attention.com/solutions/sales-reps | vendor-primary | Yes | High |
| 51 | Attention: "Real-time objection handling" and "Real-time coaching" | attention.com/solutions/sales-leaders | vendor-primary | Yes | High |
| 52 | Attention raised $30M Series B led by RTP Global announced 2026-06-24; ~$46.9M total; 500+ customers; 4x ARR YoY; CEO quote "Most software in this space watches the call and writes up what happened. We take the next best action." | PRNewswire Attention Series B release, 2026-06-24 | vendor-primary (press release) | Yes | High for the announcement; Medium for the ARR multiple (self-reported) |
| 53 | Attention captures via a meeting bot built on Recall.ai across Zoom/Meet/Teams plus Zoom Phone | attention.com/integrations/zoom; recall.ai/customers/attention | vendor-primary + independent | Yes | Medium-high |
| 54 | Attention publishes no pricing and no meaningful compliance posture | attention.com (site survey) | vendor-primary (negative evidence) | Yes | Medium-high -- phrase as "does not publish," not as "has none" |
| 55 | Sybill is post-call only, no live in-call guidance; bot-free desktop capture; Pro $30/$36 and Business $90/$108 per user/mo; $11M Series A March 2024, no round since, ~54 employees | sybill.ai, sybill.ai/pricing, help.sybill.ai; Crunchbase/Tracxn/PitchBook | vendor-primary + independent | Yes | Medium-high. **The subagent flagged that the fetched annual/monthly price orientation looks inverted -- do not quote Sybill prices without re-checking** |
| 56 | No open-source or self-hosted product appears in "Gong alternatives" or self-hosted CI SERPs | WebSearch 2026-07-24 | observed SERP | Yes | Medium-high -- SERPs are volatile and personalized; re-check at publish time |
| 57 | 58% of professionals feel uncomfortable when an AI meeting bot joins unexpectedly; 41% modify behavior when a bot is recording | calendly.com 2024 State of Meetings report (n=1,244 US/UK, fielded by Brand Over Matter, Jun-Jul 2024) | independent (vendor-commissioned, third-party-fielded) | Yes | Medium -- Calendly now ships its own Notetaker, so it is not disinterested; attribute the source if used |
| 58 | Backchannel `objection_handler` default interval 10s, 90s window, `gemini-3.5-flash-lite` | `backend/app/config.py` lines 25-26; `backend/app/services/seed_agents.py` ~lines 117-122 | repo | Yes | High |
| 59 | Backchannel objection output pairs `response_now` ("1-2 conversational sentences the user could say in the next ten seconds") with `bigger_picture` (underlying concern + strategic angle) | `backend/app/services/agents/prompts.py` lines 124-168 | repo | Yes | High |
| 60 | Backchannel has no user accounts, roles, or authentication in the application | no `User` model in `backend/app/models.py`; no auth dependency matches across `backend/app/routers/` | repo | Yes | High |
| 61 | Backchannel has no CRM integration | grep for salesforce/hubspot/crm across the repo matches only marketing HTML and an unrelated identifier in `frontend/src/hooks/useAudioCapture.ts` | repo | Yes | High |
| 62 | Backchannel has no talk-time analytics, scorecards, or coaching dashboards | grep in `backend/` matches only a meeting-type description string in `backend/app/services/meeting_context.py` | repo | Yes | High |
| 63 | Backchannel has no calendar integration or auto-join | no calendar router or client in `backend/app/routers/`; matches are prompt text | repo | Yes | Medium-high |
| 64 | Privacy First disables all LLM agents because local models are transcription-only | `backend/app/services/privacy.py`; local `MODEL_REGISTRY` entries carry `"supports_text": False` | repo | Yes | High |
| 65 | Backchannel writes per-segment WAV to disk and serves it over the API, making a Gong API upload path architecturally possible | `backend/app/services/audio_store.py`; `GET /api/sessions/{id}/segments/{n}/audio`; Gong endpoint per row 8 | repo + vendor-primary | Yes | High for the components. **The integration does not exist and must never be described as shipped** |
| 66 | Backchannel exports transcript TXT, insights XLSX, summary HTML | `backend/app/routers/artifacts.py` (`/transcript-export`, `/questions-export`, `/summary-export`) | repo | Yes | High |
| 67 | Zoom Sales Assist reached GA on 2026-07-22; surfaces "competitive intelligence, objection guidance, discovery prompts, battlecards, and configurable framework capture in real time"; Essentials $66/user/mo (from August 2026) and Premium $99.99/user/mo, billed annually | news.zoom.com/zoom-revenue-accelerator-insights-to-revenue-action/ | vendor-primary | Yes | High |
| 68 | Zoom Sales Assist guidance is pre-configured: admins input "relevant questions or guidance" per topic category (discovery, objection handling, pricing, competitor talking points, functionalities), with knowledge collections attached and rule-based live signals / timer reminders driving display | support.zoom.com KB0087752 | vendor-primary | Yes | High |
| 69 | Zoom Sales Assist prerequisites: Pro, Business, or Enterprise account; a Zoom Workplace license with Phone or a standalone Zoom Phone calling plan; a Revenue Accelerator Essentials or Premium license; admin configuration | support.zoom.com KB0087752 | vendor-primary | Yes | High |
| 70 | **RESOLUTION of rows 28 and 29 (the two 2023-dated Clari claims).** Re-verification attempted 2026-07-24 against current Clari customer documentation. The current KB article (Copilot Getting Started Level 3) confirms live cues and monologue alerts -- "Copilot automatically joins sales calls and shows you cues based on what's being said during the conversation" and "Copilot also helps you course-correct your own behavior while on calls with long monologue alerts" -- but is **silent on both the trigger-phrase mechanism and the desktop-app requirement** | clari.my.site.com/customer/articles/Knowledge/Copilot-Level-3 | vendor-primary | Partial | **Rows 28 and 29 are DROPPED from all published copy.** The current-KB live-cue and monologue-alert quotes are High confidence and are what shipped on the page instead |

### Flagged, unverifiable, and must-not-publish

- **Gong contract-term specifics** (platform fee dollar ranges, 15-seat minimum,
  implementation fees, renewal uplift percentages, no-true-down): competitor-blog
  only and partially contradicted by Gong's own docs. Use Gong's "per user plus a
  platform fee" language, or Vendr's median and seat bands.
- **Gong's 20-30 minute processing time**: not in Gong's help center. Reviewer
  complaints about slowness are citable; the number is not.
- **Gong support-quality collapse**: competitor-blog only; Capterra rates support
  4.7/5.
- **Clari Copilot standalone monthly pricing** from secondary blogs: use the
  Capterra list tiers with an explicit "as of mid-2026, verify with Clari"
  caveat.
- **Clari FedRAMP and HIPAA**: rejected -- no vendor page supports either.
- **EU data residency for Clari Copilot**: inconclusive in both directions.
- **Chorus per-seat pricing and the 180-day retention figure**: no credible
  source.
- **ZoomInfo auto-renewal litigation**: real and independently sourced, but they
  are allegations, and using them on an ecosystem-fit page is off-thesis. Omit.
- **Gong internal-surveillance complaints**: real and well-sourced, but using
  them positions Backchannel as shadow IT and surveillance evasion, contradicting
  the ecosystem framing. Omit.
- **Sybill pricing orientation**: the fetched annual/monthly figures appear
  inverted. Re-check before quoting.
- **RESOLVED 2026-07-24 -- the Clari desktop-app requirement (row 29) and the
  trigger-phrase mechanism (row 28) were re-verification targets and both
  FAILED.** Clari's current customer documentation confirms live cues and
  monologue alerts but is silent on both points, and the only sources asserting
  them remain 2023-dated community posts. **Both claims were dropped from the
  shipped page.** The published argument was restructured so it does not depend
  on characterizing Clari's internals at all: the page states what Backchannel
  does (generates a response from the trailing 90 seconds), describes Clari only
  in Clari's own current words, uses **Zoom Sales Assist** as the verified
  concrete example of the pre-configured pattern, and adds an explicit note that
  we are not characterizing Clari's matching mechanism because we could not
  verify it. Still re-check whether Clari Copilot survives the Salesloft merger
  as a named product before any future edit.
- **Could not access:** G2 (403), Reddit (blocked), TrustRadius product pages
  (403), ZoomInfo help center articles (JS-rendered), the Chorus
  implementation-guide PDF (unparseable), Trustpilot (403). Complaint evidence is
  strongest for Gong and Clari Copilot (direct Capterra verbatims) and thinnest
  for Chorus product behavior.

### Internal-consistency findings against the repo

Two documentation defects surfaced while verifying Backchannel's own claims. Both
would produce a factually wrong comparison page if the writer trusted `CLAUDE.md`:

- `CLAUDE.md` states the `objection_handler` interval is 5s and the
  `consolidated_analyst` interval is 15s. Both are stale. `backend/app/config.py`
  sets `OBJECTION_HANDLER_INTERVAL_SECONDS = 10` and
  `TEXT_AGENT_INTERVAL_SECONDS = 40`, and `backend/app/services/seed_agents.py`
  lists 5 and {15, 45} respectively under `OLD_DEFAULT_INTERVALS` -- values that
  are actively migrated away from. `docs/agents.md` is correct.
- `CLAUDE.md`'s agent roster omits `strategic_signals` and the three briefing
  agents (`brief_meeting_lens`, `brief_discovery_lens`, `brief_arbiter`), all
  seeded in `backend/app/services/seed_agents.py` and documented in
  `docs/agents.md`.

Treat `docs/agents.md` as authoritative for any marketing page, and file a
separate task to reconcile `CLAUDE.md`.
