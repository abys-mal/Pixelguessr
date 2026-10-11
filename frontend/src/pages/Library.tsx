import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import type { Category, Page } from '../api';
import { EmptyState, PageHeading, StatusMessage } from '../components/ui';

export function Library() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [count, setCount] = useState<number | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    void Promise.all([
      api<Category[]>('/api/library/categories/'),
      api<Page<{ id: string }>>('/api/library/catalog/'),
    ])
      .then(([categories, catalog]) => {
        setCategories(categories);
        setCount(catalog.count);
      })
      .catch((error: Error) => setError(error.message));
  }, []);
  return (
    <>
      <PageHeading eyebrow="CURATED, NOT CROWDSOURCED" title="A world of little mysteries.">
        Licensed, original, and AI-generated images, reviewed by people before publication.
      </PageHeading>
      {error ? (
        <StatusMessage error>{error}</StatusMessage>
      ) : count === null ? (
        <StatusMessage>Loading library…</StatusMessage>
      ) : (
        <>
          <div className="category-list" aria-label="Image categories">
            {categories.map((category) => (
              <span key={category.id}>{category.name}</span>
            ))}
          </div>
          <EmptyState
            title={
              count
                ? `${count} approved ${count === 1 ? 'image' : 'images'}`
                : 'The collection starts here.'
            }
          >
            {count
              ? 'Approved images are ready for the future game. Browsing and reveals arrive in Phase 2.'
              : 'No images have been published yet. Help build the first collection.'}
          </EmptyState>
        </>
      )}
      <div className="action-row">
        <Link className="button" to="/submit">
          Submit an image ↗
        </Link>
        <p className="muted">Every submission needs staff approval.</p>
      </div>
    </>
  );
}
