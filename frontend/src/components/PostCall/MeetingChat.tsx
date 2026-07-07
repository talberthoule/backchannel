import { useEffect, useMemo, useRef, useState } from "react";
import type { ModelInfo, Session } from "../../types";
import * as api from "../../services/api";

interface MeetingChatProps {
  session: Session;
}

interface ChatMsg {
  role: "user" | "assistant";
  content: string;
}

export default function MeetingChat({ session }: MeetingChatProps) {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [allSessions, setAllSessions] = useState<Session[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set([session.id]));
  const [search, setSearch] = useState("");

  const [models, setModels] = useState<ModelInfo[]>([]);
  const [modelId, setModelId] = useState("");

  const threadRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.listSessions().then(setAllSessions).catch(() => {});
    Promise.all([api.listModels(), api.listAgents()]).then(([m, agents]) => {
      const textModels = m.filter((x) => x.supports_text && x.key_available !== false);
      setModels(textModels);
      const analyst = agents.find((a) => a.slug === "consolidated_analyst");
      const preferred = analyst && textModels.some((x) => x.id === analyst.model_id)
        ? analyst.model_id
        : textModels[0]?.id || "";
      setModelId(preferred);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight });
  }, [messages, busy]);

  const groupSessions = useMemo(
    () => allSessions.filter((s) => s.id !== session.id && session.group_id && s.group_id === session.group_id),
    [allSessions, session],
  );

  const searchResults = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return [];
    const shown = new Set([session.id, ...groupSessions.map((s) => s.id)]);
    return allSessions.filter((s) => !shown.has(s.id) && s.name.toLowerCase().includes(q)).slice(0, 8);
  }, [search, allSessions, groupSessions, session.id]);

  const toggleSession = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      if (next.size === 0) next.add(session.id);
      return next;
    });
  };

  const selectedExtra = useMemo(
    () => allSessions.filter((s) => selectedIds.has(s.id) && s.id !== session.id && !groupSessions.some((g) => g.id === s.id)),
    [allSessions, selectedIds, groupSessions, session.id],
  );

  const handleSend = async () => {
    const question = input.trim();
    if (!question || busy || !modelId) return;
    const nextMessages: ChatMsg[] = [...messages, { role: "user", content: question }];
    setMessages(nextMessages);
    setInput("");
    setBusy(true);
    setError(null);
    try {
      const res = await api.chat(modelId, [...selectedIds], nextMessages);
      setMessages([...nextMessages, { role: "assistant", content: res.reply }]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Chat failed");
      setMessages(messages); // roll back the optimistic user message
      setInput(question);
    } finally {
      setBusy(false);
    }
  };

  const sessionCheckbox = (s: Session, removable = false) => (
    <label key={s.id} className="flex items-center gap-1.5 cursor-pointer rounded-full border border-brand-light-gray-1 bg-white px-2.5 py-1">
      <input
        type="checkbox"
        checked={selectedIds.has(s.id)}
        onChange={() => toggleSession(s.id)}
        disabled={s.id === session.id && selectedIds.size === 1}
        className="h-3.5 w-3.5 rounded border-brand-light-gray-1 text-brand-teal"
      />
      <span className="font-body text-xs text-brand-dark-gray">{s.name}{removable ? "" : ""}</span>
    </label>
  );

  return (
    <div className="flex h-full min-h-[420px] flex-col rounded-xl bg-white shadow-sm">
      {/* Scope picker */}
      <div className="border-b border-brand-light-gray-1 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-body text-xs font-medium text-brand-gray">Transcripts:</span>
          {sessionCheckbox(session)}
          {groupSessions.map((s) => sessionCheckbox(s))}
          {selectedExtra.map((s) => sessionCheckbox(s, true))}
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Add other sessions..."
            className="w-44 rounded border border-brand-light-gray-1 bg-white px-2 py-1 font-body text-xs text-brand-dark-gray outline-none focus:border-brand-teal"
          />
          <select
            value={modelId}
            onChange={(e) => setModelId(e.target.value)}
            className="ml-auto rounded border border-brand-light-gray-1 bg-white px-2 py-1 font-body text-xs text-brand-dark-gray outline-none focus:border-brand-teal"
          >
            {models.map((m) => (
              <option key={m.id} value={m.id}>{m.name}</option>
            ))}
          </select>
        </div>
        {searchResults.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-2">
            {searchResults.map((s) => (
              <button
                key={s.id}
                onClick={() => { toggleSession(s.id); setSearch(""); }}
                className="rounded-full border border-dashed border-brand-light-gray-1 px-2.5 py-1 font-body text-xs text-brand-mid-gray hover:border-brand-teal hover:text-brand-teal transition-colors"
              >
                + {s.name}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Thread */}
      <div ref={threadRef} className="flex-1 space-y-3 overflow-auto p-4">
        {messages.length === 0 && (
          <p className="py-10 text-center font-body text-sm text-brand-mid-gray">
            Ask anything about the selected meeting transcripts.
          </p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
            <div
              className={`max-w-[80%] whitespace-pre-wrap rounded-2xl px-4 py-2 font-body text-sm leading-relaxed ${
                m.role === "user"
                  ? "bg-brand-teal text-white"
                  : "bg-brand-light-gray-2 text-brand-dark-gray"
              }`}
            >
              {m.content}
            </div>
          </div>
        ))}
        {busy && <p className="font-body text-xs text-brand-mid-gray">Thinking...</p>}
        {error && <p className="font-body text-xs text-red-600">{error}</p>}
      </div>

      {/* Input */}
      <div className="flex items-center gap-2 border-t border-brand-light-gray-1 p-3">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") handleSend(); }}
          placeholder="Ask about these meetings..."
          disabled={busy}
          className="flex-1 rounded-lg border border-brand-light-gray-1 bg-white px-3 py-2 font-body text-sm text-brand-dark-gray outline-none focus:border-brand-teal"
        />
        <button
          onClick={handleSend}
          disabled={busy || !input.trim()}
          className="rounded-lg bg-brand-teal px-4 py-2 font-body text-sm font-medium text-white transition-opacity disabled:opacity-40"
        >
          Send
        </button>
      </div>
    </div>
  );
}
