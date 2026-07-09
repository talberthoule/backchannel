import React, { useState, useRef, useEffect } from "react";
import type { Speaker, TranscriptEntry } from "../../types";

interface TranscriptReviewProps {
  transcripts: TranscriptEntry[];
  speakers: Speaker[];
  onRenameSpeaker?: (speakerId: string, newName: string) => void;
}

function formatTimestamp(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return ts;
  }
}

function InlineSpeakerLabel({
  speaker,
  onRename,
}: {
  speaker: Speaker;
  onRename?: (speakerId: string, newName: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState(speaker.name);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [editing]);

  const handleCommit = () => {
    const trimmed = editName.trim();
    if (trimmed && trimmed !== speaker.name && onRename) {
      onRename(speaker.id, trimmed);
    }
    setEditing(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      handleCommit();
    } else if (e.key === "Escape") {
      setEditName(speaker.name);
      setEditing(false);
    }
  };

  if (editing) {
    return (
      <input
        ref={inputRef}
        type="text"
        value={editName}
        onChange={(e) => setEditName(e.target.value)}
        onBlur={handleCommit}
        onKeyDown={handleKeyDown}
        className="mr-1.5 inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold text-white border-0"
        style={{ backgroundColor: speaker.color, width: `${Math.max(editName.length + 2, 4)}ch` }}
      />
    );
  }

  return (
    <span
      className={`mr-1.5 inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold text-white ${onRename ? "cursor-pointer hover:opacity-80" : ""}`}
      style={{ backgroundColor: speaker.color }}
      onClick={() => {
        if (onRename) {
          setEditName(speaker.name);
          setEditing(true);
        }
      }}
      title={onRename ? "Click to rename" : undefined}
    >
      {speaker.display_name && speaker.display_name_enabled ? speaker.display_name : speaker.name}
    </span>
  );
}

export default function TranscriptReview({ transcripts, speakers, onRenameSpeaker }: TranscriptReviewProps) {
  if (transcripts.length === 0) {
    return (
      <div className="rounded-xl bg-surface p-10 text-center shadow-sm">
        <p className="text-brand-mid-gray">No transcript entries recorded for this session.</p>
      </div>
    );
  }

  return (
    <div className="rounded-xl bg-surface shadow-sm">
      <div className="border-b border-brand-light-gray-1 px-6 py-4">
        <h2 className="font-display text-lg font-semibold text-brand-dark-gray">
          Full Transcript
        </h2>
        <p className="mt-1 text-xs text-brand-mid-gray">
          {transcripts.length} {transcripts.length === 1 ? "entry" : "entries"}
          {onRenameSpeaker && " \u00b7 Click a speaker name to rename"}
        </p>
      </div>

      <div className="max-h-[600px] overflow-y-auto">
        <ul className="divide-y divide-brand-light-gray-1">
          {transcripts.map((entry, idx) => {
            const speaker = entry.speaker_id ? speakers.find((s) => s.id === entry.speaker_id) : null;
            return (
              <li key={idx} className="flex gap-4 px-6 py-4">
                <span className="shrink-0 pt-0.5 font-mono text-xs text-brand-mid-gray">
                  {formatTimestamp(entry.timestamp)}
                </span>
                <div className="flex-1">
                  {speaker && (
                    <InlineSpeakerLabel speaker={speaker} onRename={onRenameSpeaker} />
                  )}
                  <span className="text-sm leading-relaxed text-brand-dark-gray">{entry.text}</span>
                </div>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
