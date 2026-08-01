'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useState, type ReactNode } from 'react';
import { Icon, type IconName } from '@/components/Icon';

const navigation: Array<{ label: string; href: string; icon: IconName }> = [
  { label: 'Portfolio', href: '/', icon: 'grid' },
  { label: 'Companies', href: '/#watchlist', icon: 'building' },
  { label: 'Start investigation', href: '/#discovery', icon: 'search' },
  { label: 'Settings', href: '/settings', icon: 'settings' },
];

const sectionNames: Record<string, string> = {
  intelligence: 'Intelligence',
  research: 'Research',
  evidence: 'Evidence',
  relationships: 'Relationships',
  collection: 'Collection Studio',
  reports: 'Reports',
  operations: 'Operations',
  settings: 'Settings',
  models: 'AI & agents',
  integrations: 'Integrations',
};

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  const isCompany = pathname.startsWith('/competitors/');
  const isSettings = pathname.startsWith('/settings');
  const section =
    Object.entries(sectionNames).find(([segment]) => pathname.endsWith(`/${segment}`))?.[1] ??
    (isCompany ? 'Briefing' : isSettings ? 'Settings' : 'Portfolio');

  return (
    <div className="app-shell">
      <aside className={mobileOpen ? 'app-sidebar mobile-open' : 'app-sidebar'}>
        <div className="sidebar-top">
          <Link
            href="/"
            className="brand-lockup"
            aria-label="Scope Intelligence home"
            title="Scope Intelligence"
            onClick={() => setMobileOpen(false)}
          >
            <span className="brand-glyph" aria-hidden="true"><span /></span>
            <span className="brand-wordmark">
              <strong>SCOPE</strong>
              <small>Intelligence</small>
            </span>
          </Link>
          <button type="button" className="mobile-close" onClick={() => setMobileOpen(false)} aria-label="Close navigation">
            <Icon name="close" size={18} />
          </button>
        </div>

        <nav className="sidebar-nav" aria-label="Primary navigation">
          {navigation.map((item) => {
            const active =
              (item.href === '/' && pathname === '/') ||
              (item.href === '/settings' && isSettings);
            return (
              <Link
                key={item.label}
                href={item.href}
                className={active ? 'nav-item active' : 'nav-item'}
                title={item.label}
                aria-label={item.label}
                onClick={() => setMobileOpen(false)}
              >
                <Icon name={item.icon} size={19} />
                <span>{item.label}</span>
              </Link>
            );
          })}
          {isCompany ? (
            <div className="nav-item active" title={`Company ${section}`} aria-label={`Company ${section}`}>
              <Icon name="briefcase" size={19} />
              <span>Company dossier</span>
            </div>
          ) : null}
        </nav>

        <div className="sidebar-lower">
          <div className="environment-indicator" title="Private workspace · Services connected">
            <span className="status-pulse" />
            <span>Services connected</span>
          </div>
          <div className="operator-avatar" title="Research operator">OP</div>
        </div>
      </aside>

      {mobileOpen ? <button type="button" className="sidebar-backdrop" onClick={() => setMobileOpen(false)} aria-label="Close navigation" /> : null}

      <section className="app-workspace">
        <header className="workspace-bar">
          <div className="workspace-bar-copy">
            <button type="button" className="mobile-menu" onClick={() => setMobileOpen(true)} aria-label="Open navigation">
              <Icon name="menu" size={19} />
            </button>
            <div className="workspace-breadcrumb">
              <span>{isCompany ? 'Company dossier' : isSettings ? 'Workspace settings' : 'Intelligence portfolio'}</span>
              <Icon name="arrow" size={12} />
              <strong>{section}</strong>
            </div>
          </div>
          <div className="workspace-status">
            <span className="status-pulse" />
            Private environment
          </div>
        </header>
        <div className="workspace-content">{children}</div>
      </section>
    </div>
  );
}
