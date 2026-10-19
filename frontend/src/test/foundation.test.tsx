import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import { AuthContext } from '../auth/context';
import { api } from '../api';

const guest = {
  user: null,
  restrictions: null,
  loading: false,
  error: '',
  refresh: vi.fn(),
  signOut: vi.fn(),
};
function page(path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthContext.Provider value={guest}>
        <App />
      </AuthContext.Provider>
    </MemoryRouter>,
  );
}

describe('Established experience', () => {
  it('shows all modes and honest availability', () => {
    page();
    for (const mode of ['Ranked Duels', 'Singleplayer', 'Parties'])
      expect(screen.getByRole('heading', { name: mode })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Play Ranked Duel/ })).toHaveAttribute(
      'href',
      '/ranked',
    );
    expect(screen.getByRole('link', { name: /Play singleplayer/ })).toHaveAttribute(
      'href',
      '/singleplayer',
    );
    expect(screen.queryByText('Coming later')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^play$/i })).not.toBeInTheDocument();
  });
  it('requires a registered session for ranked gameplay', () => {
    page('/modes/ranked');
    expect(screen.getByRole('heading', { name: 'Make yourself at home' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Find opponent' })).not.toBeInTheDocument();
  });
  it('requires a session for image submission', () => {
    page('/submit');
    expect(screen.getByRole('heading', { name: 'Make yourself at home' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Submit for review/ })).not.toBeInTheDocument();
  });
  it('sends sign-in values and refreshes the session', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(
      async () => new Response(JSON.stringify({ csrfToken: 'fresh-token' }), { status: 200 }),
    );
    page('/login');
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'player' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'password-value' } });
    fireEvent.click(screen.getByRole('button', { name: /Sign in/ }));
    await waitFor(() => expect(guest.refresh).toHaveBeenCalled());
    const request = vi.mocked(fetch).mock.calls.find(([url]) => url === '/api/auth/login/');
    expect(JSON.parse(String(request?.[1]?.body))).toEqual({
      username: 'player',
      password: 'password-value',
    });
  });
  it('clears login errors and credentials when switching to registration', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) =>
      url === '/api/auth/csrf/'
        ? new Response(JSON.stringify({ csrfToken: 'fresh-token' }), { status: 200 })
        : new Response(JSON.stringify({ non_field_errors: ['Invalid username or password.'] }), {
            status: 400,
          }),
    );
    page('/login');
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'missing-player' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'invalid-password' } });
    fireEvent.click(screen.getByRole('button', { name: /Sign in/ }));
    await screen.findByRole('alert');
    fireEvent.click(screen.getByRole('link', { name: 'Create an account' }));
    expect(screen.getByRole('heading', { name: 'Join the picture.' })).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Username')).toHaveValue('');
    expect(screen.getByLabelText('Password')).toHaveValue('');
  });
  it('has a real not-found route', () => {
    page('/missing');
    expect(screen.getByRole('heading', { name: 'This tile is missing.' })).toBeInTheDocument();
  });
});

describe('API session transport', () => {
  it('obtains CSRF before mutation and keeps credentials same-origin', async () => {
    const mock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ csrfToken: 'rotated' }), { status: 200 }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    await api('/api/auth/logout/', { method: 'POST' });
    expect(mock.mock.calls[0][0]).toBe('/api/auth/csrf/');
    const options = mock.mock.calls[1][1];
    expect(options?.credentials).toBe('same-origin');
    expect(new Headers(options?.headers).get('X-CSRFToken')).toBe('rotated');
  });
  it('renders API validation errors without raw HTML', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Sign in required.' }), { status: 403 }),
    );
    await expect(api('/api/library/submissions/')).rejects.toThrow('Sign in required.');
  });
});
