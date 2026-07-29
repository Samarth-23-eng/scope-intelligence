import Link from 'next/link';
import type { ReactNode } from 'react';
import { Icon, type IconName } from '@/components/Icon';

export function PageHeading({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow: string;
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <header className="section-heading">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
      {actions ? <div className="section-heading-actions">{actions}</div> : null}
    </header>
  );
}

export function MetricTile({
  label,
  value,
  note,
  icon,
  tone = 'neutral',
}: {
  label: string;
  value: ReactNode;
  note: string;
  icon: IconName;
  tone?: 'neutral' | 'good' | 'warning' | 'danger';
}) {
  return (
    <article className={`workspace-metric ${tone}`}>
      <div className="workspace-metric-top">
        <span>{label}</span>
        <Icon name={icon} size={17} />
      </div>
      <strong>{value}</strong>
      <p>{note}</p>
    </article>
  );
}

export function Panel({
  title,
  eyebrow,
  action,
  children,
  className = '',
}: {
  title?: string;
  eyebrow?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`workspace-panel ${className}`}>
      {title || eyebrow || action ? (
        <header className="workspace-panel-header">
          <div>
            {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
            {title ? <h3>{title}</h3> : null}
          </div>
          {action}
        </header>
      ) : null}
      <div className="workspace-panel-body">{children}</div>
    </section>
  );
}

export function EmptyState({
  icon = 'archive',
  title,
  description,
  action,
}: {
  icon?: IconName;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <span><Icon name={icon} size={21} /></span>
      <strong>{title}</strong>
      <p>{description}</p>
      {action}
    </div>
  );
}

export function LoadingState({ label = 'Loading intelligence' }: { label?: string }) {
  return (
    <div className="loading-state" aria-live="polite">
      <span />
      <p>{label}</p>
    </div>
  );
}

export function ErrorState({
  title = 'This intelligence could not be loaded',
  message,
  onRetry,
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="page-state error" role="alert">
      <Icon name="error" size={20} />
      <div>
        <strong>{title}</strong>
        <p>{message}</p>
      </div>
      {onRetry ? (
        <button type="button" className="secondary-button" onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  );
}

export function SectionLink({
  href,
  icon,
  title,
  description,
}: {
  href: string;
  icon: IconName;
  title: string;
  description: string;
}) {
  return (
    <Link href={href} className="section-link">
      <span><Icon name={icon} size={19} /></span>
      <div>
        <strong>{title}</strong>
        <p>{description}</p>
      </div>
      <Icon name="arrow" size={17} />
    </Link>
  );
}

export function formatDate(value: string | null | undefined, withTime = false) {
  if (!value) return 'Not available';
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    ...(withTime ? { timeStyle: 'short' as const } : {}),
  }).format(new Date(value));
}

export function percent(value: number | null | undefined) {
  return `${Math.round((value ?? 0) * 100)}%`;
}

export function hostname(value: string) {
  try {
    return new URL(value).hostname;
  } catch {
    return value;
  }
}
