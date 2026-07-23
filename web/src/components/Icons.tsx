import type { ReactNode, SVGProps } from "react";

export type IconProps = SVGProps<SVGSVGElement>;

function BaseIcon({ children, ...props }: IconProps & { children: ReactNode }): JSX.Element {
  return (
    <svg
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {children}
    </svg>
  );
}

export function SearchIcon(props: IconProps): JSX.Element {
  return <BaseIcon {...props}><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></BaseIcon>;
}

export function HomeIcon(props: IconProps): JSX.Element {
  return <BaseIcon {...props}><path d="m3 11 9-8 9 8" /><path d="M5 10v10h14V10" /><path d="M9 20v-6h6v6" /></BaseIcon>;
}

export function TagIcon(props: IconProps): JSX.Element {
  return <BaseIcon {...props}><path d="M20 13 11 22 2 13V2h11Z" /><circle cx="7.5" cy="7.5" r="1.5" /></BaseIcon>;
}

export function GridIcon(props: IconProps): JSX.Element {
  return <BaseIcon {...props}><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></BaseIcon>;
}

export function HeartIcon(props: IconProps): JSX.Element {
  return <BaseIcon {...props}><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8l1.1 1.1L12 21l7.8-7.5 1.1-1.1a5.5 5.5 0 0 0-.1-7.8Z" /></BaseIcon>;
}

export function CartIcon(props: IconProps): JSX.Element {
  return <BaseIcon {...props}><path d="M3 3h2l2.2 10.4a2 2 0 0 0 2 1.6h7.7a2 2 0 0 0 2-1.6L20 7H6" /><circle cx="10" cy="20" r="1" /><circle cx="18" cy="20" r="1" /></BaseIcon>;
}

export function MessageIcon(props: IconProps): JSX.Element {
  return <BaseIcon {...props}><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4Z" /></BaseIcon>;
}

export function ArrowUpRightIcon(props: IconProps): JSX.Element {
  return <BaseIcon {...props}><path d="m7 17 10-10" /><path d="M7 7h10v10" /></BaseIcon>;
}

export function SendIcon(props: IconProps): JSX.Element {
  return <BaseIcon {...props}><path d="m22 2-7 20-4-9-9-4Z" /><path d="M22 2 11 13" /></BaseIcon>;
}

export function InfoIcon(props: IconProps): JSX.Element {
  return <BaseIcon {...props}><circle cx="12" cy="12" r="9" /><path d="M12 11v5" /><path d="M12 8h.01" /></BaseIcon>;
}

export function MenuIcon(props: IconProps): JSX.Element {
  return <BaseIcon {...props}><path d="M4 7h16M4 12h16M4 17h16" /></BaseIcon>;
}

export function CloseIcon(props: IconProps): JSX.Element {
  return <BaseIcon {...props}><path d="m6 6 12 12M18 6 6 18" /></BaseIcon>;
}

export function SparklesIcon(props: IconProps): JSX.Element {
  return <BaseIcon {...props}><path d="m12 3-1.4 3.6L7 8l3.6 1.4L12 13l1.4-3.6L17 8l-3.6-1.4Z" /><path d="m5 15-.8 2.2L2 18l2.2.8L5 21l.8-2.2L8 18l-2.2-.8Z" /><path d="m19 14-.7 1.8-1.8.7 1.8.7L19 19l.7-1.8 1.8-.7-1.8-.7Z" /></BaseIcon>;
}

export function CheckIcon(props: IconProps): JSX.Element {
  return <BaseIcon {...props}><path d="m5 12 4 4L19 6" /></BaseIcon>;
}

export function MapPinIcon(props: IconProps): JSX.Element {
  return <BaseIcon {...props}><path d="M20 10c0 5-8 11-8 11S4 15 4 10a8 8 0 1 1 16 0Z" /><circle cx="12" cy="10" r="2.5" /></BaseIcon>;
}

export function SlidersIcon(props: IconProps): JSX.Element {
  return <BaseIcon {...props}><path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3" /><path d="M1 14h6M9 8h6M17 16h6" /></BaseIcon>;
}

export function PackageIcon(props: IconProps): JSX.Element {
  return <BaseIcon {...props}><path d="m4 7 8-4 8 4-8 4Z" /><path d="M4 7v10l8 4 8-4V7" /><path d="M12 11v10" /></BaseIcon>;
}

export function CreditCardIcon(props: IconProps): JSX.Element {
  return <BaseIcon {...props}><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M3 10h18" /><path d="M7 15h3" /></BaseIcon>;
}

export function StoreIcon(props: IconProps): JSX.Element {
  return <BaseIcon {...props}><path d="M4 9h16" /><path d="m5 9 1-5h12l1 5" /><path d="M6 9v11h12V9" /><path d="M9 20v-6h6v6" /></BaseIcon>;
}

export function ClockIcon(props: IconProps): JSX.Element {
  return <BaseIcon {...props}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></BaseIcon>;
}

export function MinusIcon(props: IconProps): JSX.Element {
  return <BaseIcon {...props}><path d="M5 12h14" /></BaseIcon>;
}

export function CopyIcon(props: IconProps): JSX.Element {
  return <BaseIcon {...props}><rect x="8" y="8" width="11" height="11" rx="2" /><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3" /></BaseIcon>;
}
