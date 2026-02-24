import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  apiUrl,
  wsUrl,
  DEFAULT_FLOW,
  DEFAULT_VALVE_INTERVAL,
  DEFAULT_EPSILON,
  POLL_INTERVAL_MS,
  DEFAULT_TARGET_WEIGHT,
  STRATEGIES,
  DEFAULT_STRATEGY,
  type StrategyType,
  type Strategy,
} from './constants';
import {
  pauseBrew,
  resumeBrew,
  nudgeOpen,
  nudgeClose,
} from './brewService';

describe('API Configuration', () => {
  describe('apiUrl', () => {
    it('should be a valid URL string', () => {
      expect(typeof apiUrl).toBe('string');
      expect(apiUrl.length).toBeGreaterThan(0);
    });

    it('should end with /api', () => {
      expect(apiUrl.endsWith('/api')).toBe(true);
    });
  });

  describe('wsUrl', () => {
    it('should return a WebSocket URL string', () => {
      const ws = wsUrl();
      expect(typeof ws).toBe('string');
      expect(ws.startsWith('ws://') || ws.startsWith('wss://')).toBe(true);
    });

    it('should not contain /api', () => {
      const ws = wsUrl();
      expect(ws).not.toContain('/api');
    });
  });
});

describe('Default Values', () => {
  it('should have valid DEFAULT_FLOW', () => {
    expect(DEFAULT_FLOW).toBe('0.05');
    expect(parseFloat(DEFAULT_FLOW)).toBeGreaterThan(0);
  });

  it('should have valid DEFAULT_VALVE_INTERVAL', () => {
    expect(DEFAULT_VALVE_INTERVAL).toBe('90');
    expect(parseInt(DEFAULT_VALVE_INTERVAL, 10)).toBeGreaterThan(0);
  });

  it('should have valid DEFAULT_EPSILON', () => {
    expect(DEFAULT_EPSILON).toBe('0.008');
    expect(parseFloat(DEFAULT_EPSILON)).toBeGreaterThan(0);
  });

  it('should have valid POLL_INTERVAL_MS', () => {
    expect(POLL_INTERVAL_MS).toBe(4000);
    expect(POLL_INTERVAL_MS).toBeGreaterThan(0);
  });

  it('should have valid DEFAULT_TARGET_WEIGHT', () => {
    expect(DEFAULT_TARGET_WEIGHT).toBe('1337');
    expect(parseInt(DEFAULT_TARGET_WEIGHT, 10)).toBeGreaterThan(0);
  });

  it('should have valid DEFAULT_STRATEGY', () => {
    const validStrategies: StrategyType[] = ['default', 'pid', 'kalman_pid', 'smith_predictor_advanced', 'adaptive_gain_scheduling', 'mpc'];
    expect(validStrategies).toContain(DEFAULT_STRATEGY);
  });
});

