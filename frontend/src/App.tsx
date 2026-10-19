import { Route, Routes } from 'react-router-dom';
import { Layout } from './components/Layout';
import { PartyEntry, PartyRoute } from './pages/Party';
import { RankedEntry, RankedRoute } from './pages/Ranked';
import { Leaderboards } from './pages/RankedPublic';
import { Home } from './pages/Home';
import { Singleplayer } from './pages/Singleplayer';
import { Mode } from './pages/Mode';
import { AccountClosure, AccountClosed } from './pages/AccountClosure';
import { AuthPage } from './pages/Auth';
import { Profile, Settings } from './pages/Account';
import { Notices } from './pages/Notices';
import { Library } from './pages/Library';
import { Submit } from './pages/Submit';
import { Contributions } from './pages/Contributions';
import { About, NotFound } from './pages/Info';
import { Privacy, Terms } from './pages/Legal';
import { ModerationLayout } from './moderation/Layout';
import { ModerationHome } from './moderation/Home';
import { ModerationPlayers } from './moderation/Players';
import { ModerationPlayer } from './moderation/Player';
import { ModerationInbox } from './moderation/Inbox';
import { AdministratorGate, AdministrationOverview } from './administration/Overview';
import { ImageLibrary } from './administration/Images';
import { ImageImports } from './administration/Imports';
import { StaffRoles } from './administration/Staff';
import { AuditLog, SystemHealth } from './administration/Operations';

export function App() {
  return (
    <Routes>
      <Route path="moderation" element={<ModerationLayout />}>
        <Route path="administration" element={<AdministratorGate />}>
          <Route index element={<AdministrationOverview />} />
          <Route path="images" element={<ImageLibrary />} />
          <Route path="imports" element={<ImageImports key="list" />} />
          <Route path="imports/:id" element={<ImageImports key="detail" />} />
          <Route path="staff" element={<StaffRoles />} />
          <Route path="audit" element={<AuditLog />} />
          <Route path="health" element={<SystemHealth />} />
        </Route>
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
        <Route path="settings/close-account" element={<AccountClosure />} />
        <Route path="account-closed" element={<AccountClosed />} />
        <Route path="settings/account" element={<Settings />} />
        <Route path="settings" element={<Settings />} />
        <Route path="account-notices" element={<Notices />} />
        <Route path="library" element={<Library />} />
        <Route path="contributions" element={<Contributions />} />
        <Route path="submit" element={<Submit />} />
        <Route path="leaderboards" element={<Leaderboards />} />
        <Route path="about" element={<About />} />
        <Route path="terms" element={<Terms />} />
        <Route path="privacy" element={<Privacy />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
