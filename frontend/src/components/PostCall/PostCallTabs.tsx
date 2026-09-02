import { useRef, type KeyboardEvent as ReactKeyboardEvent } from "react";

export interface PostCallTabDef<T extends string> {
  key: T;
  label: string;
  count?: number;
}

// The tab and panel ids pair a tab with the one panel PostCallView renders.
export function tabId(key: string): string {
  return `post-call-tab-${key}`;
}

export function panelId(key: string): string {
  return `post-call-panel-${key}`;
}

interface PostCallTabsProps<T extends string> {
  tabs: PostCallTabDef<T>[];
  activeTab: T;
  onSelect: (tab: T) => void;
}

// The post-call review strip as a WAI-ARIA tablist with a roving tabindex:
// arrows move between tabs and select as they go, Home and End jump to the
// ends, and only the selected tab sits in the Tab order.
export default function PostCallTabs<T extends string>({ tabs, activeTab, onSelect }: PostCallTabsProps<T>) {
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const onKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>, index: number) => {
    const last = tabs.length - 1;
    let next: number | null = null;
    if (event.key === "ArrowRight") next = index === last ? 0 : index + 1;
    else if (event.key === "ArrowLeft") next = index === 0 ? last : index - 1;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = last;
    if (next === null) return;
    event.preventDefault();
    onSelect(tabs[next].key);
    tabRefs.current[next]?.focus();
  };

  return (
    <div role="tablist" aria-label="Post-call review" className="flex flex-wrap gap-1 rounded-lg bg-brand-light-gray-2 p-1">
      {tabs.map((tab, index) => {
        const selected = activeTab === tab.key;
        return (
          <button
            key={tab.key}
            ref={(element) => { tabRefs.current[index] = element; }}
            type="button"
            role="tab"
            id={tabId(tab.key)}
            aria-selected={selected}
            aria-controls={panelId(tab.key)}
            tabIndex={selected ? 0 : -1}
            onClick={() => onSelect(tab.key)}
            onKeyDown={(event) => onKeyDown(event, index)}
            className={`min-w-24 flex-1 rounded-md px-4 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal ${
              selected
                ? "bg-surface text-brand-teal shadow-sm"
                : "text-brand-gray hover:text-brand-dark-gray"
            }`}
          >
            {tab.label}
            {tab.count !== undefined && (
              <span className="ml-1.5 text-xs text-brand-mid-gray">({tab.count})</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
