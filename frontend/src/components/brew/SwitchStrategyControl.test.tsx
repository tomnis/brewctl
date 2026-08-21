import { describe, it, expect, vi, beforeEach } from 'vitest';
import '@testing-library/jest-dom';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { BrewProvider } from './BrewProvider';
import { useBrewStatus } from './useBrewStatus';
import * as brewService from './brewService';
import { BrewInProgress } from './types';

vi.mock('@chakra-ui/react', () => ({
  Button: ({ children, onClick, colorScheme: _colorScheme, loading: _loading, ...props }: {
    children: React.ReactNode;
    onClick?: () => void;
    colorScheme?: string;
    loading?: boolean;
    [key: string]: unknown;
  }) => <button onClick={onClick} {...props}>{children}</button>,
  HStack: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Box: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Text: ({ children, ...props }: { children: React.ReactNode; [key: string]: unknown }) =>
    <span {...props}>{children}</span>,
  Input: (props: Record<string, unknown>) => <input {...props} />,
}));

vi.mock('./constants', async () => {
  const actual = await vi.importActual<typeof import('./constants')>('./constants');
  return {
    ...actual,
    sseUrl: vi.fn(() => 'http://localhost:8000/sse/brew/status'),
    healthSseUrl: vi.fn(() => 'http://localhost:8000/sse/health'),
  };
});

vi.mock('./brewService', () => ({
  pauseBrew: vi.fn(),
  resumeBrew: vi.fn(),
  nudgeOpen: vi.fn(),
  nudgeClose: vi.fn(),
  switchStrategy: vi.fn(),
}));

vi.mock('./useBrewStatus', () => ({
  useBrewStatus: vi.fn(),
}));

import SwitchStrategyControl from './SwitchStrategyControl';

describe('SwitchStrategyControl', () => {
  const mockUseBrewStatus = useBrewStatus as ReturnType<typeof vi.fn>;

  const brew = (brew_state: BrewInProgress['brew_state']): BrewInProgress => ({
    brew_id: 'test-123',
    current_flow_rate: '0.05',
    current_weight: '100',
    target_weight: '1337',
    brew_state,
    brew_strategy: 'default',
    time_started: new Date().toISOString(),
    time_completed: null,
    estimated_time_remaining: '120',
    error_message: null,
    valve_position: 50,
  });

  const mockHook = (overrides = {}) => ({
    brewInProgress: null,
    brewError: null,
    fetchBrewInProgress: vi.fn(),
    startConnection: vi.fn(),
    stopConnection: vi.fn(),
    ...overrides,
  });

  const renderFor = (brewInProgress: BrewInProgress | null) => {
    mockUseBrewStatus.mockReturnValue(mockHook({ brewInProgress }));
    return render(<BrewProvider><SwitchStrategyControl /></BrewProvider>);
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders nothing when no brew is running', async () => {
    renderFor(null);
    await waitFor(() => {
      expect(screen.queryByText('Switch Strategy')).not.toBeInTheDocument();
    });
  });

  it('renders nothing for a completed brew', async () => {
    renderFor(brew('completed'));
    await waitFor(() => {
      expect(screen.queryByText('Switch Strategy')).not.toBeInTheDocument();
    });
  });

  it('offers the switch while brewing', async () => {
    renderFor(brew('brewing'));
    await waitFor(() => {
      expect(screen.getByText('Switch Strategy')).toBeInTheDocument();
    });
  });

  it('offers the switch while paused', async () => {
    renderFor(brew('paused'));
    await waitFor(() => {
      expect(screen.getByText('Switch Strategy')).toBeInTheDocument();
    });
  });

  it('posts the selected strategy', async () => {
    renderFor(brew('brewing'));
    fireEvent.click(await screen.findByText('Switch Strategy'));
    fireEvent.change(screen.getByLabelText('switch strategy'), { target: { value: 'pid' } });
    fireEvent.click(screen.getByText('Apply'));

    await waitFor(() => {
      expect(brewService.switchStrategy).toHaveBeenCalledWith('pid', expect.any(Object));
    });
  });

  it('surfaces a rejected switch instead of failing silently', async () => {
    (brewService.switchStrategy as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error('Strategy switched too recently, please wait')
    );
    renderFor(brew('brewing'));
    fireEvent.click(await screen.findByText('Switch Strategy'));
    fireEvent.click(screen.getByText('Apply'));

    await waitFor(() => {
      expect(screen.getByText('Strategy switched too recently, please wait')).toBeInTheDocument();
    });
  });
});
