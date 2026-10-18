import { afterEach, expect, it, vi } from 'vitest';
import { api, ApiError } from '../api';

afterEach(() => vi.unstubAllGlobals());

it('preserves structured validation errors for accessible field feedback', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          username: ['This username is unavailable.'],
          display_name: ['Ensure this field has no more than 40 characters.'],
        }),
        { status: 400 },
      ),
    ),
  );
  try {
    await api('/test');
    expect.fail('Expected validation rejection');
  } catch (error) {
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).fields).toEqual({
      username: ['This username is unavailable.'],
      display_name: ['Ensure this field has no more than 40 characters.'],
    });
    expect((error as Error).message).toContain('username: This username is unavailable.');
  }
});

it('retains only the two supported public closure fields for the login modal', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          code: 'account_closed',
          detail: 'Your account has been closed.',
          closure: {
            reason: 'Public reason',
            issued_at: '2026-10-18T12:00:00Z',
            internal_note: 'PRIVATE',
          },
        }),
        { status: 400 },
      ),
    ),
  );
  try {
    await api('/test');
    expect.fail('Expected closure rejection');
  } catch (error) {
    expect(error).toMatchObject({
      code: 'account_closed',
      message: 'Your account has been closed.',
      closure: { reason: 'Public reason', issued_at: '2026-10-18T12:00:00Z' },
    });
    expect((error as ApiError).closure).not.toHaveProperty('internal_note');
  }
});
