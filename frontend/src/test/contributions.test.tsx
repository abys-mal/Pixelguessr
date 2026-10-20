import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { App } from '../App';
import { api, type Session, type User } from '../api';
import { AuthProvider } from '../auth/AuthProvider';
import type { Contribution } from '../contributions/api';

vi.mock('../api', async (original) => ({ ...(await original<object>()), api: vi.fn() }));
const owner: User = {
  id: 'owner-id',
  username: 'contributor',
  display_name: 'Contributor',
  email: 'private@example.test',
  rating: 1000,
  ranked_tier: null,
  title: null,
  ranked_matches: 0,
  ranked_wins: 0,
  ranked_losses: 0,
  date_joined: '2026-01-01T00:00:00Z',
};
const picture: Contribution = {
  id: 'picture-id',
  status: 'pending',
  canonical_answer: 'red panda',
  category: 1,
  category_name: 'Nature',
  accepted_synonyms: ['lesser panda'],
  source: 'manual',
  source_url: '',
  license: 'CC0',
  attribution: 'Creator credit',
  created_at: '2026-10-17T12:00:00Z',
  preview_url: '/private-preview/',
  explanation: '',
  submitter: 'contributor',
  submitter_id: owner.id,
};
let current: Session;
let rows: Contribution[];
let fail: string;
let sent: FormData | null;
const list = (items: Contribution[]) => ({
  count: items.length,
  next: null,
  previous: null,
  results: items,
});
beforeEach(() => {
  current = { user: owner, restrictions: null };
  rows = [{ ...picture }];
  fail = '';
  sent = null;
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute('open', '');
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute('open');
  };
  URL.createObjectURL = vi.fn().mockReturnValue('blob:local-preview');
  URL.revokeObjectURL = vi.fn();
  vi.mocked(api)
    .mockReset()
    .mockImplementation(async (path, options) => {
      if (path === '/api/auth/me/') return current;
      if (path === '/api/library/categories/')
        return [
          { id: 2, name: 'Objects', slug: 'objects' },
          { id: 1, name: 'Nature', slug: 'nature' },
        ];
      if (path.startsWith('/api/library/contributions/?')) {
        if (fail === 'history') throw new Error('Contribution history unavailable.');
        const params = new URLSearchParams(path.split('?')[1]);
        const status = params.get('status');
        const filtered = rows.filter((row) => status === 'all' || row.status === status);
        return {
          ...list(filtered),
          count: filtered.length ? 25 : 0,
          page: Number(params.get('page')),
          page_size: 24,
          total_pages: filtered.length ? 2 : 0,
          next: params.get('page') === '1' ? '?page=2' : null,
          previous: params.get('page') === '2' ? '?page=1' : null,
          stats: {
            total: rows.length,
            pending: rows.filter((r) => r.status === 'pending').length,
            approved: rows.filter((r) => r.status === 'approved').length,
          },
        };
      }
      if (path === '/api/library/contributions/' && options?.method === 'POST') {
        if (fail) throw new Error(fail);
        sent = options.body as FormData;
        rows = [{ ...picture, id: 'new-id' }, ...rows];
        return rows[0];
      }
      if (path.startsWith('/api/library/contributions/'))
        return rows.find((row) => path.includes(row.id));
      if (path === '/api/moderation/workspace/')
        return {
          administrator: current.user?.administrator,
          pending_reports: 0,
          pending_appeals: 0,
        };
      if (path.startsWith('/api/moderation/workspace/administration/player-submissions/?'))
        return list(rows);
      if (path.endsWith('/review/')) {
        if (fail) throw new Error(fail);
        const body = JSON.parse(String(options?.body));
        rows = [];
        return {
          id: picture.id,
          status:
            body.operation === 'remove'
              ? 'removed'
              : body.operation === 'approve'
                ? 'approved'
                : 'rejected',
        };
      }
      return {};
    });
});
function Route() {
  return <output aria-label="Current route">{useLocation().pathname}</output>;
}
function show(route = '/contributions') {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <AuthProvider>
        <App />
        <Route />
      </AuthProvider>
    </MemoryRouter>,
  );
}
async function openNew() {
  await userEvent.click(await screen.findByRole('button', { name: '+ New Submission' }));
  return within(screen.getByRole('dialog', { name: 'New Submission' }));
}
async function fillSubmission() {
  const dialog = await openNew();
  await userEvent.upload(
    dialog.getByLabelText(/^Image upload/),
    new File(['image bytes'], 'secret.png', { type: 'image/png' }),
  );
  await userEvent.type(dialog.getByLabelText('Canonical answer'), 'fox');
  await userEvent.selectOptions(dialog.getByLabelText('Category'), '1');
  await userEvent.type(dialog.getByLabelText(/^Accepted synonyms/), 'vulpes, red fox');
  await userEvent.type(dialog.getByLabelText('License / usage rights'), 'CC0');
  await userEvent.type(dialog.getByLabelText('Attribution'), 'Me');
  await userEvent.click(dialog.getByRole('checkbox'));
  return dialog;
}

