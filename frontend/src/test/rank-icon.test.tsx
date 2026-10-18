import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { RankIcon } from '../components/RankIcon';

it.each(['Bronze', 'Silver', 'Gold', 'Diamond'])('renders the accessible %s SVG', (tier) => {
  render(<RankIcon tier={tier} />);
  const icon = screen.getByRole('img', { name: `${tier} rank` });
  expect(icon.tagName.toLowerCase()).toBe('svg');
  expect(icon).toHaveClass(`rank-icon-${tier.toLowerCase()}`);
  expect(icon.querySelector('title')).toHaveTextContent(tier);
});
it.each([undefined, null, '', 'Unknown', 'Pro', 'Master', 'Legend', 'constructor', 'toString'])(
  'does not invent a competitive icon for %s',
  (tier) => {
    const { container } = render(<RankIcon tier={tier} />);
    expect(container).toBeEmptyDOMElement();
  },
);
it('avoids duplicating the accessible name when paired with visible tier text', () => {
  render(
    <span>
      <RankIcon tier="Diamond" decorative />
      Diamond
    </span>,
  );
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  expect(screen.getByText('Diamond').querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
});
