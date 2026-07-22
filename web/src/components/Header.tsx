/**
 * The page header - Scout's name and a one-line description of what
 * it does. Purely presentational: no props, no state, no networking.
 */
export function Header(): JSX.Element {
  return (
    <header className="scout-header">
      <h1>Scout</h1>
      <p className="scout-header__description">
        Your retail shopping assistant - ask for a product in plain language and Scout will search
        the catalog, check real inventory, and give you a verified, grounded answer.
      </p>
    </header>
  );
}
