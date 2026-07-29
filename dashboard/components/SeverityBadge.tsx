// Severity Badge Component

import React from 'react';

interface SeverityBadgeProps {
  severity: 'low' | 'medium' | 'high' | 'critical';
}

export function SeverityBadge({ severity }: SeverityBadgeProps) {
  const colors: Record<string, string> = {
    low: 'bg-green-900 text-green-300 border-green-700',
    medium: 'bg-yellow-900 text-yellow-300 border-yellow-700',
    high: 'bg-red-900 text-red-300 border-red-700',
    critical: 'bg-red-950 text-red-200 border-red-600',
  };

  return (
    <span
      className={`px-2 py-1 text-xs font-medium rounded border ${colors[severity] || colors.low}`}
    >
      {severity.toUpperCase()}
    </span>
  );
}
