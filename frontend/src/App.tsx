import { Route, Routes } from 'react-router-dom';
import { Layout } from './components/Layout';
import { PartyEntry, PartyRoute } from './pages/Party';
import { RankedEntry, RankedRoute } from './pages/Ranked';
import { Leaderboards } from './pages/RankedPublic';
import { Home } from './pages/Home';
import { Singleplayer } from './pages/Singleplayer';
import { Mode } from './pages/Mode';
import { AuthPage } from './pages/Auth';
import { Profile, Settings } from './pages/Account';
import { Library } from './pages/Library';
import { Submit } from './pages/Submit';
import { About, NotFound } from './pages/Info';
import { ModerationLayout } from './moderation/Layout';
import { ModerationHome } from './moderation/Home';
import { ModerationPlayers } from './moderation/Players';
import { ModerationPlayer } from './moderation/Player';
import { ModerationInbox } from './moderation/Inbox';

export function App() {
  return (
    <Routes>
      <Route path="moderation" element={<ModerationLayout />}>
        <Route index element={<ModerationHome />} />
        <Route path="players" element={<ModerationPlayers />} />
        <Route path="players/:id" element={<ModerationPlayer />} />
        <Route path="reports" element={<ModerationInbox key="reports" />} />
        <Route path="appeals" element={<ModerationInbox key="appeals" appeals />} />
        <Route path="*" element={<NotFound />} />
      </Route>
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="party/new" element={<PartyEntry key="create" create />} />
        <Route path="party/join" element={<PartyEntry key="join" />} />
        <Route path="party/:code" element={<PartyRoute />} />
        <Route path="ranked" element={<RankedEntry />} />
        <Route path="ranked/:id" element={<RankedRoute />} />
        <Route path="players/:username" element={<Profile />} />
        <Route path="singleplayer" element={<Singleplayer />} />
        <Route path="modes/:modeId" element={<Mode />} />
        <Route path="login" element={<AuthPage key="login" />} />
        <Route path="register" element={<AuthPage key="register" register />} />
        <Route path="profile" element={<Profile />} />
        <Route path="settings/account" element={<Settings />} />
        <Route path="settings" element={<Settings />} />
        <Route path="library" element={<Library />} />
        <Route path="submit" element={<Submit />} />
        <Route path="leaderboards" element={<Leaderboards />} />
        <Route path="about" element={<About />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
