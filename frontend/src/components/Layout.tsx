import React, { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
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
import {
  BookOpen,
  Check,
  ChevronRight,
  Ellipsis,
  FolderPlus,
  GripVertical,
  Menu,
  Moon,
  Package,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  Plus,
  Search,
  Settings,
  Sun,
  Trash2,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { Session, SessionGroup } from "../types";
import * as api from "../services/api";
import { useConfirm } from "./ConfirmProvider";
import { filterSessions, normalizeQuery } from "../lib/sessionSearch";
import { SEARCH_HINT } from "./SearchHint";

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
  /** A call is on screen and running: the live view gets the width. */
  liveCallActive?: boolean;
  onDeleteSession: (id: string) => Promise<void>;
  onRefreshGroups: () => void;
  onRefreshSessions: () => void;
  children: React.ReactNode;
}

// The find box appears once the list is long enough that scanning beats
// scrolling; below this, a search field is more chrome than help.
export const SEARCH_THRESHOLD = 6;

// Only explicit toggles are remembered. The live-call auto-collapse is a
// per-call convenience and must not become next launch's default.
const SIDEBAR_STORAGE_KEY = "bc-sidebar-collapsed";

function readStoredCollapsed(): boolean {
  try {
    return typeof localStorage !== "undefined" && localStorage.getItem(SIDEBAR_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function storeCollapsed(collapsed: boolean) {
  try {
    localStorage.setItem(SIDEBAR_STORAGE_KEY, collapsed ? "1" : "0");
  } catch {
    /* storage unavailable (private mode); the choice just does not persist */
  }
}

const THEME_STORAGE_KEY = "bc-theme";

function readStoredTheme(): "light" | "dark" | null {
  try {
    const saved = typeof localStorage !== "undefined" ? localStorage.getItem(THEME_STORAGE_KEY) : null;
    return saved === "light" || saved === "dark" ? saved : null;
  } catch {
    return null;
  }
}

function storeTheme(theme: "light" | "dark") {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    /* see storeCollapsed */
  }
}

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() =>
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
      : false,
  );
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(mq.matches);
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  return reduced;
}

// Everything a keyboard can land on inside the drawer, for the focus trap.
const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
const SIDEBAR_ID = "bc-sidebar";

// ── Pure helpers (exported for tests) ──────────────────────────────────

// Re-exported so existing importers and tests keep their path; the
// implementations live in lib/sessionSearch.ts, which the post-call chat
// scope picker also uses.
export {
  normalizeQuery,
  dateSearchTerms,
  sessionSearchTerms,
  filterSessions,
} from "../lib/sessionSearch";

/** Live sessions first; otherwise the server's order (newest first) is kept. */
export function orderSessions(list: Session[]): Session[] {
  return [...list].sort((a, b) => {
    if (a.state === "active" && b.state !== "active") return -1;
    if (a.state !== "active" && b.state === "active") return 1;
    return 0;
  });
}

export function sessionStateLabel(state: Session["state"]): string {
  switch (state) {
    case "pre_call":
      return "Not started";
    case "active":
      return "Live";
    case "completed":
      return "Completed";
  }
}

// ── Small presentational pieces ────────────────────────────────────────

// State is carried by shape as well as color: hollow ring = not started,
// pulsing green = live, solid muted = completed.
function StateDot({ state }: { state: Session["state"] }) {
  if (state === "active") {
    return (
      <span className="relative flex h-2 w-2" aria-hidden="true">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-400 opacity-75 motion-reduce:animate-none" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-green-500" />
      </span>
    );
  }
  if (state === "pre_call") {
    return <span aria-hidden="true" className="inline-block h-2 w-2 rounded-full border-[1.5px] border-brand-teal" />;
  }
  return <span aria-hidden="true" className="inline-block h-2 w-2 rounded-full bg-brand-light-gray-1" />;
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <span className="text-[11px] font-semibold uppercase tracking-wider text-brand-mid-gray">{children}</span>;
}

function ToolLink({ icon: Icon, label, active, onClick, compact }: {
  icon: LucideIcon;
  label: string;
  active?: boolean;
  onClick: () => void;
  compact?: boolean;
}) {
  if (compact) {
    return (
      <button
        type="button"
        onClick={onClick}
        aria-label={label}
        aria-current={active ? "page" : undefined}
        title={label}
        className={`flex h-11 w-11 items-center justify-center rounded-lg transition-colors ${
          active ? "bg-brand-teal/10 text-brand-teal" : "text-brand-gray hover:bg-brand-light-gray-2 hover:text-brand-dark-gray"
        }`}
      >
        <Icon className="h-[18px] w-[18px]" aria-hidden="true" />
      </button>
    );
  }
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      className={`bc-row flex h-8 w-full items-center gap-2.5 rounded-md px-2 text-left text-[13px] transition-colors ${
        active ? "bc-accent-text bg-brand-teal/10 font-semibold" : "font-medium text-brand-gray hover:bg-brand-light-gray-2 hover:text-brand-dark-gray"
      }`}
    >
      <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
      <span className="truncate">{label}</span>
    </button>
  );
}

