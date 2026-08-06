import {
  LockIcon,
  UnlockIcon,
  BadgeCheckIcon,
  UserCheckIcon,
  EyeOffIcon,
  InfoIcon,
  CalendarIcon,
  CheckCircle2Icon,
  AlertCircleIcon,
  ClockIcon,
  HistoryIcon,
  MenuIcon,
  XIcon,
  CheckIcon,
  LandmarkIcon,
  HomeIcon,
  LayoutGridIcon,
  UsersIcon,
  PlusIcon,
  SettingsIcon,
  LogOutIcon,
  ArrowRightIcon,
  WalletIcon,
  UserIcon,
  SearchIcon,
  Building2Icon,
  BriefcaseIcon,
  HandshakeIcon,
  GavelIcon,
  CoinsIcon,
  ShieldIcon,
  TrendingUpIcon,
  Code2Icon,
  MailIcon,
  DownloadIcon,
  AlertTriangleIcon,
  ShoppingBagIcon,
  Trash2Icon,
  FileTextIcon,
  PlusIcon as PlusSignIcon,
  PawPrintIcon,
  KeyIcon,
  PackageIcon,
  PaletteIcon,
} from "lucide-react";

/**
 * Semantic icon set for the storefront.
 * Wraps Lucide to enforce accessible defaults and stroke consistency.
 * Icons inherit color from their parent (text-currentColor).
 */

const ICON_MAP = {
  held: LockIcon,
  released: UnlockIcon,
  verified: BadgeCheckIcon,
  vouched: UserCheckIcon,
  private: EyeOffIcon,
  info: InfoIcon,
  scheduled: CalendarIcon,
  completed: CheckCircle2Icon,
  disputed: AlertCircleIcon,
  pending: ClockIcon,
  expired: HistoryIcon,
  menu: MenuIcon,
  close: XIcon,
  check: CheckIcon,
  landmark: LandmarkIcon,
  search: SearchIcon,
  // App-shell navigation + account (P1 left-sidebar shell).
  home: HomeIcon,
  board: LayoutGridIcon,
  roster: UsersIcon,
  post: PlusIcon,
  settings: SettingsIcon,
  signout: LogOutIcon,
  arrowRight: ArrowRightIcon,
  wallet: WalletIcon,
  account: UserIcon,
  // Network Graph / Marketing specific
  building: Building2Icon,
  briefcase: BriefcaseIcon,
  handshake: HandshakeIcon,
  gavel: GavelIcon,
  money: CoinsIcon,
  lock: LockIcon,
  shield: ShieldIcon,
  'trending-up': TrendingUpIcon,
  code: Code2Icon,
  mail: MailIcon,
  download: DownloadIcon,
  warning: AlertTriangleIcon,
  // Basket: several packs, one payment.
  cart: ShoppingBagIcon,
  trash: Trash2Icon,
  /* A deliverable in the bundle. Replaces the per-item emoji, which rendered as a different
     piece of vendor artwork on every OS. */
  document: FileTextIcon,
  plus: PlusSignIcon,
  /* Four sector marks added 2026-08-06. The pack cover draws the sector icon at 40px and again at
     96px, so it is now the largest element on a card -- and three pairs of sectors were sharing
     one glyph (`home` for housing AND pets, `gavel` for licensing AND probate, `briefcase` for
     professional services AND "specialist niches", 26 of the 63 live packs between them). Two
     cards side by side with the same large mark read as the same product. */
  paw: PawPrintIcon,
  key: KeyIcon,
  package: PackageIcon,
  palette: PaletteIcon,
} as const;

export type IconName = keyof typeof ICON_MAP;

interface IconProps {
  name: IconName;
  className?: string;
  size?: number;
}

export function Icon({ name, className, size = 20 }: IconProps) {
  const LucideIcon = ICON_MAP[name];

  return (
    <LucideIcon
      className={className}
      size={size}
      strokeWidth={1.5}
      aria-hidden="true"
      focusable="false"
      color="currentColor"
    />
  );
}
