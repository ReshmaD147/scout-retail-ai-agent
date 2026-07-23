import { CartIcon, CloseIcon, GridIcon, HeartIcon, HomeIcon, MessageIcon, SearchIcon, SparklesIcon, TagIcon } from "./Icons";

export interface SidebarProps {
  itemCount: number;
  recentSearches: string[];
  isOpen: boolean;
  showHelpCard?: boolean;
  onClose: () => void;
  onNewSearch: () => void;
  onDeals: () => void;
  onCategories: () => void;
  onSaved: () => void;
  onCartClick: () => void;
  onRecentSearch: (query: string) => void;
  onNeedHelp: () => void;
}

export function Sidebar({
  itemCount,
  recentSearches,
  isOpen,
  showHelpCard = true,
  onClose,
  onNewSearch,
  onDeals,
  onCategories,
  onSaved,
  onCartClick,
  onRecentSearch,
  onNeedHelp,
}: SidebarProps): JSX.Element {
  return (
    <aside className={`sidebar${isOpen ? " sidebar--open" : ""}`} aria-label="Primary navigation">
      <div className="sidebar__top-row">
        <div className="sidebar__brand" aria-label="Scout">
          <span className="sidebar__brand-mark"><SparklesIcon /></span>
          <span>Scout</span>
          <span className="sidebar__brand-star" aria-hidden="true">✦</span>
        </div>
        <button type="button" className="sidebar__close" aria-label="Close navigation" onClick={onClose}>
          <CloseIcon />
        </button>
      </div>

      <button type="button" className="sidebar__new-search" onClick={onNewSearch}>
        <SearchIcon />
        <span>New search</span>
      </button>

      <nav className="sidebar__nav" aria-label="Scout sections">
        <button type="button" className="sidebar__nav-item sidebar__nav-item--active" onClick={onNewSearch}>
          <HomeIcon /><span>Home</span>
        </button>
        <button type="button" className="sidebar__nav-item" onClick={onDeals}>
          <TagIcon /><span>Deals</span>
        </button>
        <button type="button" className="sidebar__nav-item" onClick={onCategories}>
          <GridIcon /><span>Categories</span>
        </button>
        <button type="button" className="sidebar__nav-item" onClick={onSaved}>
          <HeartIcon /><span>Saved</span>
        </button>
        <button type="button" className="sidebar__nav-item" onClick={onCartClick}>
          <CartIcon /><span>Cart</span>
          <span className="sidebar__badge" aria-label={`Cart quantity: ${itemCount}`}>{itemCount}</span>
        </button>
      </nav>

      <div className="sidebar__divider" />

      <section className="sidebar__recent" aria-labelledby="recent-searches-title">
        <h2 id="recent-searches-title">Recent searches</h2>
        {recentSearches.length === 0 ? (
          <p className="sidebar__recent-empty">Your searches will appear here.</p>
        ) : (
          <ul>
            {recentSearches.slice(0, 5).map((search, index) => (
              <li key={`${search}-${index}`}>
                <button type="button" onClick={() => onRecentSearch(search)}>{search}</button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {showHelpCard && (
        <section className="sidebar__help-card" aria-label="Need help">
          <span className="sidebar__help-sparkle"><SparklesIcon /></span>
          <h2>Need help?</h2>
          <p>Ask Scout about products, availability, cart, checkout, or order status.</p>
          <button type="button" onClick={onNeedHelp}><MessageIcon /> Chat with Scout</button>
        </section>
      )}
    </aside>
  );
}
