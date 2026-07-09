import { useState } from "react";
import type { Speaker } from "../../types";
import { useConfirm } from "../ConfirmProvider";
import * as api from "../../services/api";

interface Props {
  sessionId: string;
  speakers: Speaker[];
  onRefresh: () => void;
}

const PRESET_COLORS = [
  "#0d9488",
  "#f59e0b",
  "#10b981",
  "#7c3aed",
  "#e2231a",
  "#ffc52a",
];

export default function SpeakerSetup({ sessionId, speakers, onRefresh }: Props) {
  const { confirm, toast } = useConfirm();
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [color, setColor] = useState(PRESET_COLORS[0]);
  const [isUser, setIsUser] = useState(false);
  const [speakerType, setSpeakerType] = useState<"team" | "external">("external");
  const [saving, setSaving] = useState(false);

  const resetForm = () => {
    setName("");
    setRole("");
    setColor(PRESET_COLORS[0]);
    setIsUser(false);
    setSpeakerType("external");
    setShowForm(false);
  };

  const handleAdd = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      await api.createSpeaker(sessionId, {
        name: name.trim(),
        role: role.trim() || undefined,
        color,
        is_user: isUser && speakerType === "team",
        speaker_type: speakerType,
      });
      resetForm();
      onRefresh();
    } catch (err) {
      console.error("Failed to add speaker", err);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    const ok = await confirm({
      title: "Remove participant",
      message: "Remove this participant from the session?",
      confirmLabel: "Remove",
      tone: "danger",
    });
    if (!ok) return;
    try {
      await api.deleteSpeaker(sessionId, id);
      onRefresh();
      toast("Participant removed");
    } catch (err) {
      console.error("Failed to delete speaker", err);
    }
  };

  const handleShowForm = () => {
    // If no speakers yet, default to "Me" with is_user
    if (speakers.length === 0) {
      setName("Me");
      setIsUser(true);
      setSpeakerType("team");
      setColor(PRESET_COLORS[0]);
    } else {
      // Pick next unused color
      const usedColors = new Set(speakers.map((s) => s.color));
      const nextColor = PRESET_COLORS.find((c) => !usedColors.has(c)) || PRESET_COLORS[0];
      setColor(nextColor);
      setName(`Participant ${speakers.filter((s) => s.speaker_type === "external").length + 1}`);
      setIsUser(false);
      setSpeakerType("external");
    }
    setRole("");
    setShowForm(true);
  };

  return (
    <div className="space-y-3">
      {/* Speaker list */}
      {speakers.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {speakers.map((speaker) => (
            <div
              key={speaker.id}
              className="flex items-center gap-2 rounded-lg border border-brand-light-gray-1 bg-surface px-3 py-2 shadow-sm"
            >
              <span
                className="inline-block h-3 w-3 rounded-full shrink-0"
                style={{ backgroundColor: speaker.color }}
              />
              <span className="font-body text-sm font-medium text-brand-dark-gray">
                {speaker.name}
              </span>
              {speaker.role && (
                <span className="font-body text-xs text-brand-mid-gray">
                  ({speaker.role})
                </span>
              )}
              {speaker.is_user && (
                <span className="rounded-full bg-brand-teal/10 px-1.5 py-0.5 text-[10px] font-medium text-brand-teal">
                  You
                </span>
              )}
              <span
                className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${
                  speaker.speaker_type === "team"
                    ? "bg-brand-teal-light/10 text-brand-teal-light"
                    : "bg-brand-light-gray-2 text-brand-gray"
                }`}
              >
                {speaker.speaker_type === "team" ? "Team" : "External party"}
              </span>
              <button
                onClick={() => handleDelete(speaker.id)}
                className="ml-1 text-brand-mid-gray hover:text-red-500 transition-colors"
                title="Remove participant"
              >
                <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Add form */}
      {showForm ? (
        <div className="rounded-lg border border-brand-light-gray-1 bg-surface p-4 space-y-3 shadow-sm">
          <div className="flex gap-3">
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Name"
              className="flex-1 rounded-md border border-brand-light-gray-1 px-3 py-2 font-body text-sm text-brand-dark-gray placeholder:text-brand-mid-gray focus:border-brand-teal-light focus:ring-1 focus:ring-brand-teal-light"
            />
            <input
              type="text"
              value={role}
              onChange={(e) => setRole(e.target.value)}
              placeholder="e.g., Engineer, Seller, Vendor SE"
              className="flex-1 rounded-md border border-brand-light-gray-1 px-3 py-2 font-body text-sm text-brand-dark-gray placeholder:text-brand-mid-gray focus:border-brand-teal-light focus:ring-1 focus:ring-brand-teal-light"
            />
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                setSpeakerType("team");
              }}
              className={`rounded-md px-3 py-1.5 font-body text-xs font-medium transition-colors ${
                speakerType === "team"
                  ? "bg-brand-teal text-white"
                  : "bg-brand-light-gray-2 text-brand-gray hover:bg-brand-light-gray-1"
              }`}
            >
              Team member
            </button>
            <button
              type="button"
              onClick={() => {
                setSpeakerType("external");
                setIsUser(false);
              }}
              className={`rounded-md px-3 py-1.5 font-body text-xs font-medium transition-colors ${
                speakerType === "external"
                  ? "bg-brand-teal text-white"
                  : "bg-brand-light-gray-2 text-brand-gray hover:bg-brand-light-gray-1"
              }`}
            >
              External party
            </button>
          </div>

          <div className="flex items-center gap-4">
            <span className="font-body text-xs text-brand-gray">Color:</span>
            <div className="flex gap-2">
              {PRESET_COLORS.map((c) => (
                <button
                  key={c}
                  onClick={() => setColor(c)}
                  className={`h-6 w-6 rounded-full border-2 transition-all ${
                    color === c ? "border-brand-dark-gray scale-110" : "border-transparent"
                  }`}
                  style={{ backgroundColor: c }}
                  title={c}
                />
              ))}
            </div>

            <label className="ml-auto flex items-center gap-1.5 cursor-pointer">
              <input
                type="checkbox"
                checked={isUser && speakerType === "team"}
                disabled={speakerType !== "team"}
                onChange={(e) => {
                  setIsUser(e.target.checked);
                  if (e.target.checked) setSpeakerType("team");
                }}
                className="h-3.5 w-3.5 rounded border-brand-light-gray-1 text-brand-teal focus:ring-brand-teal-light"
              />
              <span className="font-body text-xs text-brand-gray">This is me</span>
            </label>
          </div>

          <div className="flex gap-2 pt-1">
            <button
              onClick={handleAdd}
              disabled={!name.trim() || saving}
              className="rounded-md bg-brand-teal px-4 py-1.5 font-body text-sm font-medium text-white transition-colors hover:bg-brand-teal-dark disabled:opacity-50"
            >
              {saving ? "Adding..." : "Add"}
            </button>
            <button
              onClick={resetForm}
              className="rounded-md border border-brand-light-gray-1 px-4 py-1.5 font-body text-sm text-brand-gray transition-colors hover:bg-brand-light-gray-2"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <button
          onClick={handleShowForm}
          className="flex items-center gap-1.5 rounded-md border border-dashed border-brand-light-gray-1 px-3 py-2 font-body text-sm text-brand-teal transition-colors hover:border-brand-teal-light hover:bg-brand-light-gray-2"
        >
          <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
          Add Participant
        </button>
      )}
    </div>
  );
}
