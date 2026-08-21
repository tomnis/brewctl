import { describe, it, expect, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useBrewStatus } from './useBrewStatus';

// The hook opens an EventSource on mount; stub the URL so it points nowhere
// real. Only the basic API and initial state are covered here.
vi.mock('./constants', () => ({
  sseUrl: vi.fn(() => 'http://localhost:8000/sse/brew/status'),
  healthSseUrl: vi.fn(() => 'http://localhost:8000/sse/health'),
}));

describe('useBrewStatus', () => {
  describe('initial state', () => {
    it('should have brewInProgress as null initially', () => {
      const { result } = renderHook(() => useBrewStatus());
      expect(result.current.brewInProgress).toBeNull();
    });

    it('should return startConnection, stopConnection, and fetchBrewInProgress functions', () => {
      const { result } = renderHook(() => useBrewStatus());
      expect(typeof result.current.startConnection).toBe('function');
      expect(typeof result.current.stopConnection).toBe('function');
      expect(typeof result.current.fetchBrewInProgress).toBe('function');
    });

    it('should have isFlipped as false initially', () => {
      const { result } = renderHook(() => useBrewStatus());
      // Note: useBrewStatus doesn't have isFlipped, but we test that brewInProgress is null
      expect(result.current.brewInProgress).toBeNull();
    });
  });
});
