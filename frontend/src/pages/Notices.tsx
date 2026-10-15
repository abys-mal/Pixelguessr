import { Link } from 'react-router-dom';
import { useAuth } from '../auth/context';
import { AccountNotices } from '../components/AccountNotices';
import { PageHeading, SignInPrompt, StatusMessage } from '../components/ui';

export function Notices() {
  const { user, loading } = useAuth();
  if (loading) return <StatusMessage>Loading account…</StatusMessage>;
  if (!user) return <SignInPrompt feature="view your account notices" />;
  return (
    <>
      <PageHeading eyebrow="YOUR ACCOUNT" title="Account notices">
        Review sanctions, acknowledge warnings, and follow your appeals.
      </PageHeading>
      <Link to="/settings/account">← Account settings</Link>
      <AccountNotices />
    </>
  );
}
