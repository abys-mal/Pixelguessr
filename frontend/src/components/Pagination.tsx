import type { Page } from '../api';

export type PaginationInfo = Pick<Page<unknown>, 'page' | 'total_pages' | 'next' | 'previous'>;

export function PageNavigation({
  pagination,
  onPage,
  className = 'ranked-pagination',
  buttonClassName = 'button secondary',
  label = 'Page navigation',
}: {
  pagination: PaginationInfo;
  onPage: (page: number) => void;
  className?: string;
  buttonClassName?: string;
  label?: string;
}) {
  const { page, total_pages, next, previous } = pagination;
  if (!total_pages) return null;
  return (
    <nav className={className} aria-label={label}>
      <button className={buttonClassName} disabled={!previous} onClick={() => onPage(page - 1)}>
        Previous
      </button>
      <span>
        Page {page} of {total_pages}
      </span>
      <button className={buttonClassName} disabled={!next} onClick={() => onPage(page + 1)}>
        Next
      </button>
    </nav>
  );
}
