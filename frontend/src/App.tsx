import { Route, Routes } from 'react-router-dom';
import { Layout } from './components/Layout';
import { PartyEntry, PartyRoute } from './pages/Party';
import { Home } from './pages/Home';
import { Singleplayer } from './pages/Singleplayer';
import { Mode } from './pages/Mode';
import { AuthPage } from './pages/Auth';
import { Profile, Settings } from './pages/Account';
import { Library } from './pages/Library';
import { Submit } from './pages/Submit';
import { About, Leaderboards, NotFound } from './pages/Info';

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="party/new" element={<PartyEntry key="create" create />} />
        <Route path="party/join" element={<PartyEntry key="join" />} />
        <Route path="party/:code" element={<PartyRoute />} />
        <Route path="singleplayer" element={<Singleplayer />} />
        <Route path="modes/:modeId" element={<Mode />} />
        <Route path="login" element={<AuthPage key="login" />} />
        <Route path="register" element={<AuthPage key="register" register />} />
        <Route path="profile" element={<Profile />} />
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
