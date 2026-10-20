import { render, screen, fireEvent, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { App } from '../App';
import { api, type User } from '../api';
import { AuthProvider } from '../auth/AuthProvider';
import { PlayerIdentity } from '../components/PlayerIdentity';

vi.mock('../api', async (original) => ({ ...(await original<object>()), api: vi.fn() }));
const root = '/api/moderation/workspace/administration/';
const player = {
  id: 'ordinary-id',
  username: 'imagehunter',
  display_name: 'Image Hunter',
  title: 'pro',
  rating: 1000,
  date_joined: '2026-01-01',
  is_active: true,
  protected: false,
  moderator: false,
};
const base: User = {
  ...player,
  id: 'admin-id',
  username: 'administrator',
  email: 'admin@example.test',
  title: null,
  ranked_tier: null,
  ranked_matches: 0,
  ranked_wins: 0,
  ranked_losses: 0,
  moderation_access: true,
  administrator: true,
};
const photo = {
  id: 'photo-id',
  canonical_answer: 'rose',
  accepted_synonyms: ['pink rose'],
  category: 2,
  category_name: 'Nature',
  status: 'pending',
  license: 'Pexels License',
  attribution: 'Pexels',
  source_url: '',
  source: 'manual',
  preview_url: root + 'images/photo-id/preview/',
  review_reason: '',
  import_metadata: { label_verified: false },
};
let user: User;
let calls: [string, RequestInit | undefined][];
let notice: object | null;
let images: (typeof photo)[];
let rejectError: string;
let paginateImages: boolean;
const page = (rows: unknown[]) => ({
  count: rows.length,
  page: 1,
  page_size: 24,
  total_pages: rows.length ? 1 : 0,
  next: null,
  previous: null,
  results: rows,
});
beforeEach(() => {
  user = { ...base };
  calls = [];
  notice = null;
  images = [{ ...photo }];
  rejectError = '';
  paginateImages = false;
  URL.createObjectURL = vi.fn().mockReturnValue('blob:import-preview');
  URL.revokeObjectURL = vi.fn();
  HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) {
    this.setAttribute('open', '');
  });
  HTMLDialogElement.prototype.close = vi.fn(function (this: HTMLDialogElement) {
    this.removeAttribute('open');
  });
  vi.mocked(api)
    .mockReset()
    .mockImplementation(async (path, options) => {
      calls.push([path, options]);
      if (path === '/api/auth/me/')
        return {
          user,
          restrictions: { blocked: false, probation: false, unacknowledged_warnings: [] },
        };
      if (path === '/api/moderation/workspace/')
        return { pending_reports: 0, pending_appeals: 0, administrator: user.administrator };
      if (path === '/api/library/categories/')
        return [
          { id: 1, name: 'Animals', slug: 'animals' },
          { id: 2, name: 'Nature', slug: 'nature' },
        ];
      if (path === root)
        return {
          players: 42,
          active_games: 2,
          playable_images: 12,
          pending_images: 3,
          pending_player_submissions: 2,
          incomplete_imports: 1,
          recent_activity: [],
          health: [{ name: 'Database', state: 'Healthy' }],
          import_tracking_note: 'Browser batches only.',
        };
      if (path.startsWith(root + 'staff/'))
        return page([
          {
            ...base,
            role: 'Administrator',
            account_status: 'Active',
            assigned_at: null,
            recent_activity: null,
            can_remove_moderator: false,
          },
          {
            ...base,
            id: 'other-admin',
            username: 'second_admin',
            role: 'Administrator',
            account_status: 'Active',
            assigned_at: null,
            recent_activity: null,
            can_remove_moderator: false,
          },
          {
            ...player,
            id: 'mod-id',
            username: 'moderator',
            moderator: true,
            role: 'Moderator',
            account_status: 'Active',
            assigned_at: null,
            recent_activity: null,
            can_remove_moderator: true,
          },
        ]);
      if (path.startsWith(root + 'players/?'))
        return page(path.includes('imagehunter') ? [player] : []);
      if (path.startsWith(root + 'images/?')) {
        if (!paginateImages) return page(images);
        const params = new URLSearchParams(path.split('?')[1]);
        const filtered = images.filter(
          (image) => !params.get('status') || image.status === params.get('status'),
        );
        const total = Math.ceil(filtered.length / 24);
        const current = Math.max(1, Math.min(Number(params.get('page')) || 1, total));
        return {
          count: filtered.length,
          page: current,
          page_size: 24,
          total_pages: total,
          next: current < total ? '?page=' + (current + 1) : null,
          previous: current > 1 ? '?page=' + (current - 1) : null,
          results: filtered.slice((current - 1) * 24, current * 24),
        };
      }
      if (path === root + 'images/photo-id/') {
        const changes = JSON.parse(String(options?.body ?? '{}'));
        return {
          ...photo,
          ...changes,
          import_metadata: { ...photo.import_metadata, photographer: changes.photographer ?? '' },
        };
      }
      if (path === root + 'images/review/') {
        if (rejectError)
          return { results: [{ id: 'photo-id', status: 'failed', error: rejectError }] };
        const { ids, operation } = JSON.parse(String(options?.body));
        if (['approve', 'reject'].includes(operation))
          images = images.map((image) =>
            ids.includes(image.id)
              ? { ...image, status: operation === 'approve' ? 'approved' : 'rejected' }
              : image,
          );
        return { results: [{ id: 'photo-id', status: 'success' }] };
      }
      if (path === root + 'announcement/') return { announcement: notice };
      if (path.startsWith(root + 'imports/batch-id/'))
        return page([
          { id: 'item-id', filename: 'rose.jpg', status: 'uploaded', error: '', image: photo },
        ]);
      if (path.startsWith(root + 'imports/'))
        return options?.method === 'POST'
          ? { id: 'batch-id' }
          : page([
              {
                id: 'batch-id',
                name: 'Spring collection',
                items: 1,
                pending: 1,
                failed: 0,
                created_at: '2026-01-01',
              },
            ]);
      if (path.startsWith(root + 'audit/'))
        return page([
          {
            id: 'audit-id',
            actor: 'administrator',
            action: 'admin_rating',
            target_type: 'player',
            target_id: 'ordinary-id',
            created_at: '2026-01-01',
            changes: { before: { rating: 1000 }, after: { rating: 1200 } },
            reason: 'Correction',
          },
        ]);
      if (path === root + 'health/')
        return {
          checks: [
            { name: 'Database', state: 'Healthy' },
            { name: 'Redis', state: 'Not Configured' },
          ],
        };
      if (path.startsWith('/api/moderation/workspace/players/'))
        return { player, sanctions: [], appeals: [], reports: [], activity: [] };
      return {};
    });
});
function PaginationRoute() {
  const location = useLocation();
  return <output aria-label="Pagination route">{location.pathname + location.search}</output>;
}
function show(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
        <PaginationRoute />
      </AuthProvider>
    </MemoryRouter>,
  );
}

