import AdminPanel, { type AdminTab } from "./AdminPanel";
import KnowledgeManager from "./KnowledgeManager";
import OfferingsManager from "./OfferingsManager";

export type { AdminTab };

interface Props {
  showAdmin: boolean;
  showKnowledge: boolean;
  showOfferings: boolean;
  adminTab: AdminTab;
  highlightSince: string | null;
  onCloseAdmin: () => void;
  onCloseKnowledge: () => void;
  onCloseOfferings: () => void;
}

export default function ManagementView({
  showAdmin,
  showKnowledge,
  showOfferings,
  adminTab,
  highlightSince,
  onCloseAdmin,
  onCloseKnowledge,
  onCloseOfferings,
}: Props) {
  if (showAdmin) {
    return (
      <AdminPanel
        onBack={onCloseAdmin}
        initialTab={adminTab}
        highlightSince={highlightSince}
      />
    );
  }
  if (showOfferings) return <OfferingsManager onBack={onCloseOfferings} />;
  if (showKnowledge) return <KnowledgeManager onBack={onCloseKnowledge} />;
  return null;
}
