import { useCallback, useEffect, useRef, useState } from "react";
import type { KnowledgeRecord, KnowledgeSource } from "../types";
import { useConfirm } from "./ConfirmProvider";
import * as api from "../services/api";

const TYPE_BADGES: Record<string, { label: string; color: string }> = {
  offerings: { label: "Built-in", color: "#10b981" },
  collection: { label: "Collection", color: "#7c3aed" },
  files: { label: "Files", color: "#0d9488" },
};

// Inline editable cell (same pattern as OfferingsManager)
function EditableCell({
  value,
  onSave,
  multiline = false,
  placeholder = "",
}: {
  value: string;
  onSave: (val: string) => void;
  multiline?: boolean;
  placeholder?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const ref = useRef<HTMLInputElement | HTMLTextAreaElement>(null);

  useEffect(() => {
    setDraft(value);
  }, [value]);

  useEffect(() => {
    if (editing && ref.current) {
      ref.current.focus();
      ref.current.select();
    }
  }, [editing]);

  const commit = () => {
    setEditing(false);
    if (draft.trim() !== value) {
      onSave(draft.trim());
    }
  };

  if (!editing) {
    return (
      <span
        className={`block cursor-pointer rounded px-1 py-0.5 transition-colors hover:bg-brand-light-gray-2 ${
          !value ? "italic text-brand-mid-gray" : ""
        }`}
        onClick={() => setEditing(true)}
        title="Click to edit"
      >
        {value || placeholder || "—"}
      </span>
    );
  }

  if (multiline) {
    return (
      <textarea
        ref={ref as React.RefObject<HTMLTextAreaElement>}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            setDraft(value);
            setEditing(false);
          }
        }}
        className="w-full rounded border border-brand-teal-light bg-surface px-1.5 py-1 text-xs text-brand-dark-gray ring-1 ring-brand-teal-light/30"
        rows={4}
      />
    );
  }

  return (
    <input
      ref={ref as React.RefObject<HTMLInputElement>}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit();
        if (e.key === "Escape") {
          setDraft(value);
          setEditing(false);
        }
      }}
      className="w-full rounded border border-brand-teal-light bg-surface px-1.5 py-1 text-xs text-brand-dark-gray ring-1 ring-brand-teal-light/30"
    />
  );
}

// New source form
function AddSourceForm({ onAdd, onCancel }: { onAdd: (name: string, sourceType: string) => void; onCancel: () => void }) {
  const [name, setName] = useState("");
  const [sourceType, setSourceType] = useState("collection");

  return (
    <div className="rounded-lg border border-brand-teal-light/30 bg-brand-teal-light/5 p-3 space-y-2">
      <input
        autoFocus
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && name.trim()) onAdd(name.trim(), sourceType);
          if (e.key === "Escape") onCancel();
        }}
        placeholder="Source name..."
        className="w-full rounded border border-brand-light-gray-1 px-2 py-1.5 text-sm focus:border-brand-teal"
      />
      <select
        value={sourceType}
        onChange={(e) => setSourceType(e.target.value)}
        className="w-full rounded border border-brand-light-gray-1 bg-surface px-2 py-1.5 text-sm focus:border-brand-teal"
      >
        <option value="collection">Collection (structured records)</option>
        <option value="files">Files (uploaded documents)</option>
      </select>
      <div className="flex gap-2">
        <button
          onClick={() => name.trim() && onAdd(name.trim(), sourceType)}
          disabled={!name.trim()}
          className="rounded-lg bg-brand-teal px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-brand-teal-dark disabled:opacity-40"
        >
          Create
        </button>
        <button
          onClick={onCancel}
          className="rounded-lg border border-brand-light-gray-1 px-3 py-1.5 text-xs text-brand-gray transition-colors hover:bg-brand-light-gray-2"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

interface KnowledgeManagerProps {
  onBack: () => void;
}

