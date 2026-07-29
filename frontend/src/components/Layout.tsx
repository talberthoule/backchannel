import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useSensor,
  useSensors,
  useDroppable,
  useDraggable,
} from "@dnd-kit/core";
import type { DragEndEvent } from "@dnd-kit/core";
import type { Session, SessionGroup } from "../types";
import * as api from "../services/api";
import { useConfirm } from "./ConfirmProvider";

interface LayoutProps {
  sessions: Session[];
  groups: SessionGroup[];
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewSession: () => void;
  onOpenOfferings: () => void;
  onOpenKnowledge: () => void;
  onOpenAdmin: () => void;
  showingOfferings?: boolean;
  showingKnowledge?: boolean;
  showingAdmin?: boolean;
  onDeleteSession: (id: string) => Promise<void>;
  onRefreshGroups: () => void;
  onRefreshSessions: () => void;
  children: React.ReactNode;
}

const stateBadge = (state: Session["state"]) => {
  switch (state) {
    case "pre_call":
      return <span className="inline-flex items-center rounded-full bg-brand-teal/15 px-2 py-0.5 text-xs font-medium text-brand-teal">Pre-Call</span>;
    case "active":
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-400 opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-green-500" />
          </span>
          Active
        </span>
      );
    case "completed":
      return <span className="inline-flex items-center rounded-full bg-brand-light-gray-1/60 px-2 py-0.5 text-xs font-medium text-brand-gray">Completed</span>;
  }
};

// ── Draggable session row ──────────────────────────────────────────────

