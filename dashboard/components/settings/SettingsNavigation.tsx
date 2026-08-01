'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Icon, type IconName } from '@/components/Icon';

const items: Array<{ href: string; label: string; detail: string; icon: IconName }> = [
  { href: '/settings', label: 'Overview', detail: 'Workspace health', icon: 'grid' },
  { href: '/settings/models', label: 'AI & agents', detail: 'Shared model route', icon: 'spark' },
  { href: '/settings/collection', label: 'Collection', detail: 'Crawler controls', icon: 'layers' },
  { href: '/settings/integrations', label: 'Integrations', detail: 'External services', icon: 'link' },
];

export function SettingsNavigation() {
  const pathname = usePathname();

  return (
    <nav className="settings-menu" aria-label="Settings sections">
      {items.map((item) => {
        const active = item.href === '/settings' ? pathname === item.href : pathname.startsWith(item.href);
        return (
          <Link key={item.href} href={item.href} className={active ? 'active' : ''}>
            <span className="settings-menu-icon"><Icon name={item.icon} size={17} /></span>
            <span><strong>{item.label}</strong><small>{item.detail}</small></span>
            <Icon name="arrow" size={14} />
          </Link>
        );
      })}
    </nav>
  );
}