// ── Session row menu (portaled so the sidebar can clip its own overflow) ─

const MENU_WIDTH = 192;
const MENU_ROW = 30;

/** Whether a scroll should close the row menu: any scroll except one inside
 *  the menu itself, so a Move to list taller than the viewport can still be
 *  wheel-scrolled to its lower groups. Duck-typed on nodeType so it runs
 *  outside a DOM. */
export function scrollClosesMenu(menu: { contains(node: Node): boolean } | null, target: EventTarget | null): boolean {
  if (!menu || !target) return true;
  const node = target as Node;
  if (typeof node.nodeType !== "number") return true;
  return !menu.contains(node);
}

function SessionMenu({ id, anchor, session, groups, onClose, onRename, onMove, onDelete }: {
  id: string;
  anchor: HTMLElement;
  session: Session;
  groups: SessionGroup[];
  onClose: () => void;
  onRename: () => void;
  onMove: (groupId: string | null) => void;
  onDelete: () => void;
}) {
  const menuRef = useRef<HTMLDivElement>(null);
  // The parent re-renders on every WebSocket message during a live call and
  // hands down a fresh onClose each time; the listeners read it through a ref
  // so they are wired once and never re-run (which would also re-focus).
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });

  const position = useMemo(() => {
    const rect = anchor.getBoundingClientRect();
    const estimated = (3 + groups.length) * MENU_ROW + 40;
    const height = Math.min(estimated, window.innerHeight - 16);
    const below = window.innerHeight - rect.bottom > height + 8;
    const top = below ? rect.bottom + 4 : Math.max(8, rect.top - height - 4);
    const left = Math.max(8, Math.min(rect.right - MENU_WIDTH, window.innerWidth - MENU_WIDTH - 8));
    return { top, left };
  }, [anchor, groups.length]);

  // Focus the first item once, on open.
  useEffect(() => {
    menuRef.current?.querySelector<HTMLElement>("[role^=menuitem]")?.focus();
  }, []);

  useEffect(() => {
    const close = () => onCloseRef.current();
    const onPointer = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node) && !anchor.contains(event.target as Node)) {
        close();
      }
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        // Capture phase, so the mobile drawer's own Escape handler does not
        // also fire: one Escape closes the menu, the next closes the drawer.
        event.stopPropagation();
        close();
        anchor.focus();
        return;
      }
      if (event.key === "Tab") {
        // Menu button pattern: Tab leaves the menu and continues from its
        // button, in whichever direction was pressed.
        close();
        anchor.focus();
        return;
      }
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        const items = Array.from(menuRef.current?.querySelectorAll<HTMLElement>("[role^=menuitem]") ?? []);
        if (items.length === 0) return;
        event.preventDefault();
        const index = items.indexOf(document.activeElement as HTMLElement);
        const step = event.key === "ArrowDown" ? 1 : -1;
        items[(index + step + items.length) % items.length].focus();
      }
    };
    // A fixed menu cannot follow its row; scrolling elsewhere or resizing
    // closes it. Scrolling the menu's own list must not.
    const onScroll = (event: Event) => {
      if (scrollClosesMenu(menuRef.current, event.target)) close();
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey, true);
      document.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", close);
    };
  }, [anchor]);

  // Activating an item closes the menu and hands focus back to its button, so
  // a keyboard user is not dropped on <body>.
  const activate = (action: () => void) => {
    onClose();
    anchor.focus();
    action();
  };

  const itemClass = "flex w-full items-center gap-2 px-3 py-1.5 text-left text-[13px] text-brand-dark-gray transition-colors hover:bg-brand-light-gray-2 focus-visible:bg-brand-light-gray-2";

  return createPortal(
    <div
      ref={menuRef}
      id={id}
      role="menu"
      aria-label={`Actions for ${session.name}`}
      className="bc-scroll fixed z-50 max-h-[calc(100vh-16px)] overflow-y-auto rounded-lg border border-brand-light-gray-1 bg-surface py-1 shadow-lg"
      style={{ top: position.top, left: position.left, width: MENU_WIDTH }}
    >
      <button type="button" role="menuitem" className={itemClass} onClick={() => activate(onRename)}>
        <Pencil className="h-3.5 w-3.5 text-brand-mid-gray" aria-hidden="true" />
        Rename
      </button>
      <div className="my-1 border-t border-brand-light-gray-1" />
      <div role="group" aria-labelledby={`${id}-move`}>
        <p id={`${id}-move`} className="px-3 pb-1 pt-1 text-[11px] font-semibold uppercase tracking-wider text-brand-mid-gray">Move to</p>
        <button
          type="button"
          role="menuitemradio"
          aria-checked={!session.group_id}
          className={itemClass}
          onClick={() => activate(() => onMove(null))}
        >
          <span className="flex h-3.5 w-3.5 items-center justify-center">
            {!session.group_id && <Check className="h-3.5 w-3.5 text-brand-teal" aria-hidden="true" />}
          </span>
          No group
        </button>
        {groups.map((group) => (
          <button
            key={group.id}
            type="button"
            role="menuitemradio"
            aria-checked={session.group_id === group.id}
            className={itemClass}
            onClick={() => activate(() => onMove(group.id))}
          >
            <span className="flex h-3.5 w-3.5 shrink-0 items-center justify-center">
              {session.group_id === group.id && <Check className="h-3.5 w-3.5 text-brand-teal" aria-hidden="true" />}
            </span>
            <span className="truncate">{group.name}</span>
          </button>
        ))}
      </div>
      <div className="my-1 border-t border-brand-light-gray-1" />
      <button
        type="button"
        role="menuitem"
        className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[13px] text-red-600 transition-colors hover:bg-red-500/10 focus-visible:bg-red-500/10 dark:text-red-400"
        onClick={() => activate(onDelete)}
      >
        <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
        Delete
      </button>
    </div>,
    document.body,
  );
}

