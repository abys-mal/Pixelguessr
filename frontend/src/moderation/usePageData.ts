import { useCallback, useEffect, useRef, useState } from 'react';
import { api, type Page } from '../api';

export function usePageData<T extends Page<unknown>>(
  url: string,
  onPage: (page: number) => void,
  load?: () => Promise<T>,
) {
  const callbacks = useRef({ onPage, load });
  useEffect(() => {
    callbacks.current = { onPage, load };
  }, [onPage, load]);
  const [result, setResult] = useState<{
    url: string;
    requested: string;
    data: T | null;
    error: string;
  }>({ url, requested: url, data: null, error: '' });
  const [revision, setRevision] = useState(0);
  const completed = useRef<{ url: string; revision: number } | null>(null);
  useEffect(() => {
    // A corrected URL already has its response; canonicalizing state must not refetch it.
    if (completed.current?.url === url && completed.current.revision === revision) return;
    let live = true;
    const controller = new AbortController();
    const request = callbacks.current.load?.() ?? api<T>(url, { signal: controller.signal });
    void request.then(
      (data) => {
        if (!live) return;
        const [, query = ''] = url.split('?');
        const params = new URLSearchParams(query);
        const corrected = data.page != null && String(data.page) !== (params.get('page') ?? '1');
        const resolved = !corrected
          ? url
          : params.has('page')
            ? url.replace(/([?&]page=)[^&]*/, `$1${data.page}`)
            : `${url}${url.includes('?') ? '&' : '?'}page=${data.page}`;
        completed.current = { url: resolved, revision };
        setResult({ url: resolved, requested: url, data, error: '' });
        if (corrected) callbacks.current.onPage(data.page);
      },
      (error: Error) => {
        if (live) setResult({ url, requested: url, data: null, error: error.message });
      },
    );
    return () => {
      live = false;
      controller.abort();
    };
  }, [url, revision]);
  const reload = useCallback(() => setRevision((value) => value + 1), []);
  const current = result.url === url || result.requested === url;
  return {
    data: current ? result.data : null,
    error: current ? result.error : '',
    reload,
  };
}
