'use client';

import React from 'react';
import { Icon, type IconName } from '@/components/Icon';

interface Alert {
  type: string;
  competitor_id: number;
  competitor_name: string;
  title: string;
  details: string;
  severity: string;
  timestamp: string;
  metadata: Record<string, unknown>;
}

interface AlertListProps {
  alerts: Alert[];
}

export function AlertList({ alerts }: AlertListProps) {
  if (alerts.length === 0) {
    return (
      <div className="text-center py-8 text-gray-500">
        No alerts recorded yet.
      </div>
    );
  }

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'critical':
        return 'bg-red-900 text-red-300 border-red-700';
      case 'warning':
        return 'bg-yellow-900 text-yellow-300 border-yellow-700';
      case 'info':
      default:
        return 'bg-blue-900 text-blue-300 border-blue-700';
    }
  };

  const getTypeIcon = (type: string): IconName => {
    switch (type) {
      case 'new_signal':
        return 'activity';
      case 'high_severity_signal':
        return 'error';
      case 'new_prediction':
        return 'spark';
      case 'summary_updated':
        return 'document';
      default:
        return 'activity';
    }
  };

  return (
    <div className="space-y-3">
      {alerts.map((alert, index) => (
        <div
          key={index}
          className="bg-[#0d0f16] border border-[#222636] rounded-lg p-4 hover:border-[#5b8def] transition-colors"
        >
          <div className="flex items-start gap-3">
            <span className="text-[#7fa8ef]">
              <Icon name={getTypeIcon(alert.type)} size={19} />
            </span>
            <div className="flex-1">
              <div className="flex items-center justify-between mb-2">
                <h4 className="font-medium text-white">{alert.title}</h4>
                <span
                  className={`px-2 py-1 text-xs font-medium rounded border ${getSeverityColor(
                    alert.severity
                  )}`}
                >
                  {alert.severity.toUpperCase()}
                </span>
              </div>
              <p className="text-sm text-gray-300 mb-2">{alert.details}</p>
              <div className="flex items-center gap-4 text-xs text-gray-500">
                <span>{alert.competitor_name}</span>
                <span aria-hidden="true">·</span>
                <span className="font-mono">
                  {new Date(alert.timestamp).toLocaleString()}
                </span>
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
