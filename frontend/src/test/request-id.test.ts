import { afterEach, expect, it, vi } from 'vitest';
import { createRequestId } from '../requestId';

afterEach(() => vi.unstubAllGlobals());

it('uses the native UUID generator when available', () => {
  const randomUUID = vi.fn(() => '8843bacc-17ba-41c6-a3dd-ae59d928fc1a');
  const getRandomValues = vi.fn();
  vi.stubGlobal('crypto', { randomUUID, getRandomValues });
  expect(createRequestId()).toBe('8843bacc-17ba-41c6-a3dd-ae59d928fc1a');
  expect(randomUUID).toHaveBeenCalledOnce();
  expect(getRandomValues).not.toHaveBeenCalled();
});

it.each([
  [0, '00000000-0000-4000-8000-000000000000'],
  [255, 'ffffffff-ffff-4fff-bfff-ffffffffffff'],
])('generates UUIDv4 from secure random bytes on HTTP LAN origins: %i', (byte, expected) => {
  const getRandomValues = vi.fn((bytes: Uint8Array) => bytes.fill(byte));
  vi.stubGlobal('crypto', { getRandomValues });
  expect(createRequestId()).toBe(expected);
  expect(getRandomValues).toHaveBeenCalledOnce();
  expect(getRandomValues.mock.calls[0][0]).toHaveLength(16);
});
