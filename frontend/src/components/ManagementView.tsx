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
  onCloseAdmin,
  onCloseKnowledge,
  onCloseOfferings,
  onAdminOnboardingContinue,
}: Props) {
  if (showAdmin) {
    return (
      <AdminPanel
        onBack={onCloseAdmin}
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
