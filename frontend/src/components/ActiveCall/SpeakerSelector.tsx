import type { Speaker } from "../../types";

interface Props {
  speakers: Speaker[];
  activeSpeakerId: string | null;
  onSelect: (speakerId: string | null) => void;
}

export default function SpeakerSelector({ speakers, activeSpeakerId, onSelect }: Props) {
  if (speakers.length === 0) return null;

  return (
    <div className="flex items-center gap-1.5 px-4 py-2 border-b border-brand-light-gray-1 overflow-x-auto">
      {speakers.map((speaker) => {
        const isActive = activeSpeakerId === speaker.id;
        return (
          <button
            key={speaker.id}
            onClick={() => onSelect(speaker.id)}
            className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-all whitespace-nowrap ${
              isActive
                ? "bg-surface shadow-sm ring-2"
                : "bg-brand-light-gray-2 text-brand-gray hover:bg-brand-light-gray-1"
            }`}
            style={
              isActive
                ? { borderColor: speaker.color, color: speaker.color, boxShadow: `0 0 0 2px ${speaker.color}` }
                : undefined
            }
          >
            <span
              className="inline-block h-2.5 w-2.5 rounded-full shrink-0"
              style={{ backgroundColor: speaker.color }}
            />
            {speaker.name}
          </button>
        );
      })}
    </div>
  );
}
