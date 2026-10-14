import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';

export function useData<T>(url: string) {
  const [result, setResult] = useState<{ url: string; data: T | null; error: string }>({
    url,
    data: null,
    error: '',
  });
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let live = true;
    const controller = new AbortController();
    void api<T>(url, { signal: controller.signal }).then(
      (data) => {
        if (live) setResult({ url, data, error: '' });
      },
      (error: Error) => {
        if (live) setResult({ url, data: null, error: error.message });
      },
    );
    return () => {
      live = false;
      controller.abort();
    };
  }, [url, revision]);
  const reload = useCallback(() => setRevision((value) => value + 1), []);
  return {
    data: result.url === url ? result.data : null,
    error: result.url === url ? result.error : '',
    reload,
  };
}
