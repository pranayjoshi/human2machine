export default function PrivacyPage() {
  return (
    <main className="privacy-page">
      <a className="privacy-back" href="/">← H<span>2</span>M</a>
      <article>
        <p>PRIVACY NOTE</p>
        <h1>Privacy,<br /><em>plainly.</em></h1>
        <section>
          <h2>Waitlist</h2>
          <p>We store your email and signup time in a private Google Sheet only to manage H2M pilot access. We do not sell it.</p>
        </section>
        <section>
          <h2>Biological data</h2>
          <p>The landing-page signals are illustrative. This website does not collect EEG, EMG, vision, audio, or thermal data.</p>
        </section>
        <section>
          <h2>Storage</h2>
          <p>Waitlist access is limited to the H2M team and retained only while we manage pilot invitations.</p>
        </section>
      </article>
    </main>
  );
}
