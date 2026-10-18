import './rank-icon.css';

const ranks: Record<string, { name: string; color: string }> = {
  bronze: { name: 'Bronze', color: '#ce956d' },
  silver: { name: 'Silver', color: '#cad8e7' },
  gold: { name: 'Gold', color: '#f3cc72' },
  diamond: { name: 'Diamond', color: '#7bd9ff' },
};

export function RankIcon({
  tier,
  decorative = false,
}: {
  tier?: string | null;
  decorative?: boolean;
}) {
  const key = tier?.toLowerCase() ?? '';
  const rank = Object.hasOwn(ranks, key) ? ranks[key] : undefined;
  if (!rank) return null;
  return (
    <svg
      className={`rank-icon rank-icon-${key}`}
      viewBox="0 0 32 32"
      width="24"
      height="24"
      fill="none"
      stroke={rank.color}
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      role={decorative ? undefined : 'img'}
      aria-hidden={decorative || undefined}
      aria-label={decorative ? undefined : `${rank.name} rank`}
    >
      {!decorative && <title>{rank.name}</title>}
      {key === 'diamond' ? (
        <>
          <path fill={rank.color} fillOpacity=".13" d="m3 12 6-8h14l6 8-13 17Z" />
          <path d="M3 12h26M9 4l7 25L23 4M9 4l7 8 7-8" />
        </>
      ) : key === 'gold' ? (
        <>
          <path fill={rank.color} fillOpacity=".13" d="m9 19-3 10 10-4 10 4-3-10" />
          <circle cx="16" cy="13" r="10" fill={rank.color} fillOpacity=".13" />
          <path d="m16 6 2 4.5 5 .5-3.7 3.3 1.1 4.7-4.4-2.5-4.4 2.5 1.1-4.7L9 11l5-.5Z" />
        </>
      ) : (
        <>
          <path
            fill={rank.color}
            fillOpacity=".13"
            d="M5 5 16 2l11 3v11c0 6-7 11-11 14C12 27 5 22 5 16Z"
          />
          <path d="m10 14 6 5 6-5" />
          {key === 'silver' && (
            <>
              <path d="m10 9 6 5 6-5M9 5v10c0 4 4 8 7 10 3-2 7-6 7-10V5" />
            </>
          )}
        </>
      )}
    </svg>
  );
}
