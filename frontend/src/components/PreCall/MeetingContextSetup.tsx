import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import type { MeetingType, Session } from "../../types";

interface Props {
  session: Session;
  onUpdate: (data: { meeting_type?: MeetingType; meeting_context?: string }) => Promise<void>;
}

const MEETING_TYPE_KEYS: Record<MeetingType, string> = {
  general: "meetingTypes.general",
  client_sales: "meetingTypes.clientSales",
  customer_delivery: "meetingTypes.customerDelivery",
  internal_enablement: "meetingTypes.internalEnablement",
  internal_checkin: "meetingTypes.internalCheckin",
  vendor_partner: "meetingTypes.vendorPartner",
};

export const MEETING_TYPE_VALUES = Object.keys(MEETING_TYPE_KEYS) as MeetingType[];

export type MeetingTypeCopy = { label: string; hint: string; placeholder: string };

export function meetingTypeCopy(value: MeetingType, t: TFunction): MeetingTypeCopy {
  return t(MEETING_TYPE_KEYS[value], { returnObjects: true }) as MeetingTypeCopy;
}

export default function MeetingContextSetup({ session, onUpdate }: Props) {
  const { t } = useTranslation();
  const [meetingType, setMeetingType] = useState<MeetingType>(session.meeting_type || "general");
  const [meetingContext, setMeetingContext] = useState(session.meeting_context || session.notes || "");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setMeetingType(session.meeting_type || "general");
    setMeetingContext(session.meeting_context || session.notes || "");
  }, [session.id, session.meeting_type, session.meeting_context, session.notes]);

  const selected = meetingTypeCopy(meetingType, t);
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
            {t("meetingTypes.conversationType")}
          </label>
          <select
            value={meetingType}
            onChange={(event) => setMeetingType(event.target.value as MeetingType)}
            className="w-full rounded-md border border-brand-light-gray-1 bg-surface px-3 py-2 font-body text-sm text-brand-dark-gray focus:border-brand-teal-light focus:ring-1 focus:ring-brand-teal-light"
          >
            {MEETING_TYPE_VALUES.map((value) => (
              <option key={value} value={value}>
                {meetingTypeCopy(value, t).label}
              </option>
            ))}
          </select>
          <p className="mt-2 font-body text-xs leading-relaxed text-brand-mid-gray">{selected.hint}</p>
        </div>

        <div>
          <label className="mb-1 block font-body text-xs font-semibold uppercase tracking-wide text-brand-mid-gray">
            {t("meetingTypes.purposeContext")}
          </label>
          <textarea
            value={meetingContext}
            onChange={(event) => setMeetingContext(event.target.value)}
            rows={4}
            placeholder={selected.placeholder}
            className="w-full resize-none rounded-md border border-brand-light-gray-1 bg-surface px-3 py-2 font-body text-sm text-brand-dark-gray placeholder:text-brand-mid-gray focus:border-brand-teal-light focus:ring-1 focus:ring-brand-teal-light"
          />
          <div className="mt-2 flex items-center justify-between gap-3">
            <p className="font-body text-xs text-brand-mid-gray">{t("meetingTypes.saved")}</p>
            <button
              type="button"
              onClick={handleSave}
              disabled={!dirty || saving}
              className="rounded-md bg-brand-teal px-3 py-1.5 font-body text-xs font-semibold text-white transition-colors hover:bg-brand-teal-dark disabled:cursor-not-allowed disabled:opacity-50"
            >
              {saving ? t("common.saving") : t("meetingTypes.save")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
