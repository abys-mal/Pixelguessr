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