describe('STRATEGIES', () => {
  it('should have at least one strategy', () => {
    expect(STRATEGIES.length).toBeGreaterThan(0);
  });

  it('should contain all required strategies', () => {
    const strategyIds = STRATEGIES.map(s => s.id);
    expect(strategyIds).toContain('default');
    expect(strategyIds).toContain('pid');
    expect(strategyIds).toContain('kalman_pid');
    expect(strategyIds).toContain('smith_predictor_advanced');
    expect(strategyIds).toContain('adaptive_gain_scheduling');
    expect(strategyIds).toContain('mpc');
  });

  it('should have unique strategy IDs', () => {
    const ids = STRATEGIES.map(s => s.id);
    const uniqueIds = new Set(ids);
    expect(uniqueIds.size).toBe(ids.length);
  });

  it('each strategy should have required properties', () => {
    STRATEGIES.forEach((strategy: Strategy) => {
      expect(strategy).toHaveProperty('id');
      expect(strategy).toHaveProperty('name');
      expect(strategy).toHaveProperty('description');
      expect(strategy).toHaveProperty('params');
      expect(Array.isArray(strategy.params)).toBe(true);
    });
  });

  it('each strategy should have non-empty name and description', () => {
    STRATEGIES.forEach((strategy: Strategy) => {
      expect(strategy.name.length).toBeGreaterThan(0);
      expect(strategy.description.length).toBeGreaterThan(0);
    });
  });

  describe('default strategy', () => {
    it('should have no parameters', () => {
      const defaultStrategy = STRATEGIES.find(s => s.id === 'default');
      expect(defaultStrategy).toBeDefined();
      expect(defaultStrategy!.params).toHaveLength(0);
    });
  });

  describe('pid strategy', () => {
    it('should have kp, ki, kd parameters', () => {
      const pidStrategy = STRATEGIES.find(s => s.id === 'pid');
      expect(pidStrategy).toBeDefined();
      expect(pidStrategy!.params).toHaveLength(3);
      
      const paramNames = pidStrategy!.params.map(p => p.name);
      expect(paramNames).toContain('kp');
      expect(paramNames).toContain('ki');
      expect(paramNames).toContain('kd');
    });

    it('should have valid default values for pid parameters', () => {
      const pidStrategy = STRATEGIES.find(s => s.id === 'pid');
      pidStrategy!.params.forEach(param => {
        expect(parseFloat(param.defaultValue)).toBeGreaterThan(0);
        expect(param.label.length).toBeGreaterThan(0);
        expect(param.placeholder.length).toBeGreaterThan(0);
      });
    });
  });

  describe('kalman_pid strategy', () => {
    it('should have kp, ki, kd, q, r parameters', () => {
      const strategy = STRATEGIES.find(s => s.id === 'kalman_pid');
      expect(strategy).toBeDefined();
      expect(strategy!.params.length).toBeGreaterThanOrEqual(5);
      
      const paramNames = strategy!.params.map(p => p.name);
      expect(paramNames).toContain('kp');
      expect(paramNames).toContain('ki');
      expect(paramNames).toContain('kd');
      expect(paramNames).toContain('q');
      expect(paramNames).toContain('r');
    });
  });

  describe('adaptive_gain_scheduling strategy', () => {
    it('should have region-based parameters', () => {
      const strategy = STRATEGIES.find(s => s.id === 'adaptive_gain_scheduling');
      expect(strategy).toBeDefined();
      
      const paramNames = strategy!.params.map(p => p.name);
      // Should have low, med, high region parameters
      expect(paramNames).toContain('kp_low');
      expect(paramNames).toContain('kp_med');
      expect(paramNames).toContain('kp_high');
    });
  });

  describe('mpc strategy', () => {
    it('should have horizon and weight parameters', () => {
      const strategy = STRATEGIES.find(s => s.id === 'mpc');
      expect(strategy).toBeDefined();
      
      const paramNames = strategy!.params.map(p => p.name);
      expect(paramNames).toContain('horizon');
      expect(paramNames).toContain('q_error');
      expect(paramNames).toContain('q_control');
    });
  });
});

describe('API Functions', () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  describe('pauseBrew', () => {
    it('should call the correct endpoint', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        statusText: 'OK',
      });

      await pauseBrew();
      
      expect(fetch).toHaveBeenCalledTimes(1);
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining('/brew/pause'),
        expect.objectContaining({ method: 'POST' })
      );
    });

    it('should throw error when response is not ok', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        statusText: 'Internal Server Error',
      });

      await expect(pauseBrew()).rejects.toThrow('Failed to pause brew');
    });
  });

  describe('resumeBrew', () => {
    it('should call the correct endpoint', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        statusText: 'OK',
      });

      await resumeBrew();
      
      expect(fetch).toHaveBeenCalledTimes(1);
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining('/brew/resume'),
        expect.objectContaining({ method: 'POST' })
      );
    });

    it('should throw error when response is not ok', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        statusText: 'Bad Request',
      });

      await expect(resumeBrew()).rejects.toThrow('Failed to resume brew');
    });
  });

  describe('nudgeOpen', () => {
    it('should call the correct endpoint', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        statusText: 'OK',
      });

      await nudgeOpen();
      
      expect(fetch).toHaveBeenCalledTimes(1);
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining('/brew/nudge/open'),
        expect.objectContaining({ method: 'POST' })
      );
    });

    it('should throw error when response is not ok', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        statusText: 'Internal Server Error',
      });

      await expect(nudgeOpen()).rejects.toThrow('Failed to nudge open');
    });

    it('should throw rate limit error when status is 429', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 429,
        statusText: 'Too Many Requests',
      });

      await expect(nudgeOpen()).rejects.toThrow('Nudge too frequent, please wait');
    });
  });

  describe('nudgeClose', () => {
    it('should call the correct endpoint', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        statusText: 'OK',
      });

      await nudgeClose();
      
      expect(fetch).toHaveBeenCalledTimes(1);
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining('/brew/nudge/close'),
        expect.objectContaining({ method: 'POST' })
      );
    });

    it('should throw error when response is not ok', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        statusText: 'Internal Server Error',
      });

      await expect(nudgeClose()).rejects.toThrow('Failed to nudge close');
    });

    it('should throw rate limit error when status is 429', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 429,
        statusText: 'Too Many Requests',
      });

      await expect(nudgeClose()).rejects.toThrow('Nudge too frequent, please wait');
    });
  });
});
