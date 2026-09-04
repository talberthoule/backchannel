import type { DesktopUpdateController } from "../types";
import AdminPanel, { type AdminTab } from "./AdminPanel";
import KnowledgeManager from "./KnowledgeManager";
import OfferingsManager from "./OfferingsManager";

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
  onAdminTabChange: (tab: AdminTab) => void;
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
  onAdminTabChange,
}: Props) {
  if (showAdmin) {
    return (
      <AdminPanel
        onBack={onCloseAdmin}
        desktopUpdate={desktopUpdate}
        activeTab={adminTab}
        onTabChange={onAdminTabChange}
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
