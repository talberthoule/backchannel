import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { DesktopUpdateController } from "../hooks/useDesktopUpdate";
import type { DesktopUpdateStatus } from "../types";

const primaryButton = "min-h-11 rounded-lg bg-brand-teal px-4 py-2 font-body text-sm font-semibold text-white transition-colors motion-reduce:transition-none hover:bg-brand-teal-dark focus:outline-none focus:ring-2 focus:ring-brand-teal-light focus:ring-offset-2 disabled:cursor-not-allowed disabled:bg-brand-light-gray-1 disabled:text-brand-mid-gray";
const secondaryButton = "min-h-11 rounded-lg border border-brand-light-gray-1 px-4 py-2 font-body text-sm font-semibold text-brand-dark-gray transition-colors motion-reduce:transition-none hover:border-brand-teal hover:text-brand-teal focus:outline-none focus:ring-2 focus:ring-brand-teal-light focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50";

function bytes(value = 0): string {
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB"];
  let amount = value / 1024;
  let unit = units[0];
  for (let index = 1; index < units.length && amount >= 1024; index += 1) {
    amount /= 1024;
    unit = units[index];
  }
  const digits = amount >= 10 || Number.isInteger(amount) ? 0 : 1;
  return `${amount.toFixed(digits)} ${unit}`;
}

function progressText(status: DesktopUpdateStatus): string {
  return `${bytes(status.downloaded)} of ${bytes(status.size)}`;
}

export function DesktopUpdateCard({ update }: { update: DesktopUpdateController }) {
  const { status } = update;
  if (!status.enabled) return null;

  const version = status.available_version || "the latest version";
  const blocked = status.blocked_reason || "";
  const error = (status.error || "The update action could not be completed.").slice(0, 240);

  return (
    <section className="rounded-xl bg-surface p-5 shadow-sm ring-1 ring-brand-light-gray-1/60" aria-labelledby="desktop-update-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="desktop-update-title" className="font-display text-sm font-bold uppercase tracking-wider text-brand-mid-gray">
            Desktop updates
          </h2>
          <p className="mt-1 font-body text-xs text-brand-mid-gray">
            Verified before installation, with automatic rollback if the new version cannot start.
          </p>
        </div>
        {status.current_version && (
          <span className="rounded-full bg-brand-light-gray-2 px-2.5 py-1 font-mono text-xs font-medium text-brand-gray">
            Current {status.current_version}
          </span>
        )}
      </div>

      <div className="mt-4" aria-live="polite">
        {status.state === "idle" && (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="font-body text-sm text-brand-gray">Backchannel is up to date.</p>
            <button type="button" onClick={() => void update.check()} className={secondaryButton}>
              Check for updates
            </button>
          </div>
        )}

        {status.state === "checking" && (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="font-body text-sm text-brand-gray">Checking for updates...</p>
            <button type="button" disabled className={secondaryButton}>
              Checking for updates
            </button>
          </div>
        )}

        {status.state === "available" && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="font-body text-sm font-semibold text-brand-dark-gray">
                {version} is available
              </p>
              <span className="font-mono text-xs text-brand-mid-gray">{bytes(status.size)}</span>
            </div>
            {status.available_notes && (
              <div className="chat-markdown rounded-lg bg-brand-light-gray-2/60 px-4 py-3 font-body text-sm text-brand-dark-gray">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{status.available_notes}</ReactMarkdown>
              </div>
            )}
            <button type="button" onClick={() => void update.authorize()} className={primaryButton}>
              Download update
            </button>
          </div>
        )}

        {status.state === "authorizing" && (
          <p className="font-body text-sm text-brand-gray">
            Complete authorization in the secure downloads window...
          </p>
        )}

        {status.state === "needs_authorization" && (
          <div className="space-y-3">
            <div>
              <p className="font-body text-sm font-semibold text-brand-dark-gray">
                Download authorization expired
              </p>
              <p className="mt-1 font-mono text-xs text-brand-mid-gray">{progressText(status)}</p>
            </div>
            <button type="button" onClick={() => void update.authorize()} className={primaryButton}>
              Resume download
            </button>
          </div>
        )}

        {status.state === "downloading" && (
          <div className="space-y-3">
            <div className="flex items-baseline justify-between gap-3">
              <p className="font-body text-sm font-semibold text-brand-dark-gray">
                Downloading {version}
              </p>
              <span className="font-mono text-xs text-brand-mid-gray">{progressText(status)}</span>
            </div>
            <progress
              className="h-2 w-full overflow-hidden rounded-full accent-brand-teal"
              value={status.downloaded || 0}
              max={status.size || 1}
            />
            <button type="button" onClick={() => void update.cancel()} className={secondaryButton}>
              Cancel
            </button>
          </div>
        )}

        {status.state === "ready" && (
          <div className="space-y-3">
            <div>
              <p className="font-body text-sm font-semibold text-brand-dark-gray">
                {version} is ready to install
              </p>
              <p className="mt-1 font-body text-xs text-brand-mid-gray">
                Backchannel will restart and reopen automatically.
              </p>
              {blocked && (
                <p className="mt-2 rounded-lg bg-brand-light-gray-2 px-3 py-2 font-body text-xs text-brand-dark-gray">
                  Finish {blocked} before installing.
                </p>
              )}
            </div>
            <button
              type="button"
              disabled={!!blocked}
              onClick={() => void update.apply()}
              className={primaryButton}
            >
              Restart and install
            </button>
          </div>
        )}

        {status.state === "applying" && (
          <p className="font-body text-sm text-brand-gray">
            Restarting to install {version}...
          </p>
        )}

        {status.state === "error" && (
          <div className="space-y-3">
            <p role="alert" className="rounded-lg bg-brand-light-gray-2 px-3 py-2 font-body text-sm text-brand-dark-gray">
              {error}
            </p>
            <button type="button" onClick={() => void update.check()} className={secondaryButton}>
              Retry
            </button>
          </div>
        )}
      </div>
    </section>
  );
}

export function DesktopUpdateBanner({
  status,
  onOpen,
}: {
  status: DesktopUpdateStatus;
  onOpen: () => void;
}) {
  if (!["available", "downloading", "ready"].includes(status.state)) return null;
  const version = status.available_version || "Update";
  const percent = status.size
    ? Math.min(100, Math.round(((status.downloaded || 0) / status.size) * 100))
    : 0;
  const message = status.state === "available"
    ? `${version} is available`
    : status.state === "ready"
      ? `${version} is ready to install`
      : `Downloading ${version} - ${percent}%`;

  return (
    <div className="flex items-center justify-between gap-3 rounded-xl bg-surface px-4 py-3 shadow-lg ring-1 ring-brand-light-gray-1">
      <p className="font-body text-sm text-brand-dark-gray">{message}</p>
      <button
        type="button"
        onClick={onOpen}
        className="min-h-11 shrink-0 rounded-lg bg-brand-teal px-3 py-2 font-body text-xs font-semibold text-white transition-colors motion-reduce:transition-none hover:bg-brand-teal-dark focus:outline-none focus:ring-2 focus:ring-brand-teal-light focus:ring-offset-2"
      >
        View update
      </button>
    </div>
  );
}
