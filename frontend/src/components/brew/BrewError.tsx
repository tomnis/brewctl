import React from 'react';
import { BrewError as BrewErrorType } from './types';

interface BrewErrorProps {
  error: BrewErrorType;
  onRetry?: () => void;
  onDismiss?: () => void;
}

export const BrewError: React.FC<BrewErrorProps> = ({ error, onRetry, onDismiss }) => {
  return (
    <div className="brew-error p-4 rounded-lg border bg-red-50 border-red-200 mb-4">
      <div className="flex items-start justify-between">
        <div className="flex items-start gap-3">
          <span className="text-2xl">❌</span>
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="font-semibold text-gray-800">{error.error}</span>
            </div>
          </div>
        </div>
        
        <div className="flex items-center gap-2">
          {onRetry && (
            <button
              onClick={onRetry}
              className="px-3 py-1 text-sm bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors"
            >
              Retry
            </button>
          )}
          {onDismiss && (
            <button
              onClick={onDismiss}
              className="px-3 py-1 text-sm bg-gray-200 text-gray-700 rounded hover:bg-gray-300 transition-colors"
            >
              Dismiss
            </button>
          )}
        </div>
      </div>
    </div>
  );
};