it('preserves moderation navigation and adds all administration destinations', async () => {
  show('/moderation/administration');
  await screen.findByRole('heading', { name: 'Administration' });
  const nav = within(screen.getByRole('navigation', { name: 'Administration navigation' }));
  for (const title of [
    'Overview',
    'Image Library',
    'Image Imports',
    'Staff & Roles',
    'Audit Log',
    'System Health',
  ])
    expect(nav.getByRole('link', { name: title })).toBeInTheDocument();
  expect(screen.getByRole('navigation', { name: 'Moderation navigation' })).toBeInTheDocument();
  expect(screen.getByText('42')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Django Admin ↗' })).toHaveAttribute('href', '/admin/');
});
it.each(['images', 'imports', 'staff', 'audit', 'health'])(
  'denies moderator administration route %s',
  async (path) => {
    user = { ...user, administrator: false };
    show('/moderation/administration/' + path);
    await screen.findByRole('heading', { name: 'Administrator access required' });
    expect(
      screen.queryByRole('navigation', { name: 'Administration navigation' }),
    ).not.toBeInTheDocument();
    expect(calls.some(([path]) => path.startsWith(root))).toBe(false);
  },
);
it('requires explicit confirmation to promote an ordinary player', async () => {
  show('/moderation/administration/staff');
  await screen.findByRole('heading', { name: 'Current Staff' });
  await userEvent.type(screen.getByLabelText('Find an ordinary player'), 'imagehunter');
  await userEvent.click(screen.getByRole('button', { name: 'Search players' }));
  await userEvent.click(await screen.findByRole('button', { name: 'Promote to moderator' }));
  expect(
    calls.some(
      ([path, options]) => path === root + 'players/ordinary-id/' && options?.method === 'POST',
    ),
  ).toBe(false);
  expect(within(screen.getByRole('dialog')).getByText(/ordinary-id/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Confirm role change' }));
  await screen.findByText('Moderator access granted.');
  const write = calls.find(
    ([path, options]) => path === root + 'players/ordinary-id/' && options?.method === 'POST',
  );
  expect(JSON.parse(String(write?.[1]?.body))).toEqual({ operation: 'moderator', enabled: true });
  expect(screen.queryByText('Promote to administrator')).not.toBeInTheDocument();
});
it('edits reviewed labels and uses the real reveal endpoint', async () => {
  show('/moderation/administration/images');
  await userEvent.click(await screen.findByRole('button', { name: 'Review image' }));
  const dialog = within(screen.getByRole('dialog'));
  expect(dialog.queryByText(/Saving confirms you reviewed/)).not.toBeInTheDocument();
  expect(dialog.getByRole('img', { name: '200 of 400 tiles revealed' })).toHaveAttribute(
    'src',
    expect.stringMatching(new RegExp('^' + photo.preview_url + '\\?reveal=200&run=')),
  );
  fireEvent.change(dialog.getByRole('slider'), { target: { value: '400' } });
  expect(dialog.getByRole('img', { name: '400 of 400 tiles revealed' })).toHaveAttribute(
    'src',
    expect.stringMatching(new RegExp('^' + photo.preview_url + '\\?reveal=400&run=')),
  );
  expect(dialog.getByLabelText('Category')).toHaveValue('2');
  await userEvent.clear(dialog.getByLabelText('Canonical answer'));
  await userEvent.type(dialog.getByLabelText('Canonical answer'), 'garden rose');
  await userEvent.click(dialog.getByRole('button', { name: 'Save reviewed labels' }));
  await dialog.findByText('Reviewed labels and source metadata saved.');
  const write = calls.find(
    ([path, options]) => path === root + 'images/photo-id/' && options?.method === 'POST',
  );
  expect(JSON.parse(String(write?.[1]?.body))).toEqual({
    canonical_answer: 'garden rose',
    accepted_synonyms: ['pink rose'],
    category: 2,
    source: 'manual',
    source_url: '',
    license: 'Pexels License',
    attribution: 'Pexels',
    photographer: '',
  });
});
it('bulk rejection accepts an optional reason and reports explicit outcomes', async () => {
  show('/moderation/administration/images');
  await userEvent.click(await screen.findByRole('checkbox', { name: 'Select rose' }));
  await userEvent.click(screen.getByRole('button', { name: /^Reject$/ }));
  const dialog = within(screen.getByRole('dialog'));
  expect(dialog.getByLabelText('Reason (optional)')).not.toBeRequired();
  await userEvent.type(dialog.getByLabelText('Reason (optional)'), 'Ambiguous flower');
  await userEvent.click(dialog.getByRole('button', { name: 'Confirm action' }));
  expect(await screen.findByRole('heading', { name: 'Action results' })).toBeInTheDocument();
  expect(screen.getByText('1 successful · 0 skipped · 0 failed')).toBeInTheDocument();
});
it('resumes an incomplete batch and allows label preparation without approval', async () => {
  show('/moderation/administration/imports/batch-id');
  expect(await screen.findByText('rose.jpg')).toBeInTheDocument();
  expect(
    screen.getByText(/Images remain pending until their labels are reviewed/),
  ).toBeInTheDocument();
  expect(screen.getByLabelText('Choose images')).toHaveAttribute('multiple');
  await userEvent.click(screen.getByRole('button', { name: 'Prepare labels' }));
  expect(screen.getByRole('dialog', { name: 'Image detail' })).toBeInTheDocument();
});
it('removes individual selections by ID, adds more files and uploads only retained duplicate filenames', async () => {
  show('/moderation/administration/imports/batch-id');
  const input = await screen.findByLabelText('Choose images');
  const first = new File(['one'], 'same.png', { type: 'image/png' });
  const second = new File(['second'], 'same.png', { type: 'image/png' });
  await userEvent.upload(input, [first, second]);
  expect(screen.getByText('2 files selected')).toBeInTheDocument();
  await userEvent.click(screen.getAllByRole('button', { name: 'Remove same.png' })[0]);
  expect(screen.getByText('1 files selected')).toBeInTheDocument();
  expect(URL.revokeObjectURL).toHaveBeenCalled();
  await userEvent.upload(input, first);
  expect(screen.getByText('2 files selected')).toBeInTheDocument();
  await userEvent.click(screen.getAllByRole('button', { name: 'Remove same.png' })[1]);
  await userEvent.upload(input, new File(['third'], 'more.png', { type: 'image/png' }));
  expect(screen.getByText('2 files selected')).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Upload selected images' }));
  await screen.findByText(/Upload complete/);
  const uploads = calls
    .filter(([path, options]) => path === root + 'imports/batch-id/' && options?.method === 'POST')
    .map(([, options]) => (options!.body as FormData).get('file') as File);
  expect(uploads).toHaveLength(2);
  expect(uploads[0].name).toBe('same.png');
  expect(uploads[0].size).toBe(second.size);
  expect(uploads[1].name).toBe('more.png');
  expect(screen.getByText('0 files selected')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Upload selected images' })).toBeDisabled();
});
it('clears all files without confirmation and can select the same file again', async () => {
  show('/moderation/administration/imports/batch-id');
  const input = await screen.findByLabelText('Choose images');
  const file = new File(['one'], 'one.png', { type: 'image/png' });
  await userEvent.upload(input, [file, new File(['two'], 'two.png', { type: 'image/png' })]);
  await userEvent.click(screen.getByRole('button', { name: 'Clear all' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.getByText('0 files selected')).toBeInTheDocument();
  await userEvent.upload(input, file);
  expect(screen.getByText('1 files selected')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Remove one.png' })).toBeInTheDocument();
});
it('passes explicitly supplied source metadata with each upload', async () => {
  show('/moderation/administration/imports/batch-id');
  await userEvent.upload(
    await screen.findByLabelText('Choose images'),
    new File(['one'], 'one.png', { type: 'image/png' }),
  );
  await userEvent.click(screen.getByText('Source metadata for these uploads (optional)'));
  await userEvent.selectOptions(screen.getByLabelText('Source type'), 'commons');
  await userEvent.type(screen.getByLabelText('License / usage rights'), 'CC BY-SA 4.0');
  await userEvent.type(screen.getByLabelText('Attribution / credit'), 'Verified credit');
  await userEvent.type(screen.getByLabelText('Creator / photographer (optional)'), 'Creator');
  await userEvent.type(
    screen.getByLabelText('Original source URL'),
    'https://commons.wikimedia.org/wiki/File:Example.jpg',
  );
  await userEvent.click(screen.getByRole('button', { name: 'Upload selected images' }));
  await screen.findByText(/Upload complete/);
  const request = calls.find(
    ([path, options]) => path === root + 'imports/batch-id/' && options?.method === 'POST',
  );
  const body = request?.[1]?.body as FormData;
  expect(body.get('source')).toBe('commons');
  expect(body.get('license')).toBe('CC BY-SA 4.0');
  expect(body.get('attribution')).toBe('Verified credit');
  expect(body.get('photographer')).toBe('Creator');
});
it('keeps import actions together and links directly to the correct library record', async () => {
  show('/moderation/administration/imports/batch-id');
  const link = await screen.findByRole('link', { name: 'Review in Image Library →' });
  expect(link).toHaveAttribute('href', '/moderation/administration/images?q=photo-id');
  await userEvent.click(link);
  await screen.findByRole('checkbox', { name: 'Select rose' });
  expect(calls.some(([path]) => path.includes('images/?q=photo-id'))).toBe(true);
});
it('edits source metadata separately without assuming Commons licenses', async () => {
  show('/moderation/administration/images');
  await userEvent.click(await screen.findByRole('button', { name: 'Review image' }));
  const dialog = within(screen.getByRole('dialog'));
  await userEvent.selectOptions(dialog.getByLabelText('Source type'), 'commons');
  await userEvent.clear(dialog.getByLabelText('License / usage rights'));
  await userEvent.type(dialog.getByLabelText('License / usage rights'), 'CC BY-SA 4.0');
  await userEvent.type(
    dialog.getByLabelText('Original source URL'),
    'https://commons.wikimedia.org/wiki/File:Example.jpg',
  );
  await userEvent.type(dialog.getByLabelText('Creator / photographer'), 'Verified creator');
  await userEvent.click(dialog.getByRole('button', { name: 'Save reviewed labels' }));
  await dialog.findByText('Reviewed labels and source metadata saved.');
  expect(dialog.getByLabelText('License / usage rights')).toHaveValue('CC BY-SA 4.0');
  const request = calls.find(
    ([path, options]) => path === root + 'images/photo-id/' && options?.method === 'POST',
  );
  expect(JSON.parse(String(request?.[1]?.body))).toMatchObject({
    source: 'commons',
    license: 'CC BY-SA 4.0',
    photographer: 'Verified creator',
    canonical_answer: 'rose',
  });
});
it('rejects a pending image immediately and refreshes the badge without a confirmation', async () => {
  show('/moderation/administration/images');
  const reject = await screen.findByRole('button', { name: 'Reject pending image' });
  const approve = within(reject.parentElement!).getByRole('button', {
    name: 'Approve',
  });
  expect(approve.nextElementSibling).toBe(reject);
  expect(reject).toHaveTextContent('Reject');
  expect(reject).toHaveClass('mod-button', 'subtle');
  expect(approve).toHaveClass('mod-button', 'subtle');
  await userEvent.click(reject);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  await screen.findByText('Pending image rejected.');
  expect(screen.queryByRole('button', { name: 'Reject pending image' })).not.toBeInTheDocument();
  expect(screen.getByText('rejected', { selector: 'span' })).toBeInTheDocument();
  const request = calls.find(([path]) => path === root + 'images/review/');
  expect(JSON.parse(String(request?.[1]?.body))).toEqual({
    ids: ['photo-id'],
    operation: 'reject',
  });
});
it.each([
  ['approve', 1],
  ['approve', 2],
  ['reject', 1],
  ['reject', 2],
] as const)(
  'recovers page five after %s removes %s pending images and preserves URL filters',
  async (operation, removed) => {
    paginateImages = true;
    images = Array.from({ length: 96 + removed }, (_, index) => ({
      ...photo,
      id: 'image-' + index,
    }));
    show('/moderation/administration/images?status=pending&q=rose&sort=oldest&page=5');
    await screen.findByText('Page 5 of 5');
    if (operation === 'reject' && removed === 1) {
      await userEvent.click(screen.getByRole('button', { name: 'Reject pending image' }));
    } else {
      for (const checkbox of screen.getAllByRole('checkbox', { name: 'Select rose' }))
        await userEvent.click(checkbox);
      await userEvent.click(
        within(screen.getByText(`${removed} selected`).parentElement!).getByRole('button', {
          name: operation === 'approve' ? 'Approve' : 'Reject',
        }),
      );
      await userEvent.click(screen.getByRole('button', { name: 'Confirm action' }));
    }
    await screen.findByText('Page 4 of 4');
    await waitFor(() =>
      expect(screen.getByLabelText('Pagination route')).toHaveTextContent(
        'status=pending&q=rose&sort=oldest&page=4',
      ),
    );
    expect(calls.filter(([path]) => path.startsWith(root + 'images/?'))).toHaveLength(2);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  },
);
it('preserves approval confirmation and submits the selected image', async () => {
  show('/moderation/administration/images');
  const reject = await screen.findByRole('button', { name: 'Reject pending image' });
  await userEvent.click(within(reject.parentElement!).getByRole('button', { name: 'Approve' }));
  const dialog = within(screen.getByRole('dialog', { name: 'Approve 1 image?' }));
  expect(calls.some(([path]) => path === root + 'images/review/')).toBe(false);
  await userEvent.click(dialog.getByRole('button', { name: 'Confirm action' }));
  await screen.findByRole('heading', { name: 'Action results' });
  const request = calls.find(([path]) => path === root + 'images/review/');
  expect(JSON.parse(String(request?.[1]?.body))).toEqual({
    ids: ['photo-id'],
    operation: 'approve',
    reason: '',
  });
});
it('recovers a stale URL and keeps the page when a rejection leaves it valid', async () => {
  paginateImages = true;
  images = Array.from({ length: 26 }, (_, index) => ({ ...photo, id: 'image-' + index }));
  show('/moderation/administration/images?status=pending&q=rose&page=999');
  await screen.findByText('Page 2 of 2');
  await waitFor(() =>
    expect(screen.getByLabelText('Pagination route')).toHaveTextContent('page=2'),
  );
  expect(calls.filter(([path]) => path.startsWith(root + 'images/?'))).toHaveLength(1);
  await userEvent.click(screen.getAllByRole('button', { name: 'Reject pending image' })[0]);
  await screen.findByText('Pending image rejected.');
  await waitFor(() =>
    expect(screen.getAllByRole('button', { name: 'Reject pending image' })).toHaveLength(1),
  );
  expect(screen.getByText('Page 2 of 2')).toBeInTheDocument();
  expect(screen.getByLabelText('Pagination route')).toHaveTextContent('page=2');
});
it('shows the empty filtered library without pagination after its final rejection', async () => {
  paginateImages = true;
  show('/moderation/administration/images?status=pending&q=rose&page=1');
  await userEvent.click(await screen.findByRole('button', { name: 'Reject pending image' }));
  await screen.findByText('No images match these filters.');
  expect(screen.queryByRole('navigation', { name: 'Pagination' })).not.toBeInTheDocument();
  expect(screen.getByLabelText('Pagination route')).toHaveTextContent(
    'status=pending&q=rose&page=1',
  );
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});
it.each(['Approve', 'Reject', 'Retire', 'Restore'])(
  '%s confirmation uses singular wording for one image and plural for multiple images',
  async (operation) => {
    images = [photo, { ...photo, id: 'second-photo', canonical_answer: 'tiger' }];
    show('/moderation/administration/images');
    await userEvent.click(await screen.findByRole('checkbox', { name: 'Select rose' }));
    await userEvent.click(
      within(screen.getByText('1 selected').parentElement!).getByRole('button', {
        name: operation,
      }),
    );
    const single = within(screen.getByRole('dialog', { name: `${operation} 1 image?` }));
    expect(single.getByText(/The selected image will be validated/)).toBeInTheDocument();
    expect(single.queryByText(/skipped images/)).not.toBeInTheDocument();
    await userEvent.click(single.getByRole('button', { name: 'Cancel' }));
    await userEvent.click(screen.getByRole('checkbox', { name: 'Select tiger' }));
    await userEvent.click(
      within(screen.getByText('2 selected').parentElement!).getByRole('button', {
        name: operation,
      }),
    );
    const multiple = within(screen.getByRole('dialog', { name: `${operation} 2 images?` }));
    expect(multiple.getByText(/Every selected image will be validated/)).toBeInTheDocument();
  },
);
it.each(['approved', 'rejected', 'retired'])(
  'does not offer the shortcut for %s images',
  async (status) => {
    images = [{ ...photo, status }];
    show('/moderation/administration/images');
    await screen.findByRole('checkbox', { name: 'Select rose' });
    expect(screen.queryByRole('button', { name: 'Reject pending image' })).not.toBeInTheDocument();
  },
);
it('shows a failed rejection without dropping the pending image', async () => {
  rejectError = 'Only pending images can be rejected.';
  show('/moderation/administration/images');
  await userEvent.click(await screen.findByRole('button', { name: 'Reject pending image' }));
  await screen.findByText(rejectError);
  expect(screen.getByRole('button', { name: 'Reject pending image' })).toBeEnabled();
});
it('announcement body renders as text and editing remains admin only', async () => {
  notice = {
    title: 'Team update',
    body: '<script>unsafe()</script>',
    published: true,
    expires_at: null,
    version: 1,
  };
  user = { ...user, administrator: false };
  show('/moderation');
  expect(await screen.findByText('<script>unsafe()</script>')).toBeInTheDocument();
  expect(document.querySelector('script')).toBeNull();
  expect(screen.queryByRole('button', { name: 'Edit announcement' })).not.toBeInTheDocument();
});
it('shows admin player controls and accepts an optional Elo reason', async () => {
  show('/moderation/players/ordinary-id');
  await userEvent.click(await screen.findByRole('button', { name: 'Override Elo' }));
  const dialog = within(screen.getByRole('dialog'));
  expect(dialog.getByLabelText('Reason (optional)')).not.toBeRequired();
  fireEvent.change(dialog.getByLabelText('New Elo'), { target: { value: '1200' } });
  await userEvent.type(dialog.getByLabelText('Reason (optional)'), 'Correction');
  await userEvent.click(dialog.getByRole('button', { name: 'Confirm change' }));
  await screen.findByText('Administrator changes saved.');
  expect(
    calls.some(
      ([path, options]) =>
        path === root + 'players/ordinary-id/' && String(options?.body).includes('1200'),
    ),
  ).toBe(true);
});
it.each(['pro', 'master', 'legend'])(
  'renders the fixed %s honorary badge before the username',
  (title) => {
    const { container } = render(<PlayerIdentity username="PixelHunter" title={title} />);
    expect(screen.getByText(title.toUpperCase())).toHaveClass('honorary-title');
    expect(container.querySelector('.player-identity')?.firstElementChild?.textContent).toBe(
      title.toUpperCase(),
    );
  },
);
it('does not render an arbitrary or competitive title badge', () => {
  const { container } = render(<PlayerIdentity username="PixelHunter" title="diamond" />);
  expect(container.querySelector('.honorary-title')).toBeNull();
  expect(screen.getByText('PixelHunter')).toBeInTheDocument();
});

it('places promotion above a compact staff-only list and protects administrators', async () => {
  show('/moderation/administration/staff');
  const promotion = await screen.findByRole('region', { name: 'Promote a Player' });
  const directory = screen.getByRole('region', { name: 'Current Staff' });
  expect(
    promotion.compareDocumentPosition(directory) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  const list = await within(directory).findByRole('list', { name: 'Current staff' });
  const rows = within(list).getAllByRole('listitem');
  expect(rows).toHaveLength(3);
  expect(within(list).queryByText('imagehunter')).not.toBeInTheDocument();
  for (const username of ['administrator', 'second_admin']) {
    const row = rows.find((row) => within(row).queryByText(username));
    expect(row).toBeDefined();
    expect(
      within(row!).queryByRole('button', { name: 'Remove moderator access' }),
    ).not.toBeInTheDocument();
  }
  expect(within(list).getAllByRole('button', { name: 'Remove moderator access' })).toHaveLength(1);
  expect(screen.getByLabelText('Staff role')).toHaveValue('all');
});

it('retains moderator demotion confirmation from the staff list', async () => {
  show('/moderation/administration/staff');
  await userEvent.click(await screen.findByRole('button', { name: 'Remove moderator access' }));
  expect(within(screen.getByRole('dialog')).getByText(/mod-id/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Confirm role change' }));
  await screen.findByText('Moderator access removed.');
  const write = calls.find(
    ([path, options]) => path === root + 'players/mod-id/' && options?.method === 'POST',
  );
  expect(JSON.parse(String(write?.[1]?.body))).toEqual({ operation: 'moderator', enabled: false });
});

it('uses consistent approved wording while explaining the overview image count', async () => {
  show('/moderation/administration');
  const summary = await screen.findByRole('region', { name: 'Summary metrics' });
  expect(within(summary).getByText('Approved images')).toBeInTheDocument();
  expect(within(summary).getByText(/excludes retired images/)).toBeInTheDocument();
  expect(within(summary).queryByText(/Playable|Ready to Play/)).not.toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Needs Attention' })).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Recent staff activity' })).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'System status' })).toBeInTheDocument();
  expect(within(summary).getByText('Pending player review')).toBeInTheDocument();
  expect(within(summary).getByText('Pending', { exact: true })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: '2 pending player reviews →' })).toHaveAttribute(
    'href',
    '/moderation/administration/images?tab=submissions',
  );
  expect(screen.getByRole('link', { name: '3 pending import reviews →' })).toHaveAttribute(
    'href',
    '/moderation/administration/images?status=pending',
  );
});

it('labels pending library entries as Pending and preserves the API filter value', async () => {
  show('/moderation/administration/images');
  await screen.findByRole('checkbox', { name: 'Select rose' });
  expect(screen.getByText('Pending', { selector: 'span' })).toBeInTheDocument();
  await userEvent.selectOptions(screen.getByLabelText('Status'), 'pending');
  await userEvent.click(screen.getByRole('button', { name: 'Search' }));
  expect(
    calls.some(([path]) => path.startsWith(root + 'images/?') && path.includes('status=pending')),
  ).toBe(true);
});
