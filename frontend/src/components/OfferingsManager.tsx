import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Offering } from "../types";
import * as api from "../services/api";

const CATEGORY_COLORS: Record<string, string> = {
  Security: "#e2231a",
  Networking: "#0d9488",
  Productivity: "#7c3aed",
  Cloud: "#00b4d8",
  Collaboration: "#f59e0b",
  Observability: "#6366f1",
  "Data Management": "#0ea5e9",
  "Professional Services": "#f97316",
  "Managed Services": "#10b981",
};

const TAG_PALETTE = [
  "#0d9488",
  "#e2231a",
  "#7c3aed",
  "#00b4d8",
  "#f59e0b",
  "#10b981",
  "#6366f1",
  "#f97316",
  "#0ea5e9",
  "#db2777",
];

function categoryColor(cat: string): string {
  return CATEGORY_COLORS[cat] || "#666";
}

// Deterministic color per tag so dynamically created tags stay stable
function tagColor(tag: string): string {
  let hash = 0;
  for (let i = 0; i < tag.length; i++) {
    hash = (hash * 31 + tag.charCodeAt(i)) | 0;
  }
  return TAG_PALETTE[Math.abs(hash) % TAG_PALETTE.length];
}

// Inline editable cell
function EditableCell({
  value,
  onSave,
  multiline = false,
  placeholder = "",
  clamp = false,
  renderValue,
}: {
  value: string;
  onSave: (val: string) => void;
  multiline?: boolean;
  placeholder?: string;
  clamp?: boolean;
  renderValue?: (value: string) => React.ReactNode;
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
        className={`cursor-pointer rounded px-1 py-0.5 transition-colors hover:bg-brand-light-gray-2 ${
          clamp ? "line-clamp-3" : "block"
        } ${!value ? "italic text-brand-mid-gray" : ""}`}
        onClick={() => setEditing(true)}
        title={clamp && value ? value : "Click to edit"}
      >
        {renderValue ? renderValue(value) : value || placeholder || "—"}
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
        className="w-full rounded border border-brand-teal-light bg-white px-1.5 py-1 text-xs text-brand-dark-gray outline-none ring-1 ring-brand-teal-light/30"
        rows={3}
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
      className="w-full rounded border border-brand-teal-light bg-white px-1.5 py-1 text-xs text-brand-dark-gray outline-none ring-1 ring-brand-teal-light/30"
    />
  );
}

