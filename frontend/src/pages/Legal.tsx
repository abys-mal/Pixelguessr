import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { PageHeading } from '../components/ui';
import './legal.css';

function LegalPage({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="legal-page">
      <PageHeading eyebrow="PIXELGUESSR" title={title} />
      <article className="panel prose legal-document">
        <p className="legal-draft">
          <strong>Initial draft — operator and legal review required before publication.</strong>
        </p>
        <dl className="legal-dates">
          <div>
            <dt>Effective date</dt>
            <dd>Pending operator confirmation</dd>
          </div>
          <div>
            <dt>Draft prepared</dt>
            <dd>
              <time dateTime="2026-10-18">October 18, 2026</time>
            </dd>
          </div>
        </dl>
        {children}
        <h2>Operator review and updates</h2>
        <p>
          Operator: <strong>[Legal name and jurisdiction to be supplied]</strong>.
        </p>
        <p>
          Contact: <strong>[Support and privacy contact address or route to be supplied]</strong>.
        </p>
        <p>
          The operator must confirm these details and the effective date before adopting this draft.
          Changes to this document will be published here with an updated effective date.
        </p>
      </article>
    </div>
  );
}

export function Terms() {
  return (
    <LegalPage title="Terms of Service">
      <h2>Playing Pixelguessr</h2>
      <p>
        Pixelguessr is an image-guessing game with Singleplayer, private Parties, and Ranked Duels.
        Guests can use the guest-compatible modes; accounts are required for ranked play and image
        contributions. Use the service lawfully and follow the rules shown for each mode.
      </p>
      <h2>Your account</h2>
      <p>
        Provide accurate account information, keep your password private, and take responsibility
        for activity through your account. Do not impersonate others or choose abusive usernames or
        display names. Keep access to the email address you register.
      </p>
      <p>
        <strong>Operator review:</strong> confirm eligibility and age requirements before public
        launch.
      </p>
      <h2>Fair play and community conduct</h2>
      <p>
        Do not cheat, automate play to gain an unfair advantage, exploit bugs, interfere with
        matches, evade account restrictions, harass players, or misuse reports. Report concerns
        honestly. Do not upload unlawful, hateful, explicitly sexual, infringing, or otherwise
        harmful content.
      </p>
      <h2>Multiplayer and ranked play</h2>
      <p>
        The server determines guesses, deadlines, scores, and ratings. Ranked matchmaking uses Elo
        and the published duel rules; leaving an active duel or failing to reconnect within the
        applicable grace period can count as a loss. Connection and service problems may affect
        play. Ratings are game statistics, not a promise of access, prizes, or competitive standing.
      </p>
      <h2>Image contributions and rights</h2>
      <p>
        Submit only images you own or have permission to provide for use in Pixelguessr. You are
        responsible for the image, answer, synonyms, source information, license, required
        attribution, and the accuracy of your rights acknowledgment. Third-party and AI-generated
        images must comply with the rights and terms that apply to them.
      </p>
      <p>
        You retain ownership of your material. A submission permits staff review and use in
        Pixelguessr within the rights and license you supply; uploading does not transfer ownership
        or grant unlimited usage rights. Review does not guarantee approval or verify ownership on
        your behalf. Staff may reject, retire, or remove content. Approved licensed images and
        required credits may remain after account deletion where their license permits continued
        use.
      </p>
      <h2>Moderation and account access</h2>
      <p>
        Staff may issue warnings, probation, suspension, or account closure according to the conduct
        and integrity concerns involved; sanctions do not require a fixed escalation sequence.
        Restrictions differ by sanction. Account Standing shows current notices and any appeal
        action the application makes available. Eligibility and cooldowns apply; closure is not
        appealable through that interface. No response deadline or particular outcome is promised.
      </p>
      <p>
        You may voluntarily close your account through Settings. Closure prevents sign-in and does
        not itself erase stored data. Authorized administrators can reopen a closed account or
        process eligible permanent deletion through the existing controls. See the{' '}
        <Link to="/privacy">Privacy Policy</Link> for retention limitations.
      </p>
      <h2>Availability and limitations</h2>
      <p>
        The service is provided on an “as available” basis. The operator may maintain, change,
        interrupt, or discontinue features. To the extent permitted by applicable law, no guarantee
        is made of uninterrupted service, error-free operation, or fitness for a particular purpose,
        and responsibility for indirect losses is limited. Nothing in this draft excludes rights or
        liability that applicable law does not allow to be excluded.
      </p>
    </LegalPage>
  );
}

