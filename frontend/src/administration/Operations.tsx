import { useState } from 'react';
import type { Page } from '../api';
import { Heading, Loading, Pager } from '../moderation/components';
import { useData } from '../moderation/useData';
import { adminRoot, type AuditEntry, type HealthCheck } from './api';
import { ActivityList, HealthList } from './Overview';

export function AuditLog() {
  const [filters, setFilters] = useState({ q: '', action: '', target_type: '', page: '1' });
  const { data, error, reload } = useData<Page<AuditEntry>>(
    `${adminRoot}audit/?${new URLSearchParams(filters)}`,
  );
  return (
    <>
      <Heading title="Audit Log" detail="Accountable actions. A permanent record." />
      <form
        className="admin-filters"
        onSubmit={(e) => {
          e.preventDefault();
          const form = new FormData(e.currentTarget);
          setFilters({
            q: String(form.get('q')),
            action: String(form.get('action')),
            target_type: String(form.get('target_type')),
            page: '1',
          });
        }}
      >
        <label>
          Actor, target or reason
          <input name="q" />
        </label>
        <label>
          Action
          <input name="action" placeholder="image_approve" />
        </label>
        <label>
          Target type
          <select name="target_type">
            <option value="">All targets</option>
            {['player', 'image', 'import_batch', 'announcement'].map((x) => (
              <option key={x}>{x}</option>
            ))}
          </select>
        </label>
        <button className="mod-button">Filter log</button>
      </form>
      {!data ? (
        <Loading error={error} retry={reload} />
      ) : (
        <section className="mod-card">
          <p className="mod-muted">{data.count} recorded actions · read-only</p>
          <ActivityList entries={data.results} />
          {!data.count && <p className="mod-empty">No audit records match.</p>}
          <Pager
            page={Number(filters.page)}
            next={data.next}
            previous={data.previous}
            change={(value) => setFilters({ ...filters, page: String(value) })}
          />
        </section>
      )}
    </>
  );
}
export function SystemHealth() {
  const { data, error, reload } = useData<{ checks: HealthCheck[] }>(adminRoot + 'health/');
  return (
    <>
      <Heading
        title="System Health"
        detail="Bounded service checks. Operational visibility without dangerous controls."
      />
      {!data ? (
        <Loading error={error} retry={reload} />
      ) : (
        <section className="mod-card">
          <HealthList checks={data.checks} />
          <p className="mod-muted">
            Storage is checked by reading a private hosted image. Local in-memory services and
            unavailable error collection are explicitly marked Not Configured. Service details and
            secrets are never returned.
          </p>
          <button className="mod-button subtle" onClick={reload}>
            Run checks again
          </button>
        </section>
      )}
    </>
  );
}
