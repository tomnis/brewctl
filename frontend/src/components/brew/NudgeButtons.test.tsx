import { describe, it, expect, vi, beforeEach } from 'vitest';
import '@testing-library/jest-dom';
import { render, screen, waitFor } from '@testing-library/react';
import { BrewProvider } from './BrewProvider';
import { useBrewPolling } from './useBrewPolling';
import * as constants from './constants';
import { BrewInProgress } from './types';

// Mock Chakra UI components
vi.mock('@chakra-ui/react', () => ({
  Button: ({ children, onClick, ...props }: { 
    children: React.ReactNode; 
    onClick?: () => void;
    [key: string]: unknown;
  }) => (
    <button onClick={onClick} {...props}>
      {children}
    </button>
  ),
  HStack: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

// Mock the constants module
vi.mock('./constants', () => ({
  wsUrl: vi.fn(() => 'ws://localhost:8000'),
  pauseBrew: vi.fn(),
  resumeBrew: vi.fn(),
  nudgeOpen: vi.fn(),
  nudgeClose: vi.fn(),
}));

// Mock useBrewPolling
vi.mock('./useBrewPolling', () => ({
  useBrewPolling: vi.fn(() => ({
    brewInProgress: null,
    brewError: null,
    fetchBrewInProgress: vi.fn(),
    startPolling: vi.fn(),
    stopPolling: vi.fn(),
  })),
}));

// Import the component after mocking
import NudgeButtons from './NudgeButtons';

describe('NudgeButtons', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const mockUseBrewPolling = useBrewPolling as ReturnType<typeof vi.fn>;

  const createMockHookReturn = (overrides = {}) => ({
    brewInProgress: null,
    brewError: null,
    fetchBrewInProgress: vi.fn(),
    startPolling: vi.fn(),
    stopPolling: vi.fn(),
    ...overrides,
  });

  const createMockBrewInProgress = (brewState: BrewInProgress['brew_state']): BrewInProgress => ({
    brew_id: 'test-123',
    current_flow_rate: '0.05',
    current_weight: '100',
    target_weight: '1337',
    brew_state: brewState,
    brew_strategy: 'default',
    time_started: new Date().toISOString(),
    time_completed: null,
    estimated_time_remaining: '120',
    error_message: null,
    valve_position: 50,
  });

  const renderWithProvider = () => {
    return render(
      <BrewProvider>
        <NudgeButtons />
      </BrewProvider>
    );
  };

  describe('rendering', () => {
    it('should render nudge buttons when brew is in progress with state "brewing"', async () => {
      const mockBrewInProgress = createMockBrewInProgress('brewing');
      mockUseBrewPolling.mockReturnValue(
        createMockHookReturn({ brewInProgress: mockBrewInProgress })
      );

      renderWithProvider();

      await waitFor(() => {
        expect(screen.getByText('Nudge Open')).toBeInTheDocument();
        expect(screen.getByText('Nudge Close')).toBeInTheDocument();
      });
    });

    it('should NOT render nudge buttons when brewInProgress is null', async () => {
      mockUseBrewPolling.mockReturnValue(createMockHookReturn());

      renderWithProvider();

      await waitFor(() => {
        expect(screen.queryByText('Nudge Open')).not.toBeInTheDocument();
        expect(screen.queryByText('Nudge Close')).not.toBeInTheDocument();
      });
    });

    it('should NOT render nudge buttons when brew state is "paused"', async () => {
      const mockBrewInProgress = createMockBrewInProgress('paused');
      mockUseBrewPolling.mockReturnValue(
        createMockHookReturn({ brewInProgress: mockBrewInProgress })
      );

      renderWithProvider();

      await waitFor(() => {
        expect(screen.queryByText('Nudge Open')).not.toBeInTheDocument();
        expect(screen.queryByText('Nudge Close')).not.toBeInTheDocument();
      });
    });

    it('should NOT render nudge buttons when brew state is "completed"', async () => {
      const mockBrewInProgress = createMockBrewInProgress('completed');
      mockUseBrewPolling.mockReturnValue(
        createMockHookReturn({ brewInProgress: mockBrewInProgress })
      );

      renderWithProvider();

      await waitFor(() => {
        expect(screen.queryByText('Nudge Open')).not.toBeInTheDocument();
        expect(screen.queryByText('Nudge Close')).not.toBeInTheDocument();
      });
    });

    it('should NOT render nudge buttons when brew state is "idle"', async () => {
      const mockBrewInProgress = createMockBrewInProgress('idle');
      mockUseBrewPolling.mockReturnValue(
        createMockHookReturn({ brewInProgress: mockBrewInProgress })
      );

      renderWithProvider();

      await waitFor(() => {
        expect(screen.queryByText('Nudge Open')).not.toBeInTheDocument();
        expect(screen.queryByText('Nudge Close')).not.toBeInTheDocument();
      });
    });

    it('should NOT render nudge buttons when brew state is "error"', async () => {
      const mockBrewInProgress = createMockBrewInProgress('error');
      mockUseBrewPolling.mockReturnValue(
        createMockHookReturn({ brewInProgress: mockBrewInProgress })
      );

      renderWithProvider();

      await waitFor(() => {
        expect(screen.queryByText('Nudge Open')).not.toBeInTheDocument();
        expect(screen.queryByText('Nudge Close')).not.toBeInTheDocument();
      });
    });
  });

  describe('button clicks', () => {
    it('should call nudgeOpen when Nudge Open button is clicked', async () => {
      const fetchBrewInProgress = vi.fn();
      const mockBrewInProgress = createMockBrewInProgress('brewing');
      mockUseBrewPolling.mockReturnValue(
        createMockHookReturn({ 
          brewInProgress: mockBrewInProgress,
          fetchBrewInProgress 
        })
      );

      renderWithProvider();

      await waitFor(() => {
        screen.getByText('Nudge Open').click();
      });

      expect(constants.nudgeOpen).toHaveBeenCalled();
      expect(fetchBrewInProgress).toHaveBeenCalled();
    });

    it('should call nudgeClose when Nudge Close button is clicked', async () => {
      const fetchBrewInProgress = vi.fn();
      const mockBrewInProgress = createMockBrewInProgress('brewing');
      mockUseBrewPolling.mockReturnValue(
        createMockHookReturn({ 
          brewInProgress: mockBrewInProgress,
          fetchBrewInProgress 
        })
      );

      renderWithProvider();

      await waitFor(() => {
        screen.getByText('Nudge Close').click();
      });

      expect(constants.nudgeClose).toHaveBeenCalled();
      expect(fetchBrewInProgress).toHaveBeenCalled();
    });
  });
});
