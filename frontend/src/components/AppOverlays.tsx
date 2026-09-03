import { useEffect } from "react";
import type { WhatsNew } from "../hooks/useWhatsNew";
import type { DesktopUpdateController, MeetingType } from "../types";
import type { ModelDownloadsController } from "../hooks/useModelDownloads";
import { DesktopUpdateBanner } from "./DesktopUpdate";
import { ModelDownloadsBanner } from "./ModelDownloads";
import NewSessionModal from "./NewSessionModal";

interface Props {
  update: DesktopUpdateController;
  newSessionOpen: boolean;
  onCloseNewSession: () => void;
  onCreateSession: (name: string, meetingType: MeetingType) => Promise<void>;
  suppressDesktopUpdate: boolean;
  whatsNew: WhatsNew | null;
  onOpenUpdate: () => void;
  onAcknowledgeUpdate: () => void;
  downloads: ModelDownloadsController;
  onOpenPrivacy: () => void;
}

export default function AppOverlays({
  update,
  newSessionOpen,
  onCloseNewSession,
  onCreateSession,
  suppressDesktopUpdate,
  whatsNew,
  onOpenUpdate,
  onAcknowledgeUpdate,
  downloads,
  onOpenPrivacy,
}: Props) {
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("view") !== "about") return;
    onOpenUpdate();
    params.delete("view");
    const query = params.toString();
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`,
    );
  }, [onOpenUpdate]);
  const showDesktop = (
    ["available", "downloading", "ready"].includes(update.status.state)
    && !suppressDesktopUpdate
  );
  const showDownloads = downloads.active.length > 0 || downloads.failed.length > 0;
  return (
    <>
      <NewSessionModal
        open={newSessionOpen}
        onClose={onCloseNewSession}
        onCreate={onCreateSession}
      />
      {(showDesktop || whatsNew || showDownloads) && (
        <div className="fixed bottom-4 right-4 z-50 w-[min(28rem,calc(100vw-2rem))] space-y-3">
          {showDesktop && (
            <DesktopUpdateBanner status={update.status} onOpen={onOpenUpdate} />
          )}
          {showDownloads && (
            <ModelDownloadsBanner
              active={downloads.active}
              failed={downloads.failed}
              onOpenSettings={onOpenPrivacy}
              onRetry={(key) => void downloads.retry(key)}
              onDismiss={(key) => void downloads.dismiss(key)}
            />
          )}
          {whatsNew && (
            <div className="flex items-center gap-3 rounded-xl bg-surface px-4 py-3 shadow-lg ring-1 ring-brand-light-gray-1">
              <p className="min-w-0 flex-1 font-body text-sm text-brand-dark-gray">
                Backchannel was updated to <span className="font-mono font-semibold">v{whatsNew.current}</span>
              </p>
              <button
                type="button"
                onClick={() => {
                  onAcknowledgeUpdate();
                  onOpenUpdate();
                }}
                className="min-h-11 shrink-0 rounded-lg bg-brand-teal px-3 py-2 font-body text-xs font-semibold text-white transition-colors motion-reduce:transition-none hover:bg-brand-teal-dark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal-light focus-visible:ring-offset-2"
              >
                See what&apos;s new
              </button>
              <button
                type="button"
                onClick={onAcknowledgeUpdate}
                aria-label="Dismiss update notice"
                title="Dismiss"
                className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-brand-mid-gray transition-colors motion-reduce:transition-none hover:bg-brand-light-gray-2 hover:text-brand-dark-gray focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal-light"
              >
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          )}
        </div>
      )}
    </>
  );
}
