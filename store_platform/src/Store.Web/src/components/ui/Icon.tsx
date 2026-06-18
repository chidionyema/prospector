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
} from "lucide-react";

/**
 * TIE semantic icon set (E17-003).
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