export function Privacy() {
  return (
    <LegalPage title="Privacy Policy">
      <h2>What the application stores</h2>
      <ul>
        <li>
          <strong>Accounts:</strong> username, display name, email, a password hash rather than a
          readable password, account identifiers, account dates, permissions, and the date of the
          latest username assignment/change.
        </li>
        <li>
          <strong>Gameplay:</strong> guest or account participation, party membership and settings,
          rounds, timestamps, guesses where the mode stores them, scores, connection/presence state,
          Elo, and match history. Ranked records whether a guess was used and whether it was
          correct; its current implementation does not retain the submitted guess text.
        </li>
        <li>
          <strong>Contributions:</strong> uploaded images, answers, synonyms, categories,
          source/provenance references, licenses, credits, rights acknowledgments, and review
          history. Images are validated and converted for storage. References supplied for review
          are stored; the submission endpoint does not fetch arbitrary external image URLs.
        </li>
        <li>
          <strong>Moderation and administration:</strong> reports, player-facing sanction reasons,
          private staff notes, acknowledgments, appeals, decisions, name corrections, and
          administrative audit records.
        </li>
      </ul>
      <h2>How information is used</h2>
      <p>
        Information supports accounts, guest continuity, gameplay, matchmaking, rankings,
        contribution review, safety, abuse prevention, account settings, and administrative
        accountability. Requests also process connection information, including IP addresses, for
        transport and request-rate controls. Operational logging depends on the deployment.
      </p>
      <h2>Public and restricted information</h2>
      <p>
        Usernames, display names, honorary titles, join dates, ranked ratings/statistics, and
        completed ranked match history can appear on public profiles and standings. Other players in
        a party or duel see the identities and game state needed to play. Images used in games
        reveal their answers and license/credit information when the applicable round completes.
      </p>
      <p>
        Email addresses and password hashes are not part of public profiles. Private image files,
        pending contributions, report details, internal staff notes, and administrative metadata are
        restricted by the application’s account and staff permissions. Players can review their own
        contribution and sanction/appeal information. Authorized staff access the records needed for
        moderation and administration.
      </p>
      <h2>Cookies, local previews, and external resources</h2>
      <p>
        The application uses a session cookie for sign-in and guest continuity and a CSRF
        cookie/token to protect requests. Server-side sessions can contain account or guest
        identifiers. Browser memory temporarily holds form values and local image-preview URLs;
        preview URLs are released when replaced or when the submission form closes. The current
        frontend does not use localStorage or sessionStorage for account data or authentication
        tokens.
      </p>
      <p>
        The stylesheet loads Google Fonts from Google’s font services. Your browser contacts those
        services to obtain fonts, exposing normal request/connection information to the provider.
        External source links, if followed, are governed by the destination’s policies. No
        advertising or analytics integration was identified in the current application code;
        deployment-specific services must be reviewed separately.
      </p>
      <h2>Account closure, deletion, and retention</h2>
      <p>
        Voluntary or disciplinary closure disables account access but is not permanent deletion. An
        authorized administrator can process eligible deletion of a closed account. That workflow
        removes the account and specified account-owned records, removes or anonymizes identifying
        references in shared records, and invalidates sessions. Shared game history can remain
        anonymized. Approved licensed images and necessary licensing/provenance information can
        remain without an account association. A limited deletion audit is retained.
      </p>
      <p>
        Deletion does not promise that every reference in free text, operational logs, third-party
        systems, or backups disappears immediately. <strong>Operator review:</strong> document
        actual retention periods, backup handling, and the process/contact for privacy requests. No
        unverified retention schedule is stated here.
      </p>
      <h2>Hosting, storage, and safeguards</h2>
      <p>
        The application uses server-side permissions, password hashing, CSRF protection, and private
        image storage. Storage may be local or configured with an S3-compatible service; cache and
        live-update services depend on deployment. These safeguards do not guarantee absolute
        security.
      </p>
      <p>
        <strong>Operator review:</strong> confirm the deployed hosting/storage providers, data
        locations, logging and monitoring, any additional processors or tracking, and the
        information required by applicable law. These deployment facts cannot be established from
        this codebase alone.
      </p>
    </LegalPage>
  );
}
