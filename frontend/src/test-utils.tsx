import React, { createContext } from 'react';
import { RenderOptions, render as rtlRender } from '@testing-library/react';
import { BrewContextShape } from './components/brew/types';
import { BrewInProgress } from './components/brew/types';

// Default mock context values
export const defaultMockContext: BrewContextShape = {
  brewInProgress: null,
  brewError: null,
  isFlipped: false,
  fetchBrewInProgress: async () => {},
  stopConnection: () => {},
  toggleFlip: () => {},
  handlePause: async () => {},
  handleResume: async () => {},
  handleNudgeOpen: async () => {},
  handleNudgeClose: async () => {},
  dismissError: () => {},
};

// Create a mock context
export const MockBrewContext = createContext<BrewContextShape>(defaultMockContext);

// Helper to create mock brew in progress data
export const createMockBrewInProgress = (overrides: Partial<BrewInProgress> = {}): BrewInProgress => ({
  brew_id: 'test-brew-123',
  current_flow_rate: '0.05',
  current_weight: '100.0',
  target_weight: '1337',
  brew_state: 'brewing',
  brew_strategy: 'default',
  time_started: new Date().toISOString(),
  time_completed: null,
  estimated_time_remaining: '120',
  error_message: null,
  valve_position: 50,
  ...overrides,
});

// Custom render that includes provider wrapper
export function render(
  ui: React.ReactElement,
  { 
    mockContext = defaultMockContext,
    ...renderOptions 
  }: {
    mockContext?: BrewContextShape;
  } & RenderOptions = {}
) {
  return rtlRender(ui, {
    wrapper: ({ children }) => (
      <MockBrewContext.Provider value={mockContext}>
        {children}
      </MockBrewContext.Provider>
    ),
    ...renderOptions,
  });
}

// Re-export testing library utilities
export * from '@testing-library/react';
