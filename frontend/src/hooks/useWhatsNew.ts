import { useCallback, useEffect, useState } from "react";
import * as api from "../services/api";

const LAST_SEEN_VERSION_KEY = "backchannel.last_seen_version";

// localStorage can be unavailable (blocked storage, some embedded contexts);
// the what's-new banner is cosmetic, so fail silent in both directions.
function readLastSeen(): string | null {
  try {
    return window.localStorage.getItem(LAST_SEEN_VERSION_KEY);
  } catch {
    return null;
  }
}

function writeLastSeen(version: string) {
  try {
    window.localStorage.setItem(LAST_SEEN_VERSION_KEY, version);
  } catch {
    // ignore
  }
}

export interface WhatsNew {
  current: string;
  since: string;
}

// Detects that the app version changed since this browser last ran it.
// On the very first launch there is no marker: baseline silently and show
// nothing (WelcomeView owns first-run guidance). `whatsNew.since` stays set
// for the rest of the session after acknowledge so the About tab can keep
// badging the releases the user hasn't read yet.
export function useWhatsNew() {
  const [whatsNew, setWhatsNew] = useState<WhatsNew | null>(null);
  const [bannerOpen, setBannerOpen] = useState(false);

  useEffect(() => {
    api.getAppMeta()
      .then((meta) => {
        const last = readLastSeen();
        if (!last) {
          writeLastSeen(meta.version);
        } else if (last !== meta.version) {
          setWhatsNew({ current: meta.version, since: last });
          setBannerOpen(true);
        }
      })
      .catch(() => null);
  }, []);

  const acknowledge = useCallback(() => {
    if (whatsNew) writeLastSeen(whatsNew.current);
    setBannerOpen(false);
  }, [whatsNew]);

  return { whatsNew, bannerOpen, acknowledge };
}
