import { Link, Navigate, useParams } from 'react-router-dom';
import { PageHeading } from '../components/ui';
import { modes } from '../modes';

export function Mode() {
  const { modeId } = useParams();
  const mode = modes.find((item) => item.id === modeId);
  if (!mode)
    return (
      <PageHeading eyebrow="NOT FOUND" title="That mode is off the grid.">
        <Link to="/">Back to the homepage</Link>
      </PageHeading>
    );
  return (
    <Navigate
      to={mode.id === 'ranked' ? '/ranked' : mode.id === 'party' ? '/party/new' : '/singleplayer'}
      replace
    />
  );
}
