/** Premium welcome header. The aria-label preserves a concise page
 * heading for assistive technology while the visible copy follows the
 * reference design. */
export function Header(): JSX.Element {
  return (
    <header className="scout-header">
      <h1 aria-label="Scout">Hi! I&apos;m <span>Scout.</span></h1>
      <p className="scout-header__description">
        Your AI shopping assistant. Ask in natural language and get verified, grounded answers.
      </p>
    </header>
  );
}
