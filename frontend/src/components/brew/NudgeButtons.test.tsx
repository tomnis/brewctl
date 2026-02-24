import { describe, it, expect, vi, beforeEach } from 'vitest';
import '@testing-library/jest-dom';
import { render, screen, waitFor } from '@testing-library/react';
import { BrewProvider } from './BrewProvider';
import { useBrewStatus } from './useBrewStatus';
import * as brewService from './brewService';
import { BrewInProgress } from './types';

// Mock Chakra UI components
vi.mock('@chakra-ui/react', () => ({
  Button: ({ children, onClick, colorScheme, ...props }: { 
    children: React.ReactNode; 
    onClick?: () => void;
    colorScheme?: string;
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
}));

// Mock the brewService module
vi.mock('./brewService', () => ({
  pauseBrew: vi.fn(),
  resumeBrew: vi.fn(),
  nudgeOpen: vi.fn(),
  nudgeClose: vi.fn(),
}));

// Mock useBrewStatus
vi.mock('./useBrewStatus', () => ({
  useBrewStatus: vi.fn(() => ({
    brewInProgress: null,
    brewError: null,
    fetchBrewInProgress: vi.fn(),
    startConnection: vi.fn(),
    stopConnection: vi.fn(),
  })),
}));

// Import the component after mocking
import NudgeButtons from './NudgeButtons';

describe('NudgeButtons', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const mockUseBrewStatus = useBrewStatus as ReturnType<typeof vi.fn>;

  const createMockHookReturn = (overrides = {}) => ({
    brewInProgress: null,
    brewError: null,
    fetchBrewInProgress: vi.fn(),
    startConnection: vi.fn(),
    stopConnection: vi.fn(),
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
      mockUseBrewStatus.mockReturnValue(
        createMockHookReturn({ brewInProgress: mockBrewInProgress })
      );

      renderWithProvider();

      await waitFor(() => {
        expect(screen.getByText('Nudge Open')).toBeInTheDocument();
        expect(screen.getByText('Nudge Close')).toBeInTheDocument();
      });
    });

    it('should NOT render nudge buttons when brewInProgress is null', async () => {
      mockUseBrewStatus.mockReturnValue(createMockHookReturn());

      renderWithProvider();

      await waitFor(() => {
        expect(screen.queryByText('Nudge Open')).not.toBeInTheDocument();
        expect(screen.queryByText('Nudge Close')).not.toBeInTheDocument();
      });
    });

    it('should NOT render nudge buttons when brew state is "paused"', async () => {
      const mockBrewInProgress = createMockBrewInProgress('paused');
      mockUseBrewStatus.mockReturnValue(
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
      mockUseBrewStatus.mockReturnValue(
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
      mockUseBrewStatus.mockReturnValue(
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
      mockUseBrewStatus.mockReturnValue(
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
      mockUseBrewStatus.mockReturnValue(
        createMockHookReturn({ 
          brewInProgress: mockBrewInProgress,
          fetchBrewInProgress 
        })
      );

      renderWithProvider();

      await waitFor(() => {
        screen.getByText('Nudge Open').click();
      });

      expect(brewService.nudgeOpen).toHaveBeenCalled();
      expect(fetchBrewInProgress).toHaveBeenCalled();
    });

    it('should call nudgeClose when Nudge Close button is clicked', async () => {
      const fetchBrewInProgress = vi.fn();
      const mockBrewInProgress = createMockBrewInProgress('brewing');
      mockUseBrewStatus.mockReturnValue(
        createMockHookReturn({ 
          brewInProgress: mockBrewInProgress,
          fetchBrewInProgress 
        })
      );

      renderWithProvider();

      await waitFor(() => {
        screen.getByText('Nudge Close').click();
      });

      expect(brewService.nudgeClose).toHaveBeenCalled();
      expect(fetchBrewInProgress).toHaveBeenCalled();
    });
  });
});
