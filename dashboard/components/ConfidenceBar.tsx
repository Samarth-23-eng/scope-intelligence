// Confidence Bar Component

import React from 'react';

interface ConfidenceBarProps {
  confidence: number;
}

export function ConfidenceBar({ confidence }: ConfidenceBarProps) {
  const percentage = Math.round(confidence * 100);
  
  // Color based on confidence level
  let barColor = 'bg-red-500';
  if (percentage >= 70) {
    barColor = 'bg-green-500';
  } else if (percentage >= 40) {
    barColor = 'bg-yellow-500';
  }

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-gray-700 rounded overflow-hidden">
        <div
          className={`h-full ${barColor} transition-all duration-300`}
          style={{ width: `${percentage}%` }}
        />
      </div>
      <span className="text-sm text-gray-400 font-mono w-12 text-right">
        {percentage}%
      </span>
    </div>
  );
}