// Tag chip selector: toggle known tags or create a new one inline
function TagChips({
  value,
  onChange,
  knownTags,
  onCreateTag,
}: {
  value: string;
  onChange: (v: string) => void;
  knownTags: string[];
  onCreateTag: (tag: string) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [newTag, setNewTag] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const selected = new Set(value.split(",").map((s) => s.trim()).filter(Boolean));
  // Include selected tags that aren't in the known list yet so they stay visible
  const allTags = [...new Set([...knownTags, ...selected])].sort();

  useEffect(() => {
    if (adding && inputRef.current) inputRef.current.focus();
  }, [adding]);

  const toggle = (t: string) => {
    const next = new Set(selected);
    if (next.has(t)) next.delete(t);
    else next.add(t);
    onChange([...next].join(", "));
  };

  const commitNewTag = () => {
    const tag = newTag.trim();
    setAdding(false);
    setNewTag("");
    if (!tag) return;
    onCreateTag(tag);
    if (!selected.has(tag)) {
      onChange([...selected, tag].join(", "));
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-1">
      {allTags.map((t) => (
        <button
          key={t}
          type="button"
          onClick={() => toggle(t)}
          className={`rounded-full px-2 py-0.5 text-[10px] font-medium transition-colors ${
            selected.has(t)
              ? "text-white"
              : "bg-gray-100 text-gray-500 hover:bg-gray-200"
          }`}
          style={selected.has(t) ? { backgroundColor: tagColor(t) } : undefined}
        >
          {t}
        </button>
      ))}
      {adding ? (
        <input
          ref={inputRef}
          value={newTag}
          onChange={(e) => setNewTag(e.target.value)}
          onBlur={commitNewTag}
          onKeyDown={(e) => {
            if (e.key === "Enter") commitNewTag();
            if (e.key === "Escape") {
              setAdding(false);
              setNewTag("");
            }
          }}
          placeholder="New tag..."
          className="w-24 rounded-full border border-brand-teal-light bg-white px-2 py-0.5 text-[10px] text-brand-dark-gray outline-none"
        />
      ) : (
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="rounded-full border border-dashed border-brand-light-gray-1 px-2 py-0.5 text-[10px] text-brand-mid-gray transition-colors hover:border-brand-teal hover:text-brand-teal"
          title="Create a new tag"
        >
          + Tag
        </button>
      )}
    </div>
  );
}

// Add row form
function AddOfferingRow({
  onAdd,
  knownTags,
  onCreateTag,
}: {
  onAdd: (o: Partial<Offering>) => void;
  knownTags: string[];
  onCreateTag: (tag: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [vendor, setVendor] = useState("");
  const [productName, setProductName] = useState("");
  const [category, setCategory] = useState("");
  const [subcategory, setSubcategory] = useState("");
  const [description, setDescription] = useState("");
  const [useCases, setUseCases] = useState("");
  const [note, setNote] = useState("");
  const [tags, setTags] = useState("");

  const reset = () => {
    setVendor(""); setProductName(""); setCategory(""); setSubcategory("");
    setDescription(""); setUseCases(""); setNote(""); setTags("");
  };

  const handleAdd = () => {
    if (!vendor || !productName) return;
    onAdd({ vendor, product_name: productName, category, subcategory, description, use_cases: useCases, note, tags, active: true });
    reset();
    setOpen(false);
  };

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-1.5 rounded-lg border border-dashed border-brand-light-gray-1 px-3 py-2 text-sm text-brand-mid-gray transition-colors hover:border-brand-teal hover:text-brand-teal"
      >
        <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
        </svg>
        Add Offering
      </button>
    );
  }

  return (
    <div className="rounded-lg border border-brand-teal-light/30 bg-brand-teal-light/5 p-4 space-y-3">
      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="block text-xs font-medium text-brand-gray mb-1">Vendor *</label>
          <input value={vendor} onChange={(e) => setVendor(e.target.value)} placeholder="e.g. Fortinet" className="w-full rounded border border-brand-light-gray-1 px-2 py-1.5 text-sm outline-none focus:border-brand-teal" />
        </div>
        <div>
          <label className="block text-xs font-medium text-brand-gray mb-1">Product/Service *</label>
          <input value={productName} onChange={(e) => setProductName(e.target.value)} placeholder="e.g. FortiGate NGFW" className="w-full rounded border border-brand-light-gray-1 px-2 py-1.5 text-sm outline-none focus:border-brand-teal" />
        </div>
        <div>
          <label className="block text-xs font-medium text-brand-gray mb-1">Category</label>
          <input value={category} onChange={(e) => setCategory(e.target.value)} placeholder="e.g. Security" className="w-full rounded border border-brand-light-gray-1 px-2 py-1.5 text-sm outline-none focus:border-brand-teal" />
        </div>
      </div>
      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="block text-xs font-medium text-brand-gray mb-1">Sub-Category</label>
          <input value={subcategory} onChange={(e) => setSubcategory(e.target.value)} placeholder="e.g. Network Security" className="w-full rounded border border-brand-light-gray-1 px-2 py-1.5 text-sm outline-none focus:border-brand-teal" />
        </div>
        <div>
          <label className="block text-xs font-medium text-brand-gray mb-1">Note</label>
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Sold with deployment services" className="w-full rounded border border-brand-light-gray-1 px-2 py-1.5 text-sm outline-none focus:border-brand-teal" />
        </div>
        <div className="flex items-end gap-2">
          <button onClick={handleAdd} disabled={!vendor || !productName} className="rounded-lg bg-brand-teal px-4 py-1.5 text-sm font-medium text-white transition-colors hover:bg-brand-teal-dark disabled:opacity-40">Add</button>
          <button onClick={() => { reset(); setOpen(false); }} className="rounded-lg border border-brand-light-gray-1 px-4 py-1.5 text-sm text-brand-gray transition-colors hover:bg-brand-light-gray-2">Cancel</button>
        </div>
      </div>
      <div>
        <label className="block text-xs font-medium text-brand-gray mb-1">Tag(s)</label>
        <TagChips value={tags} onChange={setTags} knownTags={knownTags} onCreateTag={onCreateTag} />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-brand-gray mb-1">Description</label>
          <textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder="What it does..." rows={2} className="w-full rounded border border-brand-light-gray-1 px-2 py-1.5 text-sm outline-none focus:border-brand-teal" />
        </div>
        <div>
          <label className="block text-xs font-medium text-brand-gray mb-1">Use Cases</label>
          <textarea value={useCases} onChange={(e) => setUseCases(e.target.value)} placeholder="Pain points it solves..." rows={2} className="w-full rounded border border-brand-light-gray-1 px-2 py-1.5 text-sm outline-none focus:border-brand-teal" />
        </div>
      </div>
    </div>
  );
}

interface OfferingsManagerProps {
  onBack: () => void;
}

export default function OfferingsManager({ onBack }: OfferingsManagerProps) {
  const [offerings, setOfferings] = useState<Offering[]>([]);
  const [vendors, setVendors] = useState<string[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [tags, setTags] = useState<string[]>([]);
  const [filterVendor, setFilterVendor] = useState("");
  const [filterCategory, setFilterCategory] = useState("");
  const [filterTag, setFilterTag] = useState("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [o, v, c, t] = await Promise.all([
        api.listOfferings(),
        api.listOfferingVendors(),
        api.listOfferingCategories(),
        api.listOfferingTags(),
      ]);
      setOfferings(o);
      setVendors(v);
      setCategories(c);
      setTags(t);
    } catch (err) {
      console.error("Failed to load offerings", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const registerTag = useCallback((tag: string) => {
    setTags((prev) => (prev.includes(tag) ? prev : [...prev, tag].sort()));
  }, []);

  const filtered = useMemo(() => {
    let list = offerings;
    if (filterVendor) list = list.filter((o) => o.vendor === filterVendor);
    if (filterCategory) list = list.filter((o) => o.category === filterCategory);
    if (filterTag) list = list.filter((o) => o.tags?.includes(filterTag));
    if (search) {
      const s = search.toLowerCase();
      list = list.filter(
        (o) =>
          o.product_name.toLowerCase().includes(s) ||
          o.description.toLowerCase().includes(s) ||
          o.use_cases.toLowerCase().includes(s) ||
          o.vendor.toLowerCase().includes(s) ||
          (o.subcategory || "").toLowerCase().includes(s) ||
          (o.note || "").toLowerCase().includes(s) ||
          (o.tags || "").toLowerCase().includes(s)
      );
    }
    return list;
  }, [offerings, filterVendor, filterCategory, filterTag, search]);

  const handleUpdate = async (id: string, field: string, value: string | boolean) => {
    try {
      const updated = await api.updateOffering(id, { [field]: value });
      setOfferings((prev) => prev.map((o) => (o.id === id ? updated : o)));
    } catch (err) {
      console.error("Update failed", err);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await api.deleteOffering(id);
      setOfferings((prev) => prev.filter((o) => o.id !== id));
    } catch (err) {
      console.error("Delete failed", err);
    }
  };

  const handleAdd = async (data: Partial<Offering>) => {
    try {
      const created = await api.createOffering(data as any);
      setOfferings((prev) => [...prev, created]);
      // Refresh vendor/category lists
      const [v, c] = await Promise.all([api.listOfferingVendors(), api.listOfferingCategories()]);
      setVendors(v);
      setCategories(c);
    } catch (err) {
      console.error("Create failed", err);
    }
  };

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    setImportResult(null);
    try {
      const result = await api.importOfferings(file);
      setImportResult(`Imported ${result.created} offerings (${result.skipped} skipped)`);
      await load();
    } catch (err) {
      setImportResult("Import failed. Check file format.");
    } finally {
      setImporting(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const handleSeed = async () => {
    try {
      const replace = offerings.length > 0;
      const result = await api.seedOfferings(replace);
      if (result.created) {
        setImportResult(`${replace ? "Replaced with" : "Seeded"} ${result.created} sample offerings`);
      } else {
        setImportResult(result.message || "Database already seeded");
      }
      await load();
    } catch (err) {
      console.error("Seed failed", err);
    }
  };

  return (
    <div className="flex h-full flex-col bg-brand-light-gray-2">
      {/* Header */}
      <header className="flex items-center justify-between border-b border-brand-light-gray-1 bg-white px-6 py-3">
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
            <h1 className="font-display text-lg font-bold text-brand-dark-gray">Offerings Catalog</h1>
            <p className="font-body text-xs text-brand-mid-gray">
              Manage the products and services the Opportunity Specialist maps to
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleSeed}
            className="rounded-lg border border-brand-teal-light/30 px-3 py-1.5 text-sm font-medium text-brand-teal transition-colors hover:bg-brand-teal-light/10"
            title={offerings.length > 0
              ? "Replace all offerings with the latest sample catalog"
              : "Populate with a sample catalog of common vendor products and in-house services"}
          >
            {offerings.length > 0 ? "Reset to Sample Data" : "Load Sample Data"}
          </button>
          <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls" onChange={handleImport} className="hidden" />
          <button
            onClick={() => fileRef.current?.click()}
            disabled={importing}
            className="rounded-lg border border-brand-light-gray-1 px-3 py-1.5 text-sm font-medium text-brand-gray transition-colors hover:bg-brand-light-gray-2 disabled:opacity-50"
          >
            {importing ? "Importing..." : "Import CSV/Excel"}
          </button>
          <span className="font-body text-xs text-brand-mid-gray">
            {filtered.length} of {offerings.length} offerings
          </span>
        </div>
      </header>

      {/* Import result banner */}
      {importResult && (
        <div className="flex items-center justify-between border-b border-brand-teal-light/20 bg-brand-teal-light/5 px-6 py-2">
          <span className="font-body text-sm text-brand-teal">{importResult}</span>
          <button onClick={() => setImportResult(null)} className="text-brand-mid-gray hover:text-brand-dark-gray">
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-3 border-b border-brand-light-gray-1 bg-white px-6 py-2">
        <div className="flex items-center gap-1.5">
          <span className="font-body text-xs font-medium text-brand-mid-gray">Vendor:</span>
          <select
            value={filterVendor}
            onChange={(e) => setFilterVendor(e.target.value)}
            className="rounded border border-brand-light-gray-1 bg-white px-2 py-1 text-xs text-brand-dark-gray outline-none focus:border-brand-teal"
          >
            <option value="">All</option>
            {vendors.map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="font-body text-xs font-medium text-brand-mid-gray">Category:</span>
          <select
            value={filterCategory}
            onChange={(e) => setFilterCategory(e.target.value)}
            className="rounded border border-brand-light-gray-1 bg-white px-2 py-1 text-xs text-brand-dark-gray outline-none focus:border-brand-teal"
          >
            <option value="">All</option>
            {categories.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="font-body text-xs font-medium text-brand-mid-gray">Tag:</span>
          <select
            value={filterTag}
            onChange={(e) => setFilterTag(e.target.value)}
            className="rounded border border-brand-light-gray-1 bg-white px-2 py-1 text-xs text-brand-dark-gray outline-none focus:border-brand-teal"
          >
            <option value="">All</option>
            {tags.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div className="flex-1">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search offerings..."
            className="w-full max-w-xs rounded border border-brand-light-gray-1 bg-white px-2.5 py-1 text-xs text-brand-dark-gray outline-none focus:border-brand-teal"
          />
        </div>
        {(filterVendor || filterCategory || filterTag || search) && (
          <button
            onClick={() => { setFilterVendor(""); setFilterCategory(""); setFilterTag(""); setSearch(""); }}
            className="text-xs text-brand-mid-gray hover:text-brand-teal"
          >
            Clear filters
          </button>
        )}
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto p-4">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <span className="font-body text-sm text-brand-mid-gray">Loading offerings...</span>
          </div>
        ) : offerings.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <p className="font-body text-sm text-brand-mid-gray mb-3">No offerings in the catalog yet.</p>
            <p className="font-body text-xs text-brand-mid-gray mb-4">
              Click "Load Sample Data" to populate with a sample catalog,
              or import your own via CSV/Excel.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            <AddOfferingRow onAdd={handleAdd} knownTags={tags} onCreateTag={registerTag} />

            <div className="overflow-hidden rounded-lg border border-brand-light-gray-1 bg-white">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-brand-light-gray-1 bg-brand-light-gray-2/50">
                    <th className="px-3 py-2 font-display font-semibold text-brand-gray">Vendor</th>
                    <th className="px-3 py-2 font-display font-semibold text-brand-gray">Product/Service</th>
                    <th className="px-3 py-2 font-display font-semibold text-brand-gray">Category</th>
                    <th className="px-3 py-2 font-display font-semibold text-brand-gray">Sub-Category</th>
                    <th className="px-3 py-2 font-display font-semibold text-brand-gray">Description</th>
                    <th className="px-3 py-2 font-display font-semibold text-brand-gray">Use Cases</th>
                    <th className="px-3 py-2 font-display font-semibold text-brand-gray">Note</th>
                    <th className="px-3 py-2 font-display font-semibold text-brand-gray">Tags</th>
                    <th className="px-3 py-2 font-display font-semibold text-brand-gray w-16">Active</th>
                    <th className="px-3 py-2 w-10"></th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((o) => (
                    <tr key={o.id} className="border-b border-brand-light-gray-1 last:border-0 hover:bg-brand-light-gray-2/30 transition-colors">
                      <td className="px-3 py-2 align-top">
                        <EditableCell value={o.vendor} onSave={(v) => handleUpdate(o.id, "vendor", v)} />
                      </td>
                      <td className="px-3 py-2 align-top font-medium text-brand-dark-gray">
                        <EditableCell value={o.product_name} onSave={(v) => handleUpdate(o.id, "product_name", v)} />
                      </td>
                      <td className="px-3 py-2 align-top">
                        <EditableCell
                          value={o.category}
                          onSave={(v) => handleUpdate(o.id, "category", v)}
                          placeholder="Add category..."
                          renderValue={(v) =>
                            v ? (
                              <span
                                className="inline-flex w-fit items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium"
                                style={{ backgroundColor: `${categoryColor(v)}15`, color: categoryColor(v) }}
                              >
                                {v}
                              </span>
                            ) : (
                              "Add category..."
                            )
                          }
                        />
                      </td>
                      <td className="px-3 py-2 align-top">
                        <EditableCell value={o.subcategory || ""} onSave={(v) => handleUpdate(o.id, "subcategory", v)} placeholder="Add sub-category..." />
                      </td>
                      <td className="px-3 py-2 align-top max-w-[200px]">
                        <EditableCell value={o.description} onSave={(v) => handleUpdate(o.id, "description", v)} multiline clamp placeholder="Add description..." />
                      </td>
                      <td className="px-3 py-2 align-top max-w-[180px]">
                        <EditableCell value={o.use_cases} onSave={(v) => handleUpdate(o.id, "use_cases", v)} multiline clamp placeholder="Add use cases..." />
                      </td>
                      <td className="px-3 py-2 align-top max-w-[160px]">
                        <EditableCell value={o.note} onSave={(v) => handleUpdate(o.id, "note", v)} multiline clamp placeholder="Add note..." />
                      </td>
                      <td className="px-3 py-2 align-top">
                        <TagChips
                          value={o.tags || ""}
                          onChange={(v) => handleUpdate(o.id, "tags", v)}
                          knownTags={tags}
                          onCreateTag={registerTag}
                        />
                      </td>
                      <td className="px-3 py-2 align-top text-center">
                        <button
                          onClick={() => handleUpdate(o.id, "active", !o.active)}
                          className={`h-5 w-9 rounded-full transition-colors ${o.active ? "bg-brand-teal" : "bg-brand-light-gray-1"}`}
                          title={o.active ? "Active — click to deactivate" : "Inactive — click to activate"}
                        >
                          <span className={`block h-4 w-4 rounded-full bg-white shadow transition-transform ${o.active ? "translate-x-4" : "translate-x-0.5"}`} />
                        </button>
                      </td>
                      <td className="px-3 py-2 align-top">
                        <button
                          onClick={() => handleDelete(o.id)}
                          className="rounded p-1 text-brand-mid-gray transition-colors hover:bg-red-50 hover:text-red-500"
                          title="Delete offering"
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

            {filtered.length === 0 && offerings.length > 0 && (
              <div className="py-8 text-center">
                <p className="font-body text-sm text-brand-mid-gray">No offerings match your filters.</p>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Import format hint */}
      <div className="border-t border-brand-light-gray-1 bg-white px-6 py-2">
        <p className="font-body text-[10px] text-brand-mid-gray">
          CSV/Excel import columns: vendor, product_name, category, subcategory, description, use_cases, note, tags. Legacy column names (discipline, delivery_model, practice) are accepted as aliases.
        </p>
      </div>
    </div>
  );
}
