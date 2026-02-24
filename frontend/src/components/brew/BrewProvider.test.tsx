import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { BrewProvider, useBrewContext } from './BrewProvider';
import * as constants from './constants';

// Mock the constants module
vi.mock('./constants', () => ({
  wsUrl: vi.fn(() => 'ws://localhost:8000'),
  pauseBrew: vi.fn(),
  resumeBrew: vi.fn(),
}));

// Mock useBrewStatus
vi.mock('./useBrewStatus', () => ({
  useBrewStatus: vi.fn(() => ({
    brewInProgress: null,
    fetchBrewInProgress: vi.fn(),
    startConnection: vi.fn(),
    stopConnection: vi.fn(),
  })),
}));

import { useBrewStatus } from './useBrewStatus';

describe('BrewProvider', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const mockUseBrewStatus = useBrewStatus as ReturnType<typeof vi.fn>;

  const createMockHookReturn = (overrides = {}) => ({
    brewInProgress: null,
    fetchBrewInProgress: vi.fn(),
    startConnection: vi.fn(),
    stopConnection: vi.fn(),
    ...overrides,
  });

  it('should provide default context values', async () => {
    mockUseBrewStatus.mockReturnValue(createMockHookReturn());

    const { result } = renderHook(() => useBrewContext(), {
      wrapper: BrewProvider,
    });

    await waitFor(() => {
      expect(result.current.brewInProgress).toBeNull();
    });

    expect(result.current.isFlipped).toBe(false);
    expect(typeof result.current.fetchBrewInProgress).toBe('function');
    expect(typeof result.current.stopConnection).toBe('function');
    expect(typeof result.current.toggleFlip).toBe('function');
    expect(typeof result.current.handlePause).toBe('function');
    expect(typeof result.current.handleResume).toBe('function');
  });

  it('should start connection on mount', () => {
    const startConnection = vi.fn();
    mockUseBrewStatus.mockReturnValue(createMockHookReturn({ startConnection }));

    renderHook(() => useBrewContext(), {
      wrapper: BrewProvider,
    });

    expect(startConnection).toHaveBeenCalled();
  });

  it('should stop connection on unmount', () => {
    const stopConnection = vi.fn();
    mockUseBrewStatus.mockReturnValue(createMockHookReturn({ stopConnection }));

    const { unmount } = renderHook(() => useBrewContext(), {
      wrapper: BrewProvider,
    });

    unmount();

    expect(stopConnection).toHaveBeenCalled();
  });

  it('should set isFlipped to true when brew_state is brewing', async () => {
    const mockBrewInProgress = {
      brew_id: 'test-123',
      current_flow_rate: '0.05',
      current_weight: '100',
      target_weight: '1337',
      brew_state: 'brewing' as const,
      brew_strategy: 'default',
      time_started: new Date().toISOString(),
      time_completed: null,
      estimated_time_remaining: '120',
      error_message: null,
      valve_position: 50,
    };

    mockUseBrewStatus.mockReturnValue(
      createMockHookReturn({ brewInProgress: mockBrewInProgress })
    );

    const { result } = renderHook(() => useBrewContext(), {
      wrapper: BrewProvider,
    });

    await waitFor(() => {
      expect(result.current.isFlipped).toBe(true);
    });
  });

  it('should set isFlipped to true when brew_state is paused', async () => {
    const mockBrewInProgress = {
      brew_id: 'test-123',
      current_flow_rate: '0.05',
      current_weight: '100',
      target_weight: '1337',
      brew_state: 'paused' as const,
      brew_strategy: 'default',
      time_started: new Date().toISOString(),
      time_completed: null,
      estimated_time_remaining: '120',
      error_message: null,
      valve_position: 50,
    };

    mockUseBrewStatus.mockReturnValue(
      createMockHookReturn({ brewInProgress: mockBrewInProgress })
    );

    const { result } = renderHook(() => useBrewContext(), {
      wrapper: BrewProvider,
    });

    await waitFor(() => {
      expect(result.current.isFlipped).toBe(true);
    });
  });

  it('should set isFlipped to true when brew_state is error', async () => {
    const mockBrewInProgress = {
      brew_id: 'test-123',
      current_flow_rate: '0.05',
      current_weight: '100',
      target_weight: '1337',
      brew_state: 'error' as const,
      brew_strategy: 'default',
      time_started: new Date().toISOString(),
      time_completed: null,
      estimated_time_remaining: null,
      error_message: 'Test error',
      valve_position: 50,
    };

    mockUseBrewStatus.mockReturnValue(
      createMockHookReturn({ brewInProgress: mockBrewInProgress })
    );

    const { result } = renderHook(() => useBrewContext(), {
      wrapper: BrewProvider,
    });

    await waitFor(() => {
      expect(result.current.isFlipped).toBe(true);
    });
  });

  it('should not set isFlipped when brew_state is idle', async () => {
    const mockBrewInProgress = {
      brew_id: 'test-123',
      current_flow_rate: null,
      current_weight: null,
      target_weight: '1337',
      brew_state: 'idle' as const,
      brew_strategy: 'default',
      time_started: new Date().toISOString(),
      time_completed: null,
      estimated_time_remaining: null,
      error_message: null,
      valve_position: null,
    };

    mockUseBrewStatus.mockReturnValue(
      createMockHookReturn({ brewInProgress: mockBrewInProgress })
    );

    const { result } = renderHook(() => useBrewContext(), {
      wrapper: BrewProvider,
    });

    await waitFor(() => {
      expect(result.current.isFlipped).toBe(false);
    });
  });

  it('should not set isFlipped when brew_state is completed', async () => {
    const mockBrewInProgress = {
      brew_id: 'test-123',
      current_flow_rate: '0.05',
      current_weight: '1337',
      target_weight: '1337',
      brew_state: 'completed' as const,
      brew_strategy: 'default',
      time_started: new Date().toISOString(),
      time_completed: new Date().toISOString(),
      estimated_time_remaining: null,
      error_message: null,
      valve_position: 100,
    };

    mockUseBrewStatus.mockReturnValue(
      createMockHookReturn({ brewInProgress: mockBrewInProgress })
    );

    const { result } = renderHook(() => useBrewContext(), {
      wrapper: BrewProvider,
    });

    await waitFor(() => {
      expect(result.current.isFlipped).toBe(false);
    });
  });

  it('should toggle isFlipped when toggleFlip is called', async () => {
    mockUseBrewStatus.mockReturnValue(createMockHookReturn());

    const { result } = renderHook(() => useBrewContext(), {
      wrapper: BrewProvider,
    });

    await waitFor(() => {
      expect(result.current.isFlipped).toBe(false);
    });

    // Toggle on
    act(() => {
      result.current.toggleFlip();
    });

    expect(result.current.isFlipped).toBe(true);

    // Toggle off
    act(() => {
      result.current.toggleFlip();
    });

    expect(result.current.isFlipped).toBe(false);
  });

  it('should call pauseBrew and fetchBrewInProgress when handlePause is called', async () => {
    const fetchBrewInProgress = vi.fn();
    mockUseBrewStatus.mockReturnValue(
      createMockHookReturn({ fetchBrewInProgress })
    );

    const { result } = renderHook(() => useBrewContext(), {
      wrapper: BrewProvider,
    });

    await act(async () => {
      await result.current.handlePause();
    });

    expect(constants.pauseBrew).toHaveBeenCalled();
    expect(fetchBrewInProgress).toHaveBeenCalled();
  });

  it('should call resumeBrew and fetchBrewInProgress when handleResume is called', async () => {
    const fetchBrewInProgress = vi.fn();
    mockUseBrewStatus.mockReturnValue(
      createMockHookReturn({ fetchBrewInProgress })
    );

    const { result } = renderHook(() => useBrewContext(), {
      wrapper: BrewProvider,
    });

    await act(async () => {
      await result.current.handleResume();
    });

    expect(constants.resumeBrew).toHaveBeenCalled();
    expect(fetchBrewInProgress).toHaveBeenCalled();
  });

  it('should pass brewInProgress from useBrewStatus to context', async () => {
    const mockBrewInProgress = {
      brew_id: 'test-123',
      current_flow_rate: '0.05',
      current_weight: '100',
      target_weight: '1337',
      brew_state: 'brewing' as const,
      brew_strategy: 'default',
      time_started: new Date().toISOString(),
      time_completed: null,
      estimated_time_remaining: '120',
      error_message: null,
      valve_position: 50,
    };

    mockUseBrewStatus.mockReturnValue(
      createMockHookReturn({ brewInProgress: mockBrewInProgress })
    );

    const { result } = renderHook(() => useBrewContext(), {
      wrapper: BrewProvider,
    });

    await waitFor(() => {
      expect(result.current.brewInProgress).toEqual(mockBrewInProgress);
    });
  });

  it('should pass through stopConnection from useBrewStatus', () => {
    const stopConnection = vi.fn();
    mockUseBrewStatus.mockReturnValue(createMockHookReturn({ stopConnection }));

    const { result } = renderHook(() => useBrewContext(), {
      wrapper: BrewProvider,
    });

    result.current.stopConnection();

    expect(stopConnection).toHaveBeenCalled();
  });

  it('should pass through fetchBrewInProgress from useBrewStatus', async () => {
    const fetchBrewInProgress = vi.fn();
    mockUseBrewStatus.mockReturnValue(
      createMockHookReturn({ fetchBrewInProgress })
    );

    const { result } = renderHook(() => useBrewContext(), {
      wrapper: BrewProvider,
    });

    await act(async () => {
      await result.current.fetchBrewInProgress();
    });

    expect(fetchBrewInProgress).toHaveBeenCalled();
  });
});