it('redirects the old submit URL and shows the private dashboard', async () => {
  show('/submit');
  await screen.findByRole('heading', { name: 'Image Contributions' });
  expect(screen.getByLabelText('Current route')).toHaveTextContent('/contributions');
  expect(await screen.findByRole('button', { name: /red panda/ })).toBeInTheDocument();
  expect(screen.getByText('Total contributions')).toBeInTheDocument();
});
it('shows the existing sign-in prompt without requesting private history', async () => {
  current = { user: null, restrictions: null };
  show();
  await screen.findByRole('heading', { name: 'Make yourself at home' });
  expect(vi.mocked(api).mock.calls.some(([path]) => path.includes('/contributions/'))).toBe(false);
});
it('paginates and filters through the server while staying on the dashboard', async () => {
  show();
  await screen.findByRole('button', { name: /red panda/ });
  await userEvent.click(screen.getByRole('button', { name: 'Next' }));
  await waitFor(() =>
    expect(vi.mocked(api).mock.calls.some(([path]) => path.includes('page=2'))).toBe(true),
  );
  await userEvent.click(screen.getByRole('button', { name: 'Approved' }));
  await screen.findByRole('heading', { name: 'No approved contributions.' });
  expect(vi.mocked(api).mock.calls.some(([path]) => path.includes('status=approved&page=1'))).toBe(
    true,
  );
  expect(screen.getByLabelText('Current route')).toHaveTextContent('/contributions');
});
it('shows read-only details in an overlay without exposing staff metadata', async () => {
  rows = [
    {
      ...picture,
      explanation: 'A player-visible explanation',
      review_reason: 'Staff-only text',
      import_metadata: { secret: 'private' },
    } as Contribution,
  ];
  show();
  await userEvent.click(await screen.findByRole('button', { name: /red panda/ }));
  const dialog = within(await screen.findByRole('dialog', { name: 'Contribution details' }));
  await dialog.findByText('A player-visible explanation');
  expect(dialog.getByText('lesser panda')).toBeInTheDocument();
  expect(dialog.queryByRole('textbox')).not.toBeInTheDocument();
  expect(dialog.queryByText('Staff-only text')).not.toBeInTheDocument();
  expect(dialog.queryByRole('button', { name: /Edit|Withdraw|Delete/ })).not.toBeInTheDocument();
  expect(screen.getByLabelText('Current route')).toHaveTextContent('/contributions');
});
it('renders removed history and details without old image content even if extra fields arrive', async () => {
  rows = [
    {
      ...picture,
      status: 'removed',
      canonical_answer: 'Secret removed answer',
      preview_url: '/deleted-private/',
    },
  ];
  show();
  expect(await screen.findByRole('button', { name: /Removed contribution/ })).not.toHaveTextContent(
    'Secret removed answer',
  );
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: /Removed contribution/ }));
  const dialog = within(screen.getByRole('dialog'));
  await dialog.findByText('This contribution was removed by an administrator.');
  expect(dialog.queryByRole('img')).not.toBeInTheDocument();
  expect(dialog.queryByText('Secret removed answer')).not.toBeInTheDocument();
});
it('opens an upload-only draft with a local preview and submits synonyms and rights', async () => {
  show();
  const dialog = await fillSubmission();
  expect(dialog.getByRole('img', { name: 'Local image preview' })).toHaveAttribute(
    'src',
    'blob:local-preview',
  );
  expect(dialog.queryByLabelText('External image URL')).not.toBeInTheDocument();
  fireEvent.submit(dialog.getByRole('button', { name: 'Submit for review' }).closest('form')!);
  await screen.findByText(/Image submitted/);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(sent?.get('accepted_synonyms')).toBe('["vulpes","red fox"]');
  expect(sent?.get('rights_acknowledged')).toBe('true');
  expect(sent?.get('image_file')).toBeInstanceOf(File);
  await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:local-preview'));
});
it('releases replaced previews and releases the current preview only when the draft closes', async () => {
  vi.mocked(URL.createObjectURL)
    .mockReturnValueOnce('blob:first')
    .mockReturnValueOnce('blob:second');
  show();
  const dialog = await openNew();
  const upload = dialog.getByLabelText(/Image upload/);
  await userEvent.upload(upload, new File(['first'], 'first.png', { type: 'image/png' }));
  await userEvent.upload(upload, new File(['second'], 'second.png', { type: 'image/png' }));
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:first');
  expect(URL.revokeObjectURL).not.toHaveBeenCalledWith('blob:second');
  await userEvent.click(dialog.getByRole('button', { name: 'Cancel' }));
  await userEvent.click(screen.getByRole('button', { name: 'Keep editing' }));
  expect(URL.revokeObjectURL).not.toHaveBeenCalledWith('blob:second');
  await userEvent.click(dialog.getByRole('button', { name: 'Cancel' }));
  await userEvent.click(screen.getByRole('button', { name: 'Discard draft' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:second'));
});
it('requires source URL for licensed images while explaining owned and AI rights', async () => {
  show();
  const dialog = await openNew();
  await userEvent.selectOptions(dialog.getByLabelText('Image source / rights'), 'licensed');
  expect(dialog.getByLabelText('Source / provenance URL (required)')).toBeRequired();
  await userEvent.selectOptions(dialog.getByLabelText('Image source / rights'), 'ai');
  expect(dialog.getByLabelText('Source / provenance URL (optional)')).not.toBeRequired();
  expect(dialog.getByText(/generation tool’s usage terms/)).toBeInTheDocument();
});
it.each(['Cancel', 'Escape'])(
  'keeps an untouched draft open after file-picker %s',
  async (action) => {
    show();
    const dialog = await openNew();
    const upload = dialog.getByLabelText(/Image upload/);
    if (action === 'Escape') fireEvent.keyDown(upload, { key: 'Escape' });
    fireEvent(upload, new Event('cancel', { bubbles: true }));
    expect(screen.getByRole('dialog', { name: 'New Submission' })).toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: 'Discard this draft?' })).not.toBeInTheDocument();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    await userEvent.click(dialog.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  },
);
it.each(['Cancel', 'Escape'])(
  'preserves form data and the selected preview after file-picker %s',
  async (action) => {
    show();
    const dialog = await fillSubmission();
    const upload = dialog.getByLabelText(/Image upload/) as HTMLInputElement;
    const file = upload.files?.[0];
    if (action === 'Escape') fireEvent.keyDown(upload, { key: 'Escape' });
    fireEvent(upload, new Event('cancel', { bubbles: true }));
    expect(screen.queryByRole('dialog', { name: 'Discard this draft?' })).not.toBeInTheDocument();
    expect(dialog.getByLabelText('Canonical answer')).toHaveValue('fox');
    expect(upload.files?.[0]).toBe(file);
    expect(dialog.getByRole('img', { name: 'Local image preview' })).toHaveAttribute(
      'src',
      'blob:local-preview',
    );
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
    // A subsequent cancel originating from the dialog itself is intentional Escape.
    fireEvent(
      screen.getByRole('dialog', { name: 'New Submission' }),
      new Event('cancel', { bubbles: false, cancelable: true }),
    );
    await screen.findByRole('dialog', { name: 'Discard this draft?' });
    await userEvent.click(screen.getByRole('button', { name: 'Keep editing' }));
    expect(dialog.getByLabelText('Canonical answer')).toHaveValue('fox');
    expect(dialog.getByRole('img', { name: 'Local image preview' })).toBeInTheDocument();
  },
);
it('asks before discarding entered data, preserves it when cancelled and supports Escape', async () => {
  show();
  const dialog = await openNew();
  await userEvent.type(dialog.getByLabelText('Canonical answer'), 'draft answer');
  await userEvent.click(dialog.getByRole('button', { name: 'Cancel' }));
  await screen.findByRole('dialog', { name: 'Discard this draft?' });
  await userEvent.click(screen.getByRole('button', { name: 'Keep editing' }));
  expect(dialog.getByLabelText('Canonical answer')).toHaveValue('draft answer');
  fireEvent(
    screen.getByRole('dialog', { name: 'New Submission' }),
    new Event('cancel', { bubbles: true, cancelable: true }),
  );
  await screen.findByRole('dialog', { name: 'Discard this draft?' });
  await userEvent.click(screen.getByRole('button', { name: 'Discard draft' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(sent).toBeNull();
});
it('keeps entered data and displays failed upload validation', async () => {
  fail = 'Invalid image dimensions.';
  show();
  const dialog = await fillSubmission();
  fireEvent.submit(dialog.getByRole('button', { name: 'Submit for review' }).closest('form')!);
  expect(await dialog.findByRole('alert')).toHaveTextContent(fail);
  expect(dialog.getByLabelText('Canonical answer')).toHaveValue('fox');
});
it('lets restricted players read history while disabling new submissions', async () => {
  current = {
    user: owner,
    restrictions: {
      blocked: false,
      probation: true,
      suspension: false,
      unacknowledged_warnings: [],
    },
  };
  show();
  await screen.findByRole('button', { name: /red panda/ });
  expect(screen.getByRole('button', { name: '+ New Submission' })).toBeDisabled();
  expect(screen.getByRole('link', { name: 'View account notices' })).toBeInTheDocument();
});
it('provides retry on history failure and a polished empty state', async () => {
  fail = 'history';
  show();
  expect(await screen.findByRole('alert')).toHaveTextContent('Contribution history unavailable.');
  rows = [];
  fail = '';
  await userEvent.click(screen.getByRole('button', { name: 'Try again' }));
  await screen.findByRole('heading', { name: 'Your next perspective starts here.' });
});
it('offers administrator review corrections with final one-stage approval', async () => {
  current = {
    user: { ...owner, administrator: true, moderation_access: true },
    restrictions: null,
  };
  show('/moderation/administration/images?tab=submissions');
  expect(await screen.findByRole('button', { name: 'Pending player review' })).toBeInTheDocument();
  await userEvent.click(await screen.findByRole('button', { name: /red panda/ }));
  const dialog = within(screen.getByRole('dialog', { name: 'Review player submission' }));
  await waitFor(() => expect(dialog.getByLabelText('Category')).toHaveValue('1'));
  expect(dialog.getByLabelText('Review explanation (optional)')).not.toBeRequired();
  await userEvent.clear(dialog.getByLabelText('Canonical answer'));
  await userEvent.type(dialog.getByLabelText('Canonical answer'), 'blue square');
  await userEvent.click(dialog.getByRole('button', { name: 'Approve' }));
  await screen.findByText('Review saved.');
  const request = vi.mocked(api).mock.calls.find(([path]) => path.endsWith('/review/'));
  expect(JSON.parse(String(request?.[1]?.body))).toMatchObject({
    operation: 'approve',
    corrections: { canonical_answer: 'blue square', license: 'CC0', attribution: 'Creator credit' },
  });
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

it.each(['approved', 'rejected'] as const)(
  'keeps %s player history accessible and offers management in the correct view',
  async (status) => {
    current = {
      user: { ...owner, administrator: true, moderation_access: true },
      restrictions: null,
    };
    rows = [{ ...picture, status }];
    show('/moderation/administration/images?tab=submissions');
    await userEvent.click(await screen.findByRole('button', { name: 'All' }));
    await userEvent.click(await screen.findByRole('button', { name: /red panda/ }));
    const dialog = within(screen.getByRole('dialog', { name: 'Review player submission' }));
    if (status === 'approved') {
      expect(dialog.getByRole('link', { name: 'Open in Image Library' })).toHaveAttribute(
        'href',
        '/moderation/administration/images?q=picture-id',
      );
    } else {
      expect(dialog.queryByRole('link', { name: 'Open in Image Library' })).not.toBeInTheDocument();
      await userEvent.click(
        dialog.getByRole('button', { name: 'Permanently delete image: red panda' }),
      );
      await screen.findByRole('dialog', { name: 'Permanently delete image?' });
      await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
      expect(screen.getByRole('dialog', { name: 'Review player submission' })).toBeInTheDocument();
      expect(vi.mocked(api).mock.calls.some(([path]) => path.endsWith('/delete/'))).toBe(false);
    }
  },
);
it('rejects with an optional explicitly player-visible explanation', async () => {
  current = {
    user: { ...owner, administrator: true, moderation_access: true },
    restrictions: null,
  };
  show('/moderation/administration/images?tab=submissions');
  await userEvent.click(await screen.findByRole('button', { name: /red panda/ }));
  const dialog = within(screen.getByRole('dialog'));
  await userEvent.type(dialog.getByLabelText('Review explanation (optional)'), 'Too ambiguous');
  await userEvent.click(dialog.getByRole('checkbox', { name: 'Visible to player' }));
  await userEvent.click(dialog.getByRole('button', { name: 'Reject' }));
  await screen.findByText('Review saved.');
  expect(
    JSON.parse(
      String(vi.mocked(api).mock.calls.find(([path]) => path.endsWith('/review/'))?.[1]?.body),
    ),
  ).toMatchObject({ operation: 'reject', explanation: 'Too ambiguous', visible_to_player: true });
});
it('requires explicit removal confirmation and cancellation leaves the contribution intact', async () => {
  current = {
    user: { ...owner, administrator: true, moderation_access: true },
    restrictions: null,
  };
  show('/moderation/administration/images?tab=submissions');
  await userEvent.click(await screen.findByRole('button', { name: /red panda/ }));
  await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }));
  const confirm = within(screen.getByRole('dialog', { name: 'Remove this contribution?' }));
  expect(vi.mocked(api).mock.calls.some(([path]) => path.endsWith('/review/'))).toBe(false);
  await userEvent.click(confirm.getByRole('button', { name: 'Cancel' }));
  expect(screen.getByRole('dialog', { name: 'Review player submission' })).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Remove' }));
  await userEvent.click(screen.getByRole('button', { name: 'Remove Permanently' }));
  await screen.findByText('Review saved.');
  expect(
    JSON.parse(
      String(vi.mocked(api).mock.calls.find(([path]) => path.endsWith('/review/'))?.[1]?.body),
    ),
  ).toMatchObject({ operation: 'remove', confirm: true });
});
