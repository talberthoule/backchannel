import { useState } from "react";
import * as api from "../../services/api";

interface Props {
  sessionId: string;
  onAdded: () => void;
}

export default function DirectiveInput({ sessionId, onAdded }: Props) {
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleAdd = async () => {
    const trimmed = text.trim();
    if (!trimmed) return;

    setSubmitting(true);
    try {
      await api.createDirective(sessionId, trimmed);
      setText("");
      onAdded();
    } catch (err) {
      console.error("Failed to add directive:", err);
    } finally {
      setSubmitting(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleAdd();
    }
  };

  return (
    <div className="flex gap-3">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="e.g., watch for unclear concepts, key decisions, open questions, risks, and follow-up actions"
        rows={2}
        className="flex-1 rounded-lg border border-brand-light-gray-1 bg-white px-4 py-3
                   font-body text-sm text-brand-dark-gray placeholder:text-brand-mid-gray
                   focus:outline-none focus:ring-2 focus:ring-brand-teal-light focus:border-transparent
                   resize-none"
      />
      <button
        onClick={handleAdd}
        disabled={!text.trim() || submitting}
        className="self-end shrink-0 rounded-lg px-5 py-3 font-display text-sm font-semibold
                   text-white bg-brand-teal hover:bg-brand-teal-dark transition-colors
                   disabled:opacity-40 disabled:cursor-not-allowed
                   focus:outline-none focus:ring-2 focus:ring-brand-teal-light focus:ring-offset-2"
      >
        {submitting ? "Adding..." : "Add Directive"}
      </button>
    </div>
  );
}