function DraggableSession({ session, isActive, onClick, groups, onMoveToGroup, onRename, onDelete }: {
  session: Session;
  isActive: boolean;
  onClick: () => void;
  groups: SessionGroup[];
  onMoveToGroup: (sessionId: string, groupId: string | null) => void;
  onRename: (sessionId: string, name: string) => Promise<void>;
  onDelete: (sessionId: string) => Promise<void>;
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: session.id });
  const [showMenu, setShowMenu] = useState(false);
  const [editingName, setEditingName] = useState(false);
  const [draftName, setDraftName] = useState(session.name);
  const nameInputRef = useRef<HTMLInputElement>(null);
  const menuBtnRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const { confirm } = useConfirm();

  const handleDelete = async () => {
    const ok = await confirm({
      title: "Delete session",
      message: "Delete this session and all its data? This cannot be undone.",
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (ok) await onDelete(session.id);
  };

  // Close menu on outside click
  useEffect(() => {
    if (!showMenu) return;
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node) &&
          menuBtnRef.current && !menuBtnRef.current.contains(e.target as Node)) {
        setShowMenu(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [showMenu]);

  return (
    <div ref={setNodeRef} className={`group relative ${isDragging ? "opacity-30" : ""}`}>
      <div
        className={`mb-0.5 flex w-full items-start rounded-lg px-3 py-2 text-left transition-colors cursor-pointer ${
          isActive ? "bg-brand-teal/10 ring-1 ring-brand-teal/20" : "hover:bg-brand-light-gray-2"
        }`}
        onClick={onClick}
      >
        {/* Drag handle */}
        <span
          {...attributes}
          {...listeners}
          className="mr-1.5 mt-1 cursor-grab text-brand-light-gray-1 opacity-0 group-hover:opacity-100 transition-opacity active:cursor-grabbing"
          onClick={(e) => e.stopPropagation()}
        >
          <svg className="h-3.5 w-3.5" fill="currentColor" viewBox="0 0 20 20">
            <path d="M7 2a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM13 2a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM7 8a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM13 8a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM7 14a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM13 14a2 2 0 1 0 0 4 2 2 0 0 0 0-4z" />
          </svg>
        </span>

        <div className="flex-1 min-w-0">
          {editingName ? (
            <input
              ref={nameInputRef}
              value={draftName}
              onChange={(e) => setDraftName(e.target.value)}
              onBlur={async () => {
                setEditingName(false);
                const trimmed = draftName.trim();
                if (trimmed && trimmed !== session.name) await onRename(session.id, trimmed);
                else setDraftName(session.name);
              }}
              onKeyDown={async (e) => {
                if (e.key === "Enter") { (e.target as HTMLInputElement).blur(); }
                if (e.key === "Escape") { setDraftName(session.name); setEditingName(false); }
              }}
              onClick={(e) => e.stopPropagation()}
              className={`text-sm font-medium w-full bg-transparent border-b border-brand-teal ${isActive ? "text-brand-teal" : "text-brand-dark-gray"}`}
              autoFocus
            />
          ) : (
            <span
              className={`text-sm font-medium truncate block ${isActive ? "text-brand-teal" : "text-brand-dark-gray"}`}
              onDoubleClick={(e) => { e.stopPropagation(); setDraftName(session.name); setEditingName(true); }}
              title="Double-click to rename"
            >
              {session.name}
            </span>
          )}
          <div className="mt-0.5 flex items-center gap-1.5">
            {stateBadge(session.state)}
            <button
              ref={menuBtnRef}
              onClick={(e) => { e.stopPropagation(); setShowMenu(!showMenu); }}
              className="rounded p-0.5 text-brand-mid-gray opacity-0 group-hover:opacity-100 hover:bg-brand-light-gray-2 hover:text-brand-dark-gray transition-all"
              title="Move to group"
            >
              <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 12.75V12A2.25 2.25 0 0 1 4.5 9.75h15A2.25 2.25 0 0 1 21.75 12v.75m-8.69-6.44-2.12-2.12a1.5 1.5 0 0 0-1.061-.44H4.5A2.25 2.25 0 0 0 2.25 6v12a2.25 2.25 0 0 0 2.25 2.25h15A2.25 2.25 0 0 0 21.75 18V9a2.25 2.25 0 0 0-2.25-2.25h-5.379a1.5 1.5 0 0 1-1.06-.44Z" />
              </svg>
            </button>
          </div>
        </div>

        {/* Delete button — top-right, away from group button */}
        <button
          onClick={(e) => {
            e.stopPropagation();
            void handleDelete();
          }}
          className="ml-1 mt-0.5 flex-shrink-0 rounded p-1 text-brand-light-gray-1 opacity-0 group-hover:opacity-100 hover:bg-red-50 hover:text-red-500 transition-all"
          title="Delete session"
        >
          <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
          </svg>
        </button>
      </div>

      {/* Fixed-position menu portal */}
      {showMenu && menuBtnRef.current && (() => {
        const rect = menuBtnRef.current!.getBoundingClientRect();
        const spaceBelow = window.innerHeight - rect.bottom;
        const menuHeight = (groups.length + 1) * 28 + 8;
        const top = spaceBelow > menuHeight ? rect.bottom + 4 : rect.top - menuHeight - 4;
        return (
          <div
            ref={menuRef}
            className="fixed z-50 w-44 rounded-lg border border-brand-light-gray-1 bg-surface py-1 shadow-lg"
            style={{ top, left: rect.right + 4 }}
          >
            <button
              onClick={() => { onMoveToGroup(session.id, null); setShowMenu(false); }}
              className={`block w-full px-3 py-1.5 text-left text-xs transition-colors ${!session.group_id ? "font-semibold text-brand-teal" : "text-brand-dark-gray hover:bg-brand-light-gray-2"}`}
            >
              No group
            </button>
            {groups.map((g) => (
              <button
                key={g.id}
                onClick={() => { onMoveToGroup(session.id, g.id); setShowMenu(false); }}
                className={`block w-full px-3 py-1.5 text-left text-xs transition-colors ${session.group_id === g.id ? "font-semibold text-brand-teal" : "text-brand-dark-gray hover:bg-brand-light-gray-2"}`}
              >
                {g.name}
              </button>
            ))}
          </div>
        );
      })()}
    </div>
  );
}

// ── Droppable group folder ─────────────────────────────────────────────

type GroupDeleteDependencies = Pick<ReturnType<typeof useConfirm>, "confirm" | "toast"> & {
  deleteGroup: (id: string) => Promise<void>;
  refreshGroups: () => void;
  refreshSessions: () => void;
};

export async function deleteGroupWithConfirmation(
  group: Pick<SessionGroup, "id" | "name">,
  dependencies: GroupDeleteDependencies,
): Promise<void> {
  const confirmed = await dependencies.confirm({
    title: "Delete group",
    message: `Delete "${group.name}"? Sessions in this group will move to Sessions and will not be deleted.`,
    confirmLabel: "Delete group",
    tone: "danger",
  });
  if (!confirmed) return;

  try {
    await dependencies.deleteGroup(group.id);
    dependencies.refreshGroups();
    dependencies.refreshSessions();
  } catch {
    dependencies.toast(
      `Could not delete "${group.name}". Check your connection and try again.`,
    );
  }
}

export function DroppableGroup({ group, children, isExpanded, onToggle, onDelete, sessionCount }: {
  group: SessionGroup;
  children: React.ReactNode;
  isExpanded: boolean;
  onToggle: () => void;
  onDelete: () => void;
  sessionCount: number;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: `group-${group.id}` });

  return (
    <div ref={setNodeRef} className={`mt-1 rounded-lg transition-colors ${isOver ? "bg-brand-teal/5 ring-1 ring-brand-teal/20" : ""}`}>
      <div className="flex items-center gap-1 px-1 py-1">
        <button onClick={onToggle} className="flex min-w-0 flex-1 items-center gap-1.5 rounded px-2 py-1 text-left transition-colors hover:bg-brand-light-gray-2">
          <svg className={`h-3 w-3 text-brand-mid-gray transition-transform ${isExpanded ? "rotate-90" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
          </svg>
          <svg className="h-3.5 w-3.5 text-brand-mid-gray" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 12.75V12A2.25 2.25 0 0 1 4.5 9.75h15A2.25 2.25 0 0 1 21.75 12v.75m-8.69-6.44-2.12-2.12a1.5 1.5 0 0 0-1.061-.44H4.5A2.25 2.25 0 0 0 2.25 6v12a2.25 2.25 0 0 0 2.25 2.25h15A2.25 2.25 0 0 0 21.75 18V9a2.25 2.25 0 0 0-2.25-2.25h-5.379a1.5 1.5 0 0 1-1.06-.44Z" />
          </svg>
          <span className="text-sm font-semibold text-brand-dark-gray truncate">{group.name}</span>
          <span className="shrink-0 text-[10px] font-medium text-brand-mid-gray bg-brand-light-gray-2 px-1.5 py-0.5 rounded-full">{sessionCount}</span>
        </button>
        <button
          type="button"
          onClick={onDelete}
          aria-label={`Delete ${group.name} group`}
          title="Delete group"
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-brand-mid-gray transition-colors hover:bg-red-50 hover:text-red-600"
        >
          <svg aria-hidden="true" className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.75}>
            <path strokeLinecap="round" strokeLinejoin="round" d="m14.74 9-.35 9m-4.78 0L9.26 9m9.97-3.21c.34.05.68.1 1.02.16m-1.02-.16L18.16 19.67A2.25 2.25 0 0 1 15.92 21H8.08a2.25 2.25 0 0 1-2.24-1.33L4.77 5.79m14.46 0A48.1 48.1 0 0 0 15.75 5.25m-10.98.54c-.34.05-.68.1-1.02.16m1.02-.16A48.1 48.1 0 0 1 8.25 5.25m7.5 0V4.33c0-1.18-.91-2.16-2.09-2.2a52.7 52.7 0 0 0-3.32 0c-1.18.04-2.09 1.02-2.09 2.2v.92m7.5 0a48.7 48.7 0 0 0-7.5 0" />
          </svg>
        </button>
      </div>
      {isExpanded && <div className="pl-4">{children}</div>}
      {isExpanded && sessionCount === 0 && (
        <p className="pl-6 py-2 text-[10px] text-brand-mid-gray italic">
          {isOver ? "Drop here" : "Empty group"}
        </p>
      )}
    </div>
  );
}

// Droppable zone for "ungrouped"
function DroppableUngrouped({ children }: { children: React.ReactNode }) {
  const { setNodeRef, isOver } = useDroppable({ id: "group-ungrouped" });
  return (
    <div ref={setNodeRef} className={`rounded-lg transition-colors ${isOver ? "bg-brand-teal/5" : ""}`}>
      {children}
    </div>
  );
}

// ── Main Layout ────────────────────────────────────────────────────────

export default function Layout({
  sessions,
  groups,
  activeSessionId,
  onSelectSession,
  onNewSession,
  onOpenOfferings,
  onOpenKnowledge,
  onOpenAdmin,
  showingOfferings,
  showingKnowledge,
  showingAdmin,
  onDeleteSession,
  onRefreshGroups,
  onRefreshSessions,
  children,
}: LayoutProps) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(true);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [isDesktop, setIsDesktop] = useState(true);
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(() => new Set(groups.map((g) => g.id)));
  const [creatingGroup, setCreatingGroup] = useState(false);
  const [newGroupName, setNewGroupName] = useState("");
  const [draggedId, setDraggedId] = useState<string | null>(null);
  const { confirm, toast } = useConfirm();

  // Track the md breakpoint so the sidebar is an off-canvas drawer on mobile
  // (full width, never the icon rail) and an in-flow collapsible rail on desktop.
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 768px)");
    const update = () => setIsDesktop(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);

  // Close the mobile drawer after any navigation.
  useEffect(() => {
    setMobileOpen(false);
  }, [activeSessionId, showingOfferings, showingKnowledge, showingAdmin]);

  const collapsed = isDesktop ? sidebarCollapsed : false;

  // Theme: explicit user choice wins over OS preference; persisted in storage.
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    const saved = typeof localStorage !== "undefined" ? localStorage.getItem("bc-theme") : null;
    if (saved === "light" || saved === "dark") return saved;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("bc-theme", theme);
  }, [theme]);

  // Keep expanded groups in sync when new groups are created
  useEffect(() => {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      for (const g of groups) next.add(g.id);
      return next;
    });
  }, [groups]);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } })
  );

  const grouped = useMemo(() => {
    // Sort helper: active sessions first, then by name
    const withActiveFirst = (list: Session[]) =>
      [...list].sort((a, b) => {
        if (a.state === "active" && b.state !== "active") return -1;
        if (a.state !== "active" && b.state === "active") return 1;
        return 0;
      });

    const ungrouped = withActiveFirst(sessions.filter((s) => !s.group_id));
    const byGroup = groups.map((g) => ({
      group: g,
      sessions: withActiveFirst(sessions.filter((s) => s.group_id === g.id)),
    }));
    return { ungrouped, byGroup };
  }, [sessions, groups]);

  const toggleGroup = (id: string) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const handleCreateGroup = async () => {
    if (!newGroupName.trim()) return;
    await api.createGroup(newGroupName.trim());
    setNewGroupName("");
    setCreatingGroup(false);
    onRefreshGroups();
  };

  const handleDeleteGroup = async (group: SessionGroup) => {
    await deleteGroupWithConfirmation(group, {
      confirm,
      deleteGroup: api.deleteGroup,
      refreshGroups: onRefreshGroups,
      refreshSessions: onRefreshSessions,
      toast,
    });
  };

  const handleMoveToGroup = async (sessionId: string, groupId: string | null) => {
    await api.updateSession(sessionId, { group_id: groupId } as any);
    onRefreshSessions();
  };

  const handleRenameSession = async (sessionId: string, name: string) => {
    await api.updateSession(sessionId, { name });
    onRefreshSessions();
  };

  const handleDeleteSessionFromSidebar = async (sessionId: string) => {
    await onDeleteSession(sessionId);
  };

  const handleDragEnd = async (event: DragEndEvent) => {
    setDraggedId(null);
    const { active, over } = event;
    if (!over) return;

    const sessionId = active.id as string;
    const dropTarget = over.id as string;

    let targetGroupId: string | null = null;
    if (dropTarget === "group-ungrouped") {
      targetGroupId = null;
    } else if (dropTarget.startsWith("group-")) {
      targetGroupId = dropTarget.replace("group-", "");
    } else {
      return;
    }

    const session = sessions.find((s) => s.id === sessionId);
    if (session && session.group_id !== targetGroupId) {
      await handleMoveToGroup(sessionId, targetGroupId);
    }
  };

  const draggedSession = draggedId ? sessions.find((s) => s.id === draggedId) : null;

  return (
    <div className="flex h-screen flex-col bg-canvas font-body">
      <header className="flex items-center justify-between border-b border-brand-light-gray-1 bg-surface px-4 py-3 shadow-sm md:px-6">
        <div className="flex items-center gap-2.5">
          <button
            type="button"
            onClick={() => setMobileOpen(true)}
            className="flex h-9 w-9 items-center justify-center rounded-lg text-brand-gray transition-colors hover:bg-brand-light-gray-2 hover:text-brand-teal md:hidden"
            aria-label="Open menu"
          >
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5M3.75 17.25h16.5" />
            </svg>
          </button>
          {/* Brand mark — matches site/assets/favicon.svg on the landing page */}
          <svg className="h-7 w-7" viewBox="0 0 64 64" fill="none" aria-hidden="true">
            <rect width="64" height="64" rx="14" fill="#0f172a" />
            <rect x="10" y="26" width="7" height="18" rx="3.5" fill="#0d9488" />
            <rect x="21" y="16" width="7" height="38" rx="3.5" fill="#0d9488" />
            <rect x="32" y="8" width="7" height="48" rx="3.5" fill="#2dd4bf" />
            <rect x="43" y="20" width="7" height="30" rx="3.5" fill="#0d9488" />
            <rect x="52" y="28" width="7" height="14" rx="3.5" fill="#2dd4bf" />
          </svg>
          <span className="font-display text-[19px] font-bold tracking-tight text-brand-dark-gray">backchannel</span>
        </div>
        <button
          type="button"
          onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
          className="flex h-9 w-9 items-center justify-center rounded-lg text-brand-gray transition-colors hover:bg-brand-light-gray-2 hover:text-brand-teal"
          aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          title={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
        >
          {theme === "dark" ? (
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.8}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v2.25m6.364.386-1.591 1.591M21 12h-2.25m-.386 6.364-1.591-1.591M12 18.75V21m-4.773-4.227-1.591 1.591M5.25 12H3m4.227-4.773L5.636 5.636M15.75 12a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0Z" />
            </svg>
          ) : (
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.8}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M21.752 15.002A9.718 9.718 0 0 1 18 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 0 0 3 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 0 0 9.002-5.998Z" />
            </svg>
          )}
        </button>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Mobile drawer backdrop */}
        {mobileOpen && (
          <div
            className="fixed inset-0 z-30 bg-slate-900/40 md:hidden"
            onClick={() => setMobileOpen(false)}
            aria-hidden="true"
          />
        )}
        <aside
          className={`fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r border-brand-light-gray-1 bg-surface transition-transform duration-200 md:static md:z-auto md:translate-x-0 md:transition-[width] ${
            mobileOpen ? "translate-x-0" : "-translate-x-full"
          } ${collapsed ? "md:w-16" : "md:w-64"}`}
        >
          {collapsed ? (
            <>
              <div className="flex flex-col items-center gap-2 p-2">
                <button
                  type="button"
                  onClick={() => setSidebarCollapsed(false)}
                  className="flex h-11 w-11 items-center justify-center rounded-lg text-brand-gray transition-colors hover:bg-brand-light-gray-2 hover:text-brand-teal focus:ring-2 focus:ring-brand-teal-light"
                  aria-label="Expand sidebar"
                  aria-expanded={false}
                  title="Expand sidebar"
                >
                  <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="m9 5 7 7-7 7" />
                  </svg>
                </button>
                <button
                  type="button"
                  onClick={onNewSession}
                  className="flex h-11 w-11 items-center justify-center rounded-lg bg-brand-teal text-white shadow-sm transition-colors hover:bg-brand-teal-dark focus:ring-2 focus:ring-brand-teal-light"
                  aria-label="New session"
                  title="New session"
                >
                  <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                  </svg>
                </button>
              </div>

              <div className="mx-auto mb-2 h-px w-8 bg-brand-light-gray-1" />

              <div className="flex flex-col items-center gap-2 px-2 pb-2">
                <button
                  type="button"
                  onClick={onOpenOfferings}
                  className={`flex h-11 w-11 items-center justify-center rounded-lg transition-colors focus:ring-2 focus:ring-brand-teal-light ${showingOfferings ? "bg-brand-teal/10 text-brand-teal ring-1 ring-brand-teal/20" : "text-brand-gray hover:bg-brand-light-gray-2 hover:text-brand-dark-gray"}`}
                  aria-label="Offerings Catalog"
                  title="Offerings Catalog"
                >
                  <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M20.25 14.15v4.25c0 1.094-.787 2.036-1.872 2.18-2.087.277-4.216.42-6.378.42s-4.291-.143-6.378-.42c-1.085-.144-1.872-1.086-1.872-2.18v-4.25m16.5 0a2.18 2.18 0 0 0 .75-1.661V8.706c0-1.081-.768-2.015-1.837-2.175a48.114 48.114 0 0 0-3.413-.387m4.5 8.006c-.194.165-.42.295-.673.38A23.978 23.978 0 0 1 12 15.75c-2.648 0-5.195-.429-7.577-1.22a2.016 2.016 0 0 1-.673-.38m0 0A2.18 2.18 0 0 1 3 12.489V8.706c0-1.081.768-2.015 1.837-2.175a48.111 48.111 0 0 1 3.413-.387m7.5 0V5.25A2.25 2.25 0 0 0 13.5 3h-3a2.25 2.25 0 0 0-2.25 2.25v.894m7.5 0a48.667 48.667 0 0 0-7.5 0" /></svg>
                </button>
                <button
                  type="button"
                  onClick={onOpenKnowledge}
                  className={`flex h-11 w-11 items-center justify-center rounded-lg transition-colors focus:ring-2 focus:ring-brand-teal-light ${showingKnowledge ? "bg-brand-teal/10 text-brand-teal ring-1 ring-brand-teal/20" : "text-brand-gray hover:bg-brand-light-gray-2 hover:text-brand-dark-gray"}`}
                  aria-label="Knowledge Sources"
                  title="Knowledge Sources"
                >
                  <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25" /></svg>
                </button>
                <button
                  type="button"
                  onClick={onOpenAdmin}
                  className={`flex h-11 w-11 items-center justify-center rounded-lg transition-colors focus:ring-2 focus:ring-brand-teal-light ${showingAdmin ? "bg-brand-teal/10 text-brand-teal ring-1 ring-brand-teal/20" : "text-brand-gray hover:bg-brand-light-gray-2 hover:text-brand-dark-gray"}`}
                  aria-label="Administration"
                  title="Administration"
                >
                  <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" /><path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" /></svg>
                </button>
              </div>

              <div className="mx-auto mb-2 h-px w-8 bg-brand-light-gray-1" />

              <nav className="flex flex-1 flex-col items-center gap-2 overflow-y-auto px-2 pb-4" aria-label="Sessions">
                {sessions.map((session) => {
                  const isActive = session.id === activeSessionId;
                  const initial = session.name.trim().charAt(0).toUpperCase() || "S";
                  return (
                    <button
                      key={session.id}
                      type="button"
                      onClick={() => onSelectSession(session.id)}
                      className={`relative flex h-11 w-11 items-center justify-center rounded-lg text-xs font-semibold transition-colors focus:ring-2 focus:ring-brand-teal-light ${
                        isActive ? "bg-brand-teal text-white shadow-sm" : "bg-brand-light-gray-2 text-brand-gray hover:bg-brand-teal/10 hover:text-brand-teal"
                      }`}
                      aria-label={`Open ${session.name}`}
                      aria-current={isActive ? "page" : undefined}
                      title={session.name}
                    >
                      {initial}
                      {session.state === "active" && (
                        <span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-green-400 ring-1 ring-white" />
                      )}
                    </button>
                  );
                })}
              </nav>
            </>
          ) : (
            <>
              <div className="flex items-center gap-2 p-4">
                <button onClick={onNewSession} className="flex-1 rounded-lg bg-brand-teal px-4 py-2 font-display text-sm font-semibold text-white shadow-sm transition-colors hover:bg-brand-teal-dark">
                  + New Session
                </button>
                <button
                  type="button"
                  onClick={() => { setSidebarCollapsed(true); setMobileOpen(false); }}
                  className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg text-brand-gray transition-colors hover:bg-brand-light-gray-2 hover:text-brand-teal focus:ring-2 focus:ring-brand-teal-light"
                  aria-label="Collapse sidebar"
                  aria-expanded={true}
                  title="Collapse sidebar"
                >
                  <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="m15 19-7-7 7-7" />
                  </svg>
                </button>
              </div>

              {/* Tool links */}
              <div className="px-4 pb-2 space-y-1">
                <div className="mb-2 text-[10px] font-bold uppercase tracking-wider text-brand-mid-gray">
                  Tools
                </div>
                <button
                  onClick={onOpenOfferings}
                  className={`flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${showingOfferings ? "bg-brand-teal/10 text-brand-teal ring-1 ring-brand-teal/20" : "text-brand-gray hover:bg-brand-light-gray-2 hover:text-brand-dark-gray"}`}
                >
                  <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M20.25 14.15v4.25c0 1.094-.787 2.036-1.872 2.18-2.087.277-4.216.42-6.378.42s-4.291-.143-6.378-.42c-1.085-.144-1.872-1.086-1.872-2.18v-4.25m16.5 0a2.18 2.18 0 0 0 .75-1.661V8.706c0-1.081-.768-2.015-1.837-2.175a48.114 48.114 0 0 0-3.413-.387m4.5 8.006c-.194.165-.42.295-.673.38A23.978 23.978 0 0 1 12 15.75c-2.648 0-5.195-.429-7.577-1.22a2.016 2.016 0 0 1-.673-.38m0 0A2.18 2.18 0 0 1 3 12.489V8.706c0-1.081.768-2.015 1.837-2.175a48.111 48.111 0 0 1 3.413-.387m7.5 0V5.25A2.25 2.25 0 0 0 13.5 3h-3a2.25 2.25 0 0 0-2.25 2.25v.894m7.5 0a48.667 48.667 0 0 0-7.5 0" /></svg>
                  Offerings Catalog
                </button>
                <button
                  onClick={onOpenKnowledge}
                  className={`flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${showingKnowledge ? "bg-brand-teal/10 text-brand-teal ring-1 ring-brand-teal/20" : "text-brand-gray hover:bg-brand-light-gray-2 hover:text-brand-dark-gray"}`}
                >
                  <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25" /></svg>
                  Knowledge Sources
                </button>
                <button
                  onClick={onOpenAdmin}
                  className={`flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${showingAdmin ? "bg-brand-teal/10 text-brand-teal ring-1 ring-brand-teal/20" : "text-brand-gray hover:bg-brand-light-gray-2 hover:text-brand-dark-gray"}`}
                >
                  <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" /><path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" /></svg>
                  Administration
                </button>
              </div>

              <div className="mx-4 mb-2 border-t border-brand-light-gray-1" />

              <DndContext sensors={sensors} onDragStart={(e) => setDraggedId(e.active.id as string)} onDragEnd={handleDragEnd}>
                <nav className="flex-1 overflow-y-auto overflow-x-clip px-2 pb-4">
                  {/* Groups first */}
                  {grouped.byGroup.length > 0 && (
                    <div className="mb-2 px-3 pt-2 text-[10px] font-bold uppercase tracking-wider text-brand-mid-gray">
                      Groups
                    </div>
                  )}
                  {grouped.byGroup.map(({ group, sessions: groupSessions }) => (
                    <DroppableGroup
                      key={group.id}
                      group={group}
                      isExpanded={expandedGroups.has(group.id)}
                      onToggle={() => toggleGroup(group.id)}
                      onDelete={() => handleDeleteGroup(group)}
                      sessionCount={groupSessions.length}
                    >
                      {groupSessions.map((session) => (
                        <DraggableSession
                          key={session.id}
                          session={session}
                          isActive={session.id === activeSessionId}
                          onClick={() => onSelectSession(session.id)}
                          groups={groups}
                          onMoveToGroup={handleMoveToGroup}
                          onRename={handleRenameSession}
                          onDelete={handleDeleteSessionFromSidebar}
                        />
                      ))}
                    </DroppableGroup>
                  ))}

                  {/* Ungrouped sessions below folders */}
                  {grouped.ungrouped.length > 0 && (
                    <>
                      {(grouped.byGroup.length > 0 || creatingGroup) && (
                        <div className="mx-3 my-4 border-t border-brand-light-gray-1" />
                      )}
                      <div className="mb-2 px-3 text-[10px] font-bold uppercase tracking-wider text-brand-mid-gray">
                        Sessions
                      </div>
                      <DroppableUngrouped>
                        {grouped.ungrouped.map((session) => (
                          <DraggableSession
                            key={session.id}
                            session={session}
                            isActive={session.id === activeSessionId}
                            onClick={() => onSelectSession(session.id)}
                            groups={groups}
                            onMoveToGroup={handleMoveToGroup}
                            onRename={handleRenameSession}
                            onDelete={handleDeleteSessionFromSidebar}
                          />
                        ))}
                      </DroppableUngrouped>
                    </>
                  )}

                  {/* Create group */}
                  {creatingGroup ? (
                    <div className="mt-4 px-2">
                      <input
                        autoFocus
                        value={newGroupName}
                        onChange={(e) => setNewGroupName(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") handleCreateGroup();
                          if (e.key === "Escape") { setCreatingGroup(false); setNewGroupName(""); }
                        }}
                        onBlur={() => { if (!newGroupName.trim()) setCreatingGroup(false); }}
                        placeholder="Group name..."
                        className="w-full rounded border border-brand-teal-light bg-surface px-2 py-1 text-xs ring-1 ring-brand-teal-light/30"
                      />
                    </div>
                  ) : (
                    <button onClick={() => setCreatingGroup(true)} className="mt-4 flex w-full items-center gap-1.5 px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider text-brand-mid-gray transition-colors hover:text-brand-teal">
                      <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2.5}><path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" /></svg>
                      New Group
                    </button>
                  )}

                  {sessions.length === 0 && (
                    <p className="px-3 pt-4 text-center text-xs text-brand-mid-gray">No sessions yet</p>
                  )}
                </nav>

                {/* Drag overlay */}
                <DragOverlay>
                  {draggedSession && (
                    <div className="rounded-lg bg-surface px-3 py-2 shadow-lg ring-1 ring-brand-teal/20 opacity-90 w-56">
                      <span className="text-sm font-medium text-brand-teal truncate block">{draggedSession.name}</span>
                      <div className="mt-0.5">{stateBadge(draggedSession.state)}</div>
                    </div>
                  )}
                </DragOverlay>
              </DndContext>
            </>
          )}
        </aside>

        <main className="flex-1 overflow-y-auto p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
}
