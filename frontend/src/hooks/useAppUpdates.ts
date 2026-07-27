import { useDesktopUpdate } from "./useDesktopUpdate";
import { useWhatsNew } from "./useWhatsNew";

export function useAppUpdates() {
  return { ...useWhatsNew(), desktopUpdate: useDesktopUpdate() };
}