export default function KnowledgeManager({ onBack }: KnowledgeManagerProps) {
  const { confirm, toast } = useConfirm();
  const [sources, setSources] = useState<KnowledgeSource[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [records, setRecords] = useState<KnowledgeRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingRecords, setLoadingRecords] = useState(false);
  const [creating, setCreating] = useState(false);
  const [addingRecord, setAddingRecord] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newBody, setNewBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);
  const importRef = useRef<HTMLInputElement>(null);
  const uploadRef = useRef<HTMLInputElement>(null);

  const selected = sources.find((s) => s.id === selectedId) || null;

  const loadSources = useCallback(async () => {
    setLoading(true);
    try {
      const list = await api.listKnowledgeSources();
      setSources(list);
      setSelectedId((prev) => prev && list.some((s) => s.id === prev) ? prev : (list[0]?.id ?? null));
    } catch (err) {
      console.error("Failed to load knowledge sources", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadSources(); }, [loadSources]);

  const loadRecords = useCallback(async (sourceId: string) => {
    setLoadingRecords(true);
    try {
      setRecords(await api.listKnowledgeRecords(sourceId));
    } catch (err) {
      console.error("Failed to load records", err);
      setRecords([]);
    } finally {
      setLoadingRecords(false);
    }
  }, []);

  useEffect(() => {
    if (selectedId) loadRecords(selectedId);
    else setRecords([]);
  }, [selectedId, loadRecords]);

  const refreshCounts = useCallback(async () => {
    try {
      setSources(await api.listKnowledgeSources());
    } catch { /* non-fatal */ }
  }, []);

  const handleCreateSource = async (name: string, sourceType: string) => {
    try {
      const created = await api.createKnowledgeSource({ name, source_type: sourceType });
      setSources((prev) => [...prev, created]);
      setSelectedId(created.id);
      setCreating(false);
    } catch (err) {
      console.error("Create source failed", err);
    }
  };

  const handleDeleteSource = async (id: string) => {
    const ok = await confirm({
      title: "Delete knowledge source",
      message: "Delete this knowledge source and all its records? This cannot be undone.",
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (!ok) return;
    try {
      await api.deleteKnowledgeSource(id);
      setSources((prev) => prev.filter((s) => s.id !== id));
      if (selectedId === id) setSelectedId(null);
      toast("Knowledge source deleted");
    } catch (err) {
      setBanner(err instanceof Error ? err.message : "Delete failed");
    }
  };

  const handleUpdateSource = async (id: string, field: string, value: string | boolean) => {
    try {
      const updated = await api.updateKnowledgeSource(id, { [field]: value });
      setSources((prev) => prev.map((s) => (s.id === id ? updated : s)));
    } catch (err) {
      console.error("Update source failed", err);
    }
  };

  const handleUpdateRecord = async (id: string, field: string, value: string | boolean) => {
    try {
      const updated = await api.updateKnowledgeRecord(id, { [field]: value });
      setRecords((prev) => prev.map((r) => (r.id === id ? updated : r)));
    } catch (err) {
      console.error("Update record failed", err);
    }
  };

  const handleDeleteRecord = async (id: string) => {
    const ok = await confirm({
      title: "Delete record",
      message: "Delete this knowledge record? This cannot be undone.",
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (!ok) return;
    try {
      await api.deleteKnowledgeRecord(id);
      setRecords((prev) => prev.filter((r) => r.id !== id));
      refreshCounts();
      toast("Record deleted");
    } catch (err) {
      console.error("Delete record failed", err);
    }
  };

  const handleAddRecord = async () => {
    if (!selectedId || !newTitle.trim() || !newBody.trim()) return;
    try {
      const created = await api.createKnowledgeRecord(selectedId, { title: newTitle.trim(), body: newBody.trim() });
      setRecords((prev) => [...prev, created]);
      setNewTitle("");
      setNewBody("");
      setAddingRecord(false);
      refreshCounts();
    } catch (err) {
      console.error("Create record failed", err);
    }
  };

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !selectedId) return;
    setBusy(true);
    setBanner(null);
    try {
      const result = await api.importKnowledgeRecords(selectedId, file);
      setBanner(`Imported ${result.created} records (${result.skipped} skipped)`);
      await loadRecords(selectedId);
      refreshCounts();
    } catch {
      setBanner("Import failed. Expected CSV/Excel with title and body columns.");
    } finally {
      setBusy(false);
      if (importRef.current) importRef.current.value = "";
    }
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !selectedId) return;
    setBusy(true);
    setBanner(null);
    try {
      const result = await api.uploadKnowledgeFile(selectedId, file);
      setBanner(`Added "${result.title}" (${result.chars.toLocaleString()} characters)`);
      await loadRecords(selectedId);
      refreshCounts();
    } catch {
      setBanner("Upload failed. Supported formats: .txt, .md, .docx, .pdf, .pptx, .xlsx, .csv, .html");
    } finally {
      setBusy(false);
      if (uploadRef.current) uploadRef.current.value = "";
    }
  };

  const isBuiltIn = selected?.source_type === "offerings";

  return (
    <div className="flex h-full flex-col bg-brand-light-gray-2">
      {/* Header */}
      <header className="flex items-center justify-between border-b border-brand-light-gray-1 bg-surface px-6 py-3">
        <div className="flex items-center gap-3">
          <button
            onClick={onBack}
            className="rounded p-1 text-brand-mid-gray transition-colors hover:bg-brand-light-gray-2 hover:text-brand-dark-gray"
            title="Back to sessions"
          >
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5 3 12m0 0 7.5-7.5M3 12h18" />
            </svg>
          </button>
          <div>
            <h1 className="font-display text-lg font-bold text-brand-dark-gray">Knowledge Sources</h1>
            <p className="font-body text-xs text-brand-mid-gray">
              Manage the knowledge bases agents can match opportunities against
            </p>
          </div>
        </div>
      </header>

      {/* Banner */}
      {banner && (
        <div className="flex items-center justify-between border-b border-brand-teal-light/20 bg-brand-teal-light/5 px-6 py-2">
          <span className="font-body text-sm text-brand-teal">{banner}</span>
          <button onClick={() => setBanner(null)} className="text-brand-mid-gray hover:text-brand-dark-gray">
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      )}

      <div className="flex flex-1 overflow-hidden">
        {/* Source list */}
        <aside className="flex w-72 flex-col border-r border-brand-light-gray-1 bg-surface p-3">
          <div className="mb-2 flex items-center justify-between px-1">
            <span className="text-[10px] font-bold uppercase tracking-wider text-brand-mid-gray">Sources</span>
            <button
              onClick={() => setCreating(true)}
              className="rounded p-1 text-brand-mid-gray transition-colors hover:bg-brand-light-gray-2 hover:text-brand-teal"
              title="New knowledge source"
            >
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
            </button>
          </div>

          {creating && <div className="mb-2"><AddSourceForm onAdd={handleCreateSource} onCancel={() => setCreating(false)} /></div>}

          <div className="flex-1 space-y-1 overflow-y-auto">
            {loading ? (
              <p className="px-2 py-4 text-center font-body text-xs text-brand-mid-gray">Loading...</p>
            ) : sources.length === 0 ? (
              <p className="px-2 py-4 text-center font-body text-xs text-brand-mid-gray">No knowledge sources yet</p>
            ) : (
              sources.map((s) => {
                const badge = TYPE_BADGES[s.source_type] || TYPE_BADGES.collection;
                const isSelected = s.id === selectedId;
                return (
                  <div
                    key={s.id}
                    onClick={() => setSelectedId(s.id)}
                    className={`group cursor-pointer rounded-lg px-3 py-2 transition-colors ${
                      isSelected ? "bg-brand-teal/10 ring-1 ring-brand-teal/20" : "hover:bg-brand-light-gray-2"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className={`truncate text-sm font-medium ${isSelected ? "text-brand-teal" : "text-brand-dark-gray"}`}>
                        {s.name}
                      </span>
                      {s.source_type !== "offerings" && (
                        <button
                          onClick={(e) => { e.stopPropagation(); handleDeleteSource(s.id); }}
                          className="rounded p-0.5 text-brand-light-gray-1 opacity-0 transition-all hover:bg-red-50 hover:text-red-500 group-hover:opacity-100"
                          title="Delete source"
                        >
                          <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
                          </svg>
                        </button>
                      )}
                    </div>
                    <div className="mt-1 flex items-center gap-1.5">
                      <span className="inline-flex rounded-full px-1.5 py-0.5 text-[9px] font-medium text-white" style={{ backgroundColor: badge.color }}>
                        {badge.label}
                      </span>
                      <span className="text-[10px] text-brand-mid-gray">
                        {s.source_type === "offerings" ? "Offerings catalog" : `${s.record_count} record${s.record_count === 1 ? "" : "s"}`}
                      </span>
                      {!s.active && <span className="text-[10px] italic text-brand-mid-gray">inactive</span>}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </aside>

        {/* Records panel */}
        <div className="flex-1 overflow-auto p-4">
          {!selected ? (
            <div className="flex items-center justify-center py-20">
              <span className="font-body text-sm text-brand-mid-gray">Select or create a knowledge source</span>
            </div>
          ) : isBuiltIn ? (
            <div className="mx-auto max-w-lg rounded-xl bg-surface p-6 text-center shadow-sm">
              <h3 className="font-display text-base font-bold text-brand-dark-gray">{selected.name}</h3>
              <p className="mt-2 font-body text-sm text-brand-gray">
                This is the built-in source backed by the offerings catalog. Manage its contents in the Offerings Catalog tool.
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {/* Source toolbar */}
              <div className="flex items-center justify-between rounded-xl bg-surface px-4 py-3 shadow-sm">
                <div className="min-w-0">
                  <EditableCell value={selected.name} onSave={(v) => v && handleUpdateSource(selected.id, "name", v)} />
                  <div className="mt-0.5">
                    <EditableCell
                      value={selected.description}
                      onSave={(v) => handleUpdateSource(selected.id, "description", v)}
                      placeholder="Add a description..."
                    />
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {selected.source_type === "collection" && (
                    <>
                      <input ref={importRef} type="file" accept=".csv,.xlsx,.xls" onChange={handleImport} className="hidden" />
                      <button
                        onClick={() => importRef.current?.click()}
                        disabled={busy}
                        className="rounded-lg border border-brand-light-gray-1 px-3 py-1.5 text-sm font-medium text-brand-gray transition-colors hover:bg-brand-light-gray-2 disabled:opacity-50"
                      >
                        {busy ? "Working..." : "Import CSV/Excel"}
                      </button>
                    </>
                  )}
                  {selected.source_type === "files" && (
                    <>
                      <input ref={uploadRef} type="file" accept=".txt,.md,.markdown,.docx,.pdf,.pptx,.xlsx,.xls,.csv,.html,.htm" onChange={handleUpload} className="hidden" />
                      <button
                        onClick={() => uploadRef.current?.click()}
                        disabled={busy}
                        className="rounded-lg border border-brand-light-gray-1 px-3 py-1.5 text-sm font-medium text-brand-gray transition-colors hover:bg-brand-light-gray-2 disabled:opacity-50"
                      >
                        {busy ? "Working..." : "Upload File"}
                      </button>
                    </>
                  )}
                  <button
                    onClick={() => handleUpdateSource(selected.id, "active", !selected.active)}
                    className={`h-5 w-9 rounded-full transition-colors ${selected.active ? "bg-brand-teal" : "bg-brand-light-gray-1"}`}
                    title={selected.active ? "Active — click to deactivate" : "Inactive — click to activate"}
                  >
                    <span className={`block h-4 w-4 rounded-full bg-slate-50 shadow transition-transform ${selected.active ? "translate-x-4" : "translate-x-0.5"}`} />
                  </button>
                </div>
              </div>

              {/* Add record */}
              {addingRecord ? (
                <div className="rounded-lg border border-brand-teal-light/30 bg-brand-teal-light/5 p-4 space-y-2">
                  <input
                    autoFocus
                    value={newTitle}
                    onChange={(e) => setNewTitle(e.target.value)}
                    placeholder="Title..."
                    className="w-full rounded border border-brand-light-gray-1 px-2 py-1.5 text-sm focus:border-brand-teal"
                  />
                  <textarea
                    value={newBody}
                    onChange={(e) => setNewBody(e.target.value)}
                    placeholder="Body..."
                    rows={3}
                    className="w-full rounded border border-brand-light-gray-1 px-2 py-1.5 text-sm focus:border-brand-teal"
                  />
                  <div className="flex gap-2">
                    <button
                      onClick={handleAddRecord}
                      disabled={!newTitle.trim() || !newBody.trim()}
                      className="rounded-lg bg-brand-teal px-4 py-1.5 text-sm font-medium text-white transition-colors hover:bg-brand-teal-dark disabled:opacity-40"
                    >
                      Add
                    </button>
                    <button
                      onClick={() => { setAddingRecord(false); setNewTitle(""); setNewBody(""); }}
                      className="rounded-lg border border-brand-light-gray-1 px-4 py-1.5 text-sm text-brand-gray transition-colors hover:bg-brand-light-gray-2"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  onClick={() => setAddingRecord(true)}
                  className="flex items-center gap-1.5 rounded-lg border border-dashed border-brand-light-gray-1 px-3 py-2 text-sm text-brand-mid-gray transition-colors hover:border-brand-teal hover:text-brand-teal"
                >
                  <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                  </svg>
                  Add Record
                </button>
              )}

              {/* Records table */}
              {loadingRecords ? (
                <div className="py-10 text-center">
                  <span className="font-body text-sm text-brand-mid-gray">Loading records...</span>
                </div>
              ) : records.length === 0 ? (
                <div className="py-10 text-center">
                  <p className="font-body text-sm text-brand-mid-gray">
                    {selected.source_type === "files"
                      ? "No files yet. Upload a document (.txt, .md, .docx, .pdf, .pptx, .xlsx, .csv, .html) to add knowledge."
                      : "No records yet. Add records manually or import a CSV/Excel file with title and body columns."}
                  </p>
                </div>
              ) : (
                <div className="overflow-x-auto rounded-lg border border-brand-light-gray-1 bg-surface">
                  <table className="w-full min-w-[560px] text-left text-xs">
                    <thead>
                      <tr className="border-b border-brand-light-gray-1 bg-brand-light-gray-2/50">
                        <th className="px-3 py-2 font-display font-semibold text-brand-gray w-64">Title</th>
                        <th className="px-3 py-2 font-display font-semibold text-brand-gray">Body</th>
                        <th className="px-3 py-2 font-display font-semibold text-brand-gray w-16">Active</th>
                        <th className="px-3 py-2 w-10"></th>
                      </tr>
                    </thead>
                    <tbody>
                      {records.map((r) => (
                        <tr key={r.id} className="border-b border-brand-light-gray-1 last:border-0 hover:bg-brand-light-gray-2/30 transition-colors">
                          <td className="px-3 py-2 align-top font-medium text-brand-dark-gray">
                            <EditableCell value={r.title} onSave={(v) => handleUpdateRecord(r.id, "title", v)} placeholder="Add title..." />
                          </td>
                          <td className="px-3 py-2 align-top">
                            <EditableCell value={r.body} onSave={(v) => handleUpdateRecord(r.id, "body", v)} multiline placeholder="Add body..." />
                          </td>
                          <td className="px-3 py-2 align-top text-center">
                            <button
                              onClick={() => handleUpdateRecord(r.id, "active", !r.active)}
                              className={`h-5 w-9 rounded-full transition-colors ${r.active ? "bg-brand-teal" : "bg-brand-light-gray-1"}`}
                              title={r.active ? "Active — click to deactivate" : "Inactive — click to activate"}
                            >
                              <span className={`block h-4 w-4 rounded-full bg-slate-50 shadow transition-transform ${r.active ? "translate-x-4" : "translate-x-0.5"}`} />
                            </button>
                          </td>
                          <td className="px-3 py-2 align-top">
                            <button
                              onClick={() => handleDeleteRecord(r.id)}
                              className="rounded p-1 text-brand-mid-gray transition-colors hover:bg-red-50 hover:text-red-500"
                              title="Delete record"
                            >
                              <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
                              </svg>
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Format hint */}
      <div className="border-t border-brand-light-gray-1 bg-surface px-6 py-2">
        <p className="font-body text-[10px] text-brand-mid-gray">
          Collection imports expect CSV/Excel with title and body columns (extra columns are kept as metadata). File sources accept .txt, .md, .docx, .pdf, .pptx, .xlsx, .csv, and .html uploads — files are converted to Markdown on upload and only the Markdown is stored. Point an agent at a source in Administration.
        </p>
      </div>
    </div>
  );
}
