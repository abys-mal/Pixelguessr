import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { beforeEach, expect, it, vi } from 'vitest';
import { api, type Page } from '../api';
import { PageNavigation } from '../components/Pagination';
import { Pager } from '../moderation/components';
import { usePageData } from '../moderation/usePageData';

vi.mock('../api', async (original) => ({ ...(await original<object>()), api: vi.fn() }));
const response = (page = 5, total = 5): Page<{ id: string }> => ({
  page,
  total_pages: total,
  page_size: 24,
  count: total ? (total - 1) * 24 + 1 : 0,
  next: page < total ? '?page=' + (page + 1) : null,
  previous: page > 1 ? '?page=' + (page - 1) : null,
  results: total ? [{ id: 'image' }] : [],
});
beforeEach(() => vi.mocked(api).mockReset());

it('shares accurate labels, enabled states and page callbacks across styles', () => {
  const change = vi.fn();
  const view = render(<Pager pagination={response(3, 8)} change={change} />);
  expect(screen.getByText('Page 3 of 8')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Next' }));
  expect(change).toHaveBeenLastCalledWith(4);
  fireEvent.click(screen.getByRole('button', { name: 'Previous' }));
  expect(change).toHaveBeenLastCalledWith(2);
  view.rerender(<PageNavigation pagination={response(1, 1)} onPage={change} />);
  expect(screen.getByText('Page 1 of 1')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
  view.rerender(<PageNavigation pagination={response(1, 0)} onPage={change} />);
  expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
});

function useList(start = 5) {
  const [page, setPage] = useState(start);
  const state = usePageData<Page<{ id: string }>>(
    `/api/items/?q=red%20fox&status=pending&sort=oldest&page=${page}`,
    setPage,
  );
  return { ...state, page, setPage };
}

it('recovers a disappearing page without errors or a duplicate fetch, preserving filters', async () => {
  vi.mocked(api).mockResolvedValueOnce(response()).mockResolvedValueOnce(response(4, 4));
  const { result } = renderHook(() => useList());
  await waitFor(() => expect(result.current.data?.page).toBe(5));
  act(() => result.current.reload());
  await waitFor(() => expect(result.current.page).toBe(4));
  expect(result.current.data?.page).toBe(4);
  expect(result.current.error).toBe('');
  expect(api).toHaveBeenCalledTimes(2);
  expect(vi.mocked(api).mock.calls[1][0]).toBe(
    '/api/items/?q=red%20fox&status=pending&sort=oldest&page=5',
  );
  vi.mocked(api).mockResolvedValueOnce(response(4, 4));
  act(() => result.current.reload());
  await waitFor(() => expect(api).toHaveBeenCalledTimes(3));
  expect(vi.mocked(api).mock.calls[2][0]).toBe(
    '/api/items/?q=red%20fox&status=pending&sort=oldest&page=4',
  );
});

it('keeps a valid current page and recovers empty results to page one', async () => {
  vi.mocked(api)
    .mockResolvedValueOnce(response(3, 5))
    .mockResolvedValueOnce(response(3, 4))
    .mockResolvedValueOnce(response(1, 0));
  const { result } = renderHook(() => useList(3));
  await waitFor(() => expect(result.current.data?.total_pages).toBe(5));
  act(() => result.current.reload());
  await waitFor(() => expect(result.current.data?.total_pages).toBe(4));
  expect(result.current.page).toBe(3);
  act(() => result.current.reload());
  await waitFor(() => expect(result.current.page).toBe(1));
  expect(result.current.data?.results).toEqual([]);
  expect(api).toHaveBeenCalledTimes(3);
});

it('retains real API errors and ignores a stale response after navigation', async () => {
  let complete: (value: Page<{ id: string }>) => void = () => {};
  vi.mocked(api).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        complete = resolve;
      }),
  );
  const { result } = renderHook(() => useList());
  vi.mocked(api).mockRejectedValueOnce(new Error('Database unavailable.'));
  act(() => result.current.setPage(2));
  await waitFor(() => expect(result.current.error).toBe('Database unavailable.'));
  act(() => complete(response(4, 4)));
  expect(result.current.page).toBe(2);
  expect(result.current.error).toBe('Database unavailable.');
  expect(api).toHaveBeenCalledTimes(2);
});
