import { CartIcon, MenuIcon, SparklesIcon } from "./Icons";

export interface MobileHeaderProps {
  itemCount: number;
  onMenuClick: () => void;
  onCartClick: () => void;
}

export function MobileHeader({ itemCount, onMenuClick, onCartClick }: MobileHeaderProps): JSX.Element {
  return (
    <header className="mobile-header">
      <button type="button" className="mobile-header__button" aria-label="Open navigation" onClick={onMenuClick}>
        <MenuIcon />
      </button>
      <div className="mobile-header__brand"><SparklesIcon /><span>Scout</span></div>
      <button type="button" className="mobile-header__button mobile-header__cart" aria-label={`Open mobile cart, ${itemCount} item${itemCount === 1 ? "" : "s"}`} onClick={onCartClick}>
        <CartIcon /><span>{itemCount}</span>
      </button>
    </header>
  );
}
