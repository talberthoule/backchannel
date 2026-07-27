import AdminPanel, { type AdminTab } from "./AdminPanel";
import KnowledgeManager from "./KnowledgeManager";
import OfferingsManager from "./OfferingsManager";
import type { DesktopUpdateController } from "../hooks/useDesktopUpdate";

export type { AdminTab };

interface Props {
  showAdmin: boolean;
  showKnowledge: boolean;
  showOfferings: boolean;
  adminTab: AdminTab;
  adminOnboarding: boolean;
  highlightSince: string | null;
  desktopUpdate: DesktopUpdateController;
  onCloseAdmin: () => void;
  onCloseKnowledge: () => void;
  onCloseOfferings: () => void;
  onAdminOnboardingContinue: () => void;
}

export default function ManagementView({
  showAdmin,
  showKnowledge,
  showOfferings,
  adminTab,
  adminOnboarding,
  highlightSince,
  desktopUpdate,
  onCloseAdmin,
  onCloseKnowledge,
  onCloseOfferings,
  onAdminOnboardingContinue,
}: Props) {
  if (showAdmin) {
    return (
      <AdminPanel
        onBack={onCloseAdmin}
        desktopUpdate={desktopUpdate}
        initialTab={adminTab}
        highlightSince={highlightSince}
        onboarding={adminOnboarding}
        onOnboardingContinue={onAdminOnboardingContinue}
      />
    );
  }
  if (showOfferings) return <OfferingsManager onBack={onCloseOfferings} />;
  if (showKnowledge) return <KnowledgeManager onBack={onCloseKnowledge} />;
  return null;
}