// ── Draggable session row ──────────────────────────────────────────────

function SessionRow({ session, isActive, onClick, groups, onMoveToGroup, onRename, onDelete }: {
  session: Session;
  isActive: boolean;
  onClick: () => void;
  groups: SessionGroup[];
  onMoveToGroup: (sessionId: string, groupId: string | null) => void;
  onRename: (sessionId: string, name: string) => Promise<void>;
  onDelete: (sessionId: string) => Promise<void>;
}) {
  const { listeners, setNodeRef, setActivatorNodeRef, isDragging } = useDraggable({ id: session.id });
  const [menuOpen, setMenuOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(session.name);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const menuId = `bc-session-menu-${session.id}`;
  const { confirm } = useConfirm();

  const startRename = () => {
    setDraft(session.name);
    setEditing(true);
  };

  const commitRename = async () => {
    setEditing(false);
    const trimmed = draft.trim();
    if (trimmed && trimmed !== session.name) await onRename(session.id, trimmed);
    else setDraft(session.name);
  };

  const handleDelete = async () => {
    const ok = await confirm({
      title: "Delete session",
      message: "Delete this session and all its data? This cannot be undone.",
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (ok) await onDelete(session.id);
  };

  return (
    <div
      ref={setNodeRef}
      className={`group relative flex items-center rounded-md transition-colors ${isDragging ? "opacity-30" : ""} ${
        isActive ? "bg-brand-teal/10" : "hover:bg-brand-light-gray-2"
      }`}
    >
      {editing ? (
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={() => void commitRename()}
          onKeyDown={(event) => {
            if (event.key === "Enter") (event.target as HTMLInputElement).blur();
            if (event.key === "Escape") { setDraft(session.name); setEditing(false); }
          }}
          aria-label="Session name"
          className="my-1 ml-2 h-6 w-full min-w-0 rounded border border-brand-teal bg-surface px-1.5 text-sm text-brand-dark-gray"
          autoFocus
        />
      ) : (
        <button
          type="button"
          onClick={onClick}
          onDoubleClick={startRename}
          aria-current={isActive ? "page" : undefined}
          title={session.name}
          className={`bc-row flex h-8 min-w-0 flex-1 items-center gap-2 rounded-md pl-2 pr-1 text-left text-sm ${
            isActive ? "bc-accent-text font-semibold" : "font-medium text-brand-dark-gray"
          }`}
        >
          <span className="flex h-4 w-4 shrink-0 items-center justify-center">
            <StateDot state={session.state} />
          </span>
          <span className="truncate">{session.name}</span>
          <span className="sr-only">, {sessionStateLabel(session.state)}</span>
        </button>
      )}

      {/* Row actions: reserved width so the name never reflows on hover. */}
      <div className="bc-reveal flex shrink-0 items-center pr-1">
        <span
          ref={setActivatorNodeRef}
          {...listeners}
          aria-hidden="true"
          title="Drag to another group"
          className="bc-grip flex h-7 w-5 cursor-grab items-center justify-center rounded text-brand-mid-gray hover:text-brand-dark-gray active:cursor-grabbing"
        >
          <GripVertical className="h-3.5 w-3.5" />
        </span>
        <button
          ref={menuButtonRef}
          type="button"
          onClick={() => setMenuOpen((open) => !open)}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          aria-controls={menuOpen ? menuId : undefined}
          aria-label={`Actions for ${session.name}`}
          title="More actions"
          className="bc-action flex h-7 w-7 items-center justify-center rounded text-brand-mid-gray transition-colors hover:bg-brand-light-gray-1/60 hover:text-brand-dark-gray"
        >
          <Ellipsis className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>

      {menuOpen && menuButtonRef.current && (
        <SessionMenu
          id={menuId}
          anchor={menuButtonRef.current}
          session={session}
          groups={groups}
          onClose={() => setMenuOpen(false)}
          onRename={startRename}
          onMove={(groupId) => onMoveToGroup(session.id, groupId)}
          onDelete={() => void handleDelete()}
        />
      )}
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
  const sessionsId = `bc-group-${group.id}-sessions`;

  return (
    <div ref={setNodeRef} className={`rounded-md transition-colors ${isOver ? "bg-brand-teal/5 ring-1 ring-brand-teal/20" : ""}`}>
      <div className="group flex items-center rounded-md transition-colors hover:bg-brand-light-gray-2">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={isExpanded}
          aria-controls={sessionsId}
          className="bc-row flex h-8 min-w-0 flex-1 items-center gap-1.5 rounded-md pl-1 pr-1 text-left"
        >
          <ChevronRight
            className={`h-3.5 w-3.5 shrink-0 text-brand-mid-gray transition-transform duration-150 motion-reduce:transition-none ${isExpanded ? "rotate-90" : ""}`}
            aria-hidden="true"
          />
          <span className="truncate text-sm font-semibold text-brand-dark-gray" title={group.name}>{group.name}</span>
          <span className="ml-auto shrink-0 pl-2 text-xs tabular-nums text-brand-mid-gray" aria-label={`${sessionCount} sessions`}>
            {sessionCount}
          </span>
        </button>
        <button
          type="button"
          onClick={onDelete}
          aria-label={`Delete ${group.name} group`}
          title="Delete group"
          className="bc-reveal bc-action mr-1 flex h-7 w-7 shrink-0 items-center justify-center rounded text-brand-mid-gray transition-colors hover:bg-red-500/10 hover:text-red-600 dark:hover:text-red-400"
        >
          <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      </div>
      {/* Always in the DOM so aria-controls resolves; hidden when collapsed. */}
      <div id={sessionsId} hidden={!isExpanded} className="ml-[11px] border-l border-brand-light-gray-1/70 pl-1.5">
        {isExpanded && children}
        {isExpanded && sessionCount === 0 && (
          <p className="py-1.5 pl-2 text-xs text-brand-mid-gray">{isOver ? "Drop here" : "No sessions"}</p>
        )}
      </div>
    </div>
  );
}

// Droppable zone for "ungrouped"
function DroppableUngrouped({ children }: { children: React.ReactNode }) {
  const { setNodeRef, isOver } = useDroppable({ id: "group-ungrouped" });
  return (
    <div ref={setNodeRef} className={`rounded-md transition-colors ${isOver ? "bg-brand-teal/5 ring-1 ring-brand-teal/20" : ""}`}>
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
  liveCallActive = false,
  onDeleteSession,
  onRefreshGroups,
  onRefreshSessions,
  children,
}: LayoutProps) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(readStoredCollapsed);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [isDesktop, setIsDesktop] = useState(true);
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(() => new Set(groups.map((g) => g.id)));
  const [creatingGroup, setCreatingGroup] = useState(false);
  const [newGroupName, setNewGroupName] = useState("");
  const [query, setQuery] = useState("");
  const [queryFocused, setQueryFocused] = useState(false);
  const [draggedId, setDraggedId] = useState<string | null>(null);
  const { confirm, toast } = useConfirm();
  const reducedMotion = usePrefersReducedMotion();
  const asideRef = useRef<HTMLElement>(null);
  const hamburgerRef = useRef<HTMLButtonElement>(null);

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

  // The drawer is a modal dialog: focus moves in when it opens, Tab stays
  // inside, Escape closes it, and focus returns to the menu button on every
  // close path (Escape, backdrop, navigation).
  const drawerOpen = mobileOpen && !isDesktop;
  const drawerWasOpen = useRef(false);
  useEffect(() => {
    if (drawerOpen) {
      drawerWasOpen.current = true;
      asideRef.current?.querySelector<HTMLElement>(FOCUSABLE)?.focus();
      const onKey = (event: KeyboardEvent) => {
        if (event.key === "Escape") {
          setMobileOpen(false);
          return;
        }
        if (event.key !== "Tab" || !asideRef.current) return;
        const focusables = Array.from(asideRef.current.querySelectorAll<HTMLElement>(FOCUSABLE))
          .filter((el) => el.offsetParent !== null);
        if (focusables.length === 0) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        const current = document.activeElement as HTMLElement | null;
        const inside = current ? asideRef.current.contains(current) : false;
        if (event.shiftKey && (!inside || current === first)) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && (!inside || current === last)) {
          event.preventDefault();
          first.focus();
        }
      };
      document.addEventListener("keydown", onKey);
      return () => document.removeEventListener("keydown", onKey);
    }
    if (drawerWasOpen.current) {
      drawerWasOpen.current = false;
      hamburgerRef.current?.focus();
    }
  }, [drawerOpen]);

  // Opening a live call collapses the rail: the call view is the dense screen
  // and the session list is not what you are reading during a meeting. Only on
  // the transition in, so expanding it mid-call sticks.
  useEffect(() => {
    if (liveCallActive) setSidebarCollapsed(true);
  }, [liveCallActive]);

  const collapsed = isDesktop ? sidebarCollapsed : false;

  const setCollapsedExplicitly = (next: boolean) => {
    setSidebarCollapsed(next);
    storeCollapsed(next);
  };

  // Theme: explicit user choice wins over OS preference; persisted in storage.
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    const saved = readStoredTheme();
    if (saved) return saved;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    storeTheme(theme);
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

  const showSearch = sessions.length >= SEARCH_THRESHOLD;
  // A query only filters while the box that can clear it is on screen.
  const filtering = showSearch && normalizeQuery(query).length > 0;

  // If the list shrinks below the threshold the box unmounts; a query left
  // behind would keep hiding rows with nothing to clear it.
  useEffect(() => {
    if (!showSearch) setQuery("");
  }, [showSearch]);

  const grouped = useMemo(() => {
    const visible = filtering ? filterSessions(sessions, groups, query) : sessions;
    const ungrouped = orderSessions(visible.filter((s) => !s.group_id));
    const byGroup = groups
      .map((g) => ({ group: g, sessions: orderSessions(visible.filter((s) => s.group_id === g.id)) }))
      // While filtering, a group with no matches is noise; when not, every group shows.
      .filter(({ sessions: list }) => !filtering || list.length > 0);
    return { ungrouped, byGroup, visibleCount: visible.length };
  }, [sessions, groups, query, filtering]);

  const toggleGroup = (id: string) => {
    // Groups are held open while filtering; flipping the stored state then
    // would only show up as a surprise collapse after the search is cleared.
    if (filtering) return;
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
  const hasGroups = groups.length > 0;
  // While filtering, the heading only earns its place above a visible group.
  const showGroupsHeading = creatingGroup || (hasGroups && (!filtering || grouped.byGroup.length > 0));

  const renderSession = (session: Session) => (
    <SessionRow
      key={session.id}
      session={session}
      isActive={session.id === activeSessionId}
      onClick={() => onSelectSession(session.id)}
      groups={groups}
      onMoveToGroup={handleMoveToGroup}
      onRename={handleRenameSession}
      onDelete={handleDeleteSessionFromSidebar}
    />
  );

  const newGroupInput = (
    <div className="px-1 py-1">
      <input
        autoFocus
        value={newGroupName}
        onChange={(e) => setNewGroupName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") void handleCreateGroup();
          if (e.key === "Escape") { setCreatingGroup(false); setNewGroupName(""); }
        }}
        onBlur={() => { if (!newGroupName.trim()) setCreatingGroup(false); }}
        placeholder="Group name"
        aria-label="New group name"
        className="h-8 w-full rounded-md border border-brand-teal bg-surface px-2 text-sm text-brand-dark-gray placeholder:text-brand-mid-gray"
      />
    </div>
  );

  return (
    <div className="flex h-screen flex-col bg-canvas font-body">
      <header className="flex items-center justify-between border-b border-brand-light-gray-1 bg-surface px-4 py-3 shadow-sm md:px-6">
        <div className="flex items-center gap-2.5">
          <button
            ref={hamburgerRef}
            type="button"
            onClick={() => setMobileOpen(true)}
            className="flex h-9 w-9 items-center justify-center rounded-lg text-brand-gray transition-colors hover:bg-brand-light-gray-2 hover:text-brand-teal md:hidden"
            aria-label="Open menu"
            aria-expanded={mobileOpen}
            aria-controls={SIDEBAR_ID}
          >
            <Menu className="h-5 w-5" aria-hidden="true" />
          </button>
          {/* Brand mark: matches site/assets/favicon.svg on the landing page */}
          <svg className="h-7 w-7" viewBox="0 0 64 64" fill="none" aria-hidden="true">
            <rect width="64" height="64" rx="14" style={{ fill: "rgb(var(--brand-mark-bg))" }} />
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
            <Sun className="h-5 w-5" aria-hidden="true" />
          ) : (
            <Moon className="h-5 w-5" aria-hidden="true" />
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
          ref={asideRef}
          id={SIDEBAR_ID}
          role={drawerOpen ? "dialog" : undefined}
          aria-modal={drawerOpen ? true : undefined}
          className={`fixed inset-y-0 left-0 z-40 flex w-72 flex-col overflow-hidden border-r border-brand-light-gray-1 bg-surface transition-transform duration-200 ease-out motion-reduce:transition-none md:static md:z-auto md:transform-none md:transition-[width] ${
            mobileOpen ? "translate-x-0" : "-translate-x-full"
          } ${collapsed ? "md:w-16" : "md:w-72"}`}
          aria-label="Sidebar"
        >
          {collapsed ? (
            <div key="rail" className="bc-fade-in flex h-full w-full flex-col items-center">
              <div className="flex flex-col items-center gap-1 p-2">
                <button
                  type="button"
                  onClick={() => setCollapsedExplicitly(false)}
                  className="flex h-11 w-11 items-center justify-center rounded-lg text-brand-gray transition-colors hover:bg-brand-light-gray-2 hover:text-brand-dark-gray"
                  aria-label="Expand sidebar"
                  aria-expanded={false}
                  aria-controls={SIDEBAR_ID}
                  title="Expand sidebar"
                >
                  <PanelLeftOpen className="h-[18px] w-[18px]" aria-hidden="true" />
                </button>
                <button
                  type="button"
                  onClick={onNewSession}
                  className="flex h-11 w-11 items-center justify-center rounded-lg bg-brand-teal text-white shadow-sm transition-colors hover:bg-brand-teal-dark"
                  aria-label="New session"
                  title="New session"
                >
                  <Plus className="h-[18px] w-[18px]" aria-hidden="true" />
                </button>
              </div>

              {/* overflow-x-hidden: the 44px targets plus a Windows scrollbar can
                  exceed the 64px rail; clip rather than grow a second scrollbar. */}
              <nav
                className="bc-scroll flex w-full flex-1 flex-col items-center gap-1 overflow-x-hidden overflow-y-auto border-t border-brand-light-gray-1 px-1 py-2"
                aria-label="Sessions"
              >
                {orderSessions(sessions).map((session) => {
                  const isActive = session.id === activeSessionId;
                  const initial = session.name.trim().charAt(0).toUpperCase() || "S";
                  return (
                    <button
                      key={session.id}
                      type="button"
                      onClick={() => onSelectSession(session.id)}
                      className={`relative flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-xs font-semibold transition-colors ${
                        isActive ? "bg-brand-teal text-white shadow-sm" : "bg-brand-light-gray-2 text-brand-gray hover:bg-brand-teal/10 hover:text-brand-teal"
                      }`}
                      aria-label={`Open ${session.name}, ${sessionStateLabel(session.state).toLowerCase()}`}
                      aria-current={isActive ? "page" : undefined}
                      title={`${session.name} (${sessionStateLabel(session.state)})`}
                    >
                      {initial}
                      {session.state === "active" && (
                        <span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-green-400 ring-1 ring-surface" aria-hidden="true" />
                      )}
                    </button>
                  );
                })}
              </nav>

              <div className="flex w-full flex-col items-center gap-1 border-t border-brand-light-gray-1 p-2">
                <ToolLink compact icon={Package} label="Offerings Catalog" active={showingOfferings} onClick={onOpenOfferings} />
                <ToolLink compact icon={BookOpen} label="Knowledge Sources" active={showingKnowledge} onClick={onOpenKnowledge} />
                <ToolLink compact icon={Settings} label="Administration" active={showingAdmin} onClick={onOpenAdmin} />
              </div>
            </div>
          ) : (
            <div key="panel" className="bc-fade-in flex h-full w-full flex-col">
              <div className="flex items-center gap-2 p-3">
                <button
                  type="button"
                  onClick={onNewSession}
                  className="flex h-9 flex-1 items-center justify-center gap-1.5 rounded-lg bg-brand-teal px-3 font-display text-sm font-semibold text-white shadow-sm transition-colors hover:bg-brand-teal-dark"
                >
                  <Plus className="h-4 w-4" aria-hidden="true" />
                  New session
                </button>
                <button
                  type="button"
                  onClick={() => setCollapsedExplicitly(true)}
                  className="hidden h-9 w-9 shrink-0 items-center justify-center rounded-lg text-brand-gray transition-colors hover:bg-brand-light-gray-2 hover:text-brand-dark-gray md:flex"
                  aria-label="Collapse sidebar"
                  aria-expanded={true}
                  aria-controls={SIDEBAR_ID}
                  title="Collapse sidebar"
                >
                  <PanelLeftClose className="h-[18px] w-[18px]" aria-hidden="true" />
                </button>
                <button
                  type="button"
                  onClick={() => setMobileOpen(false)}
                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-brand-gray transition-colors hover:bg-brand-light-gray-2 hover:text-brand-dark-gray md:hidden"
                  aria-label="Close menu"
                >
                  <X className="h-[18px] w-[18px]" aria-hidden="true" />
                </button>
              </div>

              {showSearch && (
                <div className="px-3 pb-2">
                  <div className="relative">
                    <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-brand-mid-gray" aria-hidden="true" />
                    <input
                      type="search"
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Escape" && query) { e.stopPropagation(); setQuery(""); } }}
                      onFocus={() => setQueryFocused(true)}
                      onBlur={() => setQueryFocused(false)}
                      placeholder="Find a session"
                      aria-label="Find a session"
                      aria-describedby="sidebar-search-hint"
                      className="bc-search h-8 w-full rounded-md border border-brand-light-gray-1 bg-canvas pl-8 pr-8 text-sm text-brand-dark-gray transition-colors placeholder:text-brand-mid-gray focus:border-brand-teal"
                    />
                    {query && (
                      <button
                        type="button"
                        onClick={() => setQuery("")}
                        aria-label="Clear search"
                        className="bc-action absolute right-1 top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded text-brand-mid-gray transition-colors hover:bg-brand-light-gray-2 hover:text-brand-dark-gray"
                      >
                        <X className="h-3.5 w-3.5" aria-hidden="true" />
                      </button>
                    )}
                  </div>
                  <p
                    id="sidebar-search-hint"
                    className={`mt-1 px-0.5 font-body text-xs text-brand-mid-gray ${queryFocused ? "" : "sr-only"}`}
                  >
                    {SEARCH_HINT}
                  </p>
                </div>
              )}

              <DndContext sensors={sensors} onDragStart={(e) => setDraggedId(e.active.id as string)} onDragEnd={handleDragEnd}>
                <nav className="bc-scroll flex-1 overflow-y-auto overflow-x-clip px-2 pb-3" aria-label="Sessions">
                  {sessions.length === 0 ? (
                    <div className="px-2 pt-6 text-center">
                      <p className="text-sm font-medium text-brand-dark-gray">No sessions yet</p>
                      <p className="mt-1 text-xs text-brand-mid-gray">Start one with New session.</p>
                    </div>
                  ) : filtering && grouped.visibleCount === 0 ? (
                    <div className="px-2 pt-6 text-center">
                      <p className="text-sm text-brand-dark-gray">No sessions match &ldquo;{query.trim()}&rdquo;</p>
                      <button
                        type="button"
                        onClick={() => setQuery("")}
                        className="bc-accent-text mt-2 text-xs font-medium hover:underline"
                      >
                        Clear search
                      </button>
                    </div>
                  ) : (
                    <>
                      {showGroupsHeading && (
                        <div className="flex h-8 items-center justify-between pl-2 pr-1">
                          <SectionLabel>Groups</SectionLabel>
                          {!filtering && (
                            <button
                              type="button"
                              onClick={() => setCreatingGroup(true)}
                              aria-label="New group"
                              title="New group"
                              className="bc-action flex h-7 w-7 items-center justify-center rounded text-brand-mid-gray transition-colors hover:bg-brand-light-gray-2 hover:text-brand-dark-gray"
                            >
                              <FolderPlus className="h-3.5 w-3.5" aria-hidden="true" />
                            </button>
                          )}
                        </div>
                      )}
                      {creatingGroup && newGroupInput}
                      {grouped.byGroup.map(({ group, sessions: groupSessions }) => (
                        <DroppableGroup
                          key={group.id}
                          group={group}
                          isExpanded={filtering || expandedGroups.has(group.id)}
                          onToggle={() => toggleGroup(group.id)}
                          onDelete={() => handleDeleteGroup(group)}
                          sessionCount={groupSessions.length}
                        >
                          {groupSessions.map(renderSession)}
                        </DroppableGroup>
                      ))}

                      {grouped.ungrouped.length > 0 && (
                        <>
                          {hasGroups && (
                            <div className="mt-2 flex h-8 items-center pl-2">
                              <SectionLabel>Sessions</SectionLabel>
                            </div>
                          )}
                          <DroppableUngrouped>
                            {grouped.ungrouped.map(renderSession)}
                          </DroppableUngrouped>
                        </>
                      )}

                      {!hasGroups && !creatingGroup && !filtering && (
                        <button
                          type="button"
                          onClick={() => setCreatingGroup(true)}
                          className="bc-row mt-2 flex h-8 w-full items-center gap-2 rounded-md px-2 text-xs font-medium text-brand-mid-gray transition-colors hover:bg-brand-light-gray-2 hover:text-brand-dark-gray"
                        >
                          <FolderPlus className="h-3.5 w-3.5" aria-hidden="true" />
                          New group
                        </button>
                      )}
                    </>
                  )}
                </nav>

                {/* Drag overlay */}
                <DragOverlay dropAnimation={reducedMotion ? null : undefined}>
                  {draggedSession && (
                    <div className="flex h-8 w-56 items-center gap-2 rounded-md bg-surface pl-2 pr-3 shadow-lg ring-1 ring-brand-teal/30">
                      <span className="flex h-4 w-4 shrink-0 items-center justify-center">
                        <StateDot state={draggedSession.state} />
                      </span>
                      <span className="truncate text-sm font-medium text-brand-dark-gray">{draggedSession.name}</span>
                    </div>
                  )}
                </DragOverlay>
              </DndContext>

              <div className="border-t border-brand-light-gray-1 p-2">
                <ToolLink icon={Package} label="Offerings Catalog" active={showingOfferings} onClick={onOpenOfferings} />
                <ToolLink icon={BookOpen} label="Knowledge Sources" active={showingKnowledge} onClick={onOpenKnowledge} />
                <ToolLink icon={Settings} label="Administration" active={showingAdmin} onClick={onOpenAdmin} />
              </div>
            </div>
          )}
        </aside>

        <main className="flex-1 overflow-y-auto p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
}
