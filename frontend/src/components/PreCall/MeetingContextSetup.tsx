import { useEffect, useState } from "react";
import type { MeetingType, Session } from "../../types";

interface Props {
  session: Session;
  onUpdate: (data: { meeting_type?: MeetingType; meeting_context?: string }) => Promise<void>;
}

export const MEETING_TYPES: { value: MeetingType; label: string; hint: string; placeholder: string }[] = [
  {
    value: "general",
    label: "General / infer",
    hint: "Let the agents infer the meeting shape from transcript and context.",
    placeholder: "Example: Internal discussion about the crypto algorithm landscape and where the cyber sales team needs clearer enablement.",
  },
  {
    value: "client_sales",
    label: "Client / prospect",
    hint: "Use for discovery, account strategy, buying signals, and sales follow-up.",
    placeholder: "Example: Conversation with a client CIO about AI readiness, risks, timeline, and where we may help.",
  },
  {
    value: "customer_delivery",
    label: "Customer delivery",
    hint: "Use for implementation, project, operations, or technical working sessions.",
    placeholder: "Example: Weekly migration planning call focused on blockers, owners, scope decisions, and next actions.",
  },
  {
    value: "internal_enablement",
    label: "Internal enablement",
    hint: "Use for training, knowledge transfer, and technical education.",
    placeholder: "Example: A CSC/pre-sales engineer is educating SPL/cyber sellers on cryptographic algorithms and how to discuss them clearly.",
  },
  {
    value: "internal_checkin",
    label: "Internal check-in",
    hint: "Use for one-on-ones, relationship calls, coaching, or informal internal conversations.",
    placeholder: "Example: Quick internal check-in to understand what someone is working on and where they may need support.",
  },
  {
    value: "vendor_partner",
    label: "Vendor / partner",
    hint: "Use for roadmap, program, alliance, partner, or vendor update conversations.",
    placeholder: "Example: Vendor program update covering roadmap changes, field asks, enablement gaps, and follow-up commitments.",
  },
];

export default function MeetingContextSetup({ session, onUpdate }: Props) {
  const [meetingType, setMeetingType] = useState<MeetingType>(session.meeting_type || "general");
  const [meetingContext, setMeetingContext] = useState(session.meeting_context || session.notes || "");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setMeetingType(session.meeting_type || "general");
    setMeetingContext(session.meeting_context || session.notes || "");
  }, [session.id, session.meeting_type, session.meeting_context, session.notes]);

  const selected = MEETING_TYPES.find((type) => type.value === meetingType) || MEETING_TYPES[0];
  const dirty = meetingType !== session.meeting_type || meetingContext !== (session.meeting_context || "");

  const handleSave = async () => {
    setSaving(true);
    try {
      await onUpdate({
        meeting_type: meetingType,
        meeting_context: meetingContext.trim(),
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="rounded-lg border border-brand-light-gray-1 bg-surface p-4 shadow-sm">
      <div className="grid gap-3 md:grid-cols-[220px,1fr]">
        <div>
          <label className="mb-1 block font-body text-xs font-semibold uppercase tracking-wide text-brand-mid-gray">
            Conversation Type
          </label>
          <select
            value={meetingType}
            onChange={(event) => setMeetingType(event.target.value as MeetingType)}
            className="w-full rounded-md border border-brand-light-gray-1 bg-surface px-3 py-2 font-body text-sm text-brand-dark-gray focus:border-brand-teal-light focus:ring-1 focus:ring-brand-teal-light"
          >
            {MEETING_TYPES.map((type) => (
              <option key={type.value} value={type.value}>
                {type.label}
              </option>
            ))}
          </select>
          <p className="mt-2 font-body text-xs leading-relaxed text-brand-mid-gray">{selected.hint}</p>
        </div>

        <div>
          <label className="mb-1 block font-body text-xs font-semibold uppercase tracking-wide text-brand-mid-gray">
            Purpose / Context
          </label>
          <textarea
            value={meetingContext}
            onChange={(event) => setMeetingContext(event.target.value)}
            rows={4}
            placeholder={selected.placeholder}
            className="w-full resize-none rounded-md border border-brand-light-gray-1 bg-surface px-3 py-2 font-body text-sm text-brand-dark-gray placeholder:text-brand-mid-gray focus:border-brand-teal-light focus:ring-1 focus:ring-brand-teal-light"
          />
          <div className="mt-2 flex items-center justify-between gap-3">
            <p className="font-body text-xs text-brand-mid-gray">Context saved with this session.</p>
            <button
              type="button"
              onClick={handleSave}
              disabled={!dirty || saving}
              className="rounded-md bg-brand-teal px-3 py-1.5 font-body text-xs font-semibold text-white transition-colors hover:bg-brand-teal-dark disabled:cursor-not-allowed disabled:opacity-50"
            >
              {saving ? "Saving..." : "Save Context"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
