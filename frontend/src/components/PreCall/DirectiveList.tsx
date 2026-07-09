import { useState } from "react";
import type { Directive } from "../../types";
import { useConfirm } from "../ConfirmProvider";
import * as api from "../../services/api";

interface Props {
  sessionId: string;
  directives: Directive[];
  onRefresh: () => void;
}

export default function DirectiveList({ sessionId, directives, onRefresh }: Props) {
  const { confirm, toast } = useConfirm();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");

  const handleToggle = async (directive: Directive) => {
    try {
      await api.updateDirective(sessionId, directive.id, { active: !directive.active });
      onRefresh();
    } catch (err) {
      console.error("Failed to toggle directive:", err);
    }
  };

  const handleDelete = async (id: string) => {
    const ok = await confirm({
      title: "Delete directive",
      message: "Delete this directive?",
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (!ok) return;
    try {
      await api.deleteDirective(sessionId, id);
      onRefresh();
      toast("Directive deleted");
    } catch (err) {
      console.error("Failed to delete directive:", err);
    }
  };

  const startEdit = (directive: Directive) => {
    setEditingId(directive.id);
    setEditText(directive.text);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditText("");
  };

  const saveEdit = async (id: string) => {
    const trimmed = editText.trim();
    if (!trimmed) return;
    try {
      await api.updateDirective(sessionId, id, { text: trimmed });
      setEditingId(null);
      setEditText("");
      onRefresh();
    } catch (err) {
      console.error("Failed to update directive:", err);
    }
  };

  if (directives.length === 0) {
    return (
      <p className="font-body text-sm text-brand-mid-gray py-4 text-center">
        No directives yet. Add one above to guide the AI during your call.
      </p>
    );
  }

  return (
    <ul className="space-y-2">
      {directives.map((d) => {
        const isEditing = editingId === d.id;

        return (
          <li
            key={d.id}
            className={`rounded-lg bg-surface shadow-sm border px-4 py-3 transition-colors ${
              d.active
                ? "border-brand-teal-light/40"
                : "border-brand-light-gray-1 opacity-60"
            }`}
          >
            <div className="flex items-start gap-3">
              {/* Toggle */}
              <button
                onClick={() => handleToggle(d)}
                className="mt-0.5 shrink-0"
                title={d.active ? "Deactivate" : "Activate"}
              >
                <div
                  className={`relative h-5 w-9 rounded-full transition-colors ${
                    d.active ? "bg-brand-teal" : "bg-brand-light-gray-1"
                  }`}
                >
                  <div
                    className={`absolute top-0.5 h-4 w-4 rounded-full bg-surface shadow transition-transform ${
                      d.active ? "translate-x-4" : "translate-x-0.5"
                    }`}
                  />
                </div>
              </button>

              {/* Content */}
              <div className="flex-1 min-w-0">
                {isEditing ? (
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={editText}
                      onChange={(e) => setEditText(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") saveEdit(d.id);
                        if (e.key === "Escape") cancelEdit();
                      }}
                      className="flex-1 rounded border border-brand-light-gray-1 px-2 py-1
                                 font-body text-sm text-brand-dark-gray
                                 focus:ring-1 focus:ring-brand-teal-light"
                      autoFocus
                    />
                    <button
                      onClick={() => saveEdit(d.id)}
                      className="text-xs font-display font-semibold text-brand-teal
                                 hover:text-brand-teal-dark"
                    >
                      Save
                    </button>
                    <button
                      onClick={cancelEdit}
                      className="text-xs font-display font-semibold text-brand-mid-gray
                                 hover:text-brand-dark-gray"
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <p className="font-body text-sm text-brand-dark-gray">{d.text}</p>
                )}
              </div>

              {/* Actions */}
              {!isEditing && (
                <div className="flex items-center gap-1 shrink-0">
                  {/* Edit */}
                  <button
                    onClick={() => startEdit(d)}
                    className="p-1 rounded text-brand-mid-gray hover:text-brand-teal transition-colors"
                    title="Edit"
                  >
                    <svg
                      className="h-4 w-4"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      strokeWidth={1.5}
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10"
                      />
                    </svg>
                  </button>

                  {/* Delete */}
                  <button
                    onClick={() => handleDelete(d.id)}
                    className="p-1 rounded text-brand-mid-gray hover:text-red-500 transition-colors"
                    title="Delete"
                  >
                    <svg
                      className="h-4 w-4"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      strokeWidth={1.5}
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0"
                      />
                    </svg>
                  </button>
                </div>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
