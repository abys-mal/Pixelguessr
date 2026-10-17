export function PlayerIdentity({ username, title }: { username: string; title?: string | null }) {
  const value = title?.toLowerCase();
  return (
    <span className="player-identity">
      {value && ['pro', 'master', 'legend'].includes(value) && (
        <span className={`honorary-title honorary-${value}`}>{value.toUpperCase()}</span>
      )}
      <span>{username}</span>
    </span>
  );
}
