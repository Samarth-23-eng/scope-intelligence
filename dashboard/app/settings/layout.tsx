import type { ReactNode } from 'react';
import { SettingsNavigation } from '@/components/settings/SettingsNavigation';

export default function SettingsLayout({ children }: { children: ReactNode }) {
  return (
    <div className="settings-hub">
      <SettingsNavigation />
      <div className="settings-hub-content">{children}</div>
    </div>
  );
}
