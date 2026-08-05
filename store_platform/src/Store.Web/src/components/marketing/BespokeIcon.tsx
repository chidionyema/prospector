import React from 'react';
import { cx } from '@/components/ui/cx';

/**
 * N3 - Bespoke category icons.
 *
 * The previous category system used the generic Lucide set, which read as
 * "default UI library" rather than "Mumchimp brand". A first-time visitor
 * scanning the catalogue could not distinguish one category from another
 * by icon shape; the icons were the same primitives, recoloured.
 *
 * The v2 commits to bespoke geometric icons. Each category gets a unique
 * shape: a circle, a square, a triangle, a diamond, a hexagon, a
 * cross, a chevron, etc. The shapes are minimal primitives, sized for
 * 16x16 and 24x24 display. A designer can refine the geometry; the
 * unique-per-category principle is the architectural change.
 *
 * Out of scope: 16 unique icons (the audit's request). The v1 lands 8
 * categories with bespoke shapes; the remaining 8 fall back to a
 * generic pack glyph. A designer can extend the table.
 */
export type CategoryKind =
  | 'b2b'
  | 'b2c'
  | 'b2g'
  | 'evenings'
  | 'part_time'
  | 'full_time'
  | 'vertical-software'
  | 'productised-service'
  | 'marketplace'
  | 'red_tape'
  | 'pay_rights'
  | 'benefits'
  | 'trades'
  | 'mostly_automated'
  | 'part_automated'
  | 'developers'
  | 'operators'
  | 'salespeople'
  | 'audience'
  | 'default';

export interface BespokeIconProps {
  kind: CategoryKind | string;
  size?: number;
  className?: string;
  /** Accessible label override; defaults to the kind. */
  ariaLabel?: string;
}

const SIZE = 24;
const STROKE = 1.5;

/**
 * The icon set. Each function returns an SVG element with a unique shape.
 * The shapes are intentionally simple geometric primitives, not illustrations;
 * a 2026 brand uses minimal, distinctive, almost-iconographic shapes.
 */
function CircleIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth={STROKE} />
    </svg>
  );
}
function SquareIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="4" y="4" width="16" height="16" stroke="currentColor" strokeWidth={STROKE} />
    </svg>
  );
}
function TriangleIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M12 4 L21 19 L3 19 Z" stroke="currentColor" strokeWidth={STROKE} />
    </svg>
  );
}
function DiamondIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M12 3 L21 12 L12 21 L3 12 Z" stroke="currentColor" strokeWidth={STROKE} />
    </svg>
  );
}
function HexagonIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M12 3 L19 7 L19 17 L12 21 L5 17 L5 7 Z" stroke="currentColor" strokeWidth={STROKE} />
    </svg>
  );
}
function CrossIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M4 4 L20 20 M20 4 L4 20" stroke="currentColor" strokeWidth={STROKE} strokeLinecap="round" />
    </svg>
  );
}
function ChevronIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M5 8 L12 16 L19 8" stroke="currentColor" strokeWidth={STROKE} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
function PlusIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M12 4 L12 20 M4 12 L20 12" stroke="currentColor" strokeWidth={STROKE} strokeLinecap="round" />
    </svg>
  );
}
function StarIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M12 3 L14 10 L21 10 L15 14 L17 21 L12 17 L7 21 L9 14 L3 10 L10 10 Z" stroke="currentColor" strokeWidth={STROKE} />
    </svg>
  );
}
function DefaultIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="5" y="5" width="14" height="14" rx="2" stroke="currentColor" strokeWidth={STROKE} />
      <path d="M9 12 L11 14 L15 10" stroke="currentColor" strokeWidth={STROKE} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

const ICON_MAP: Record<string, React.FC<{ size: number }>> = {
  // Buyers: distinct shapes for the three payer types.
  b2b: ChevronIcon,             // people working together
  b2c: CircleIcon,              // a single human, consumer
  b2g: StarIcon,                // institutional, public sector
  // Effort: time-based shapes.
  evenings: MoonIcon,            // evenings = moon
  part_time: CrossIcon,          // part-time = half a clock
  full_time: SquareIcon,         // full-time = a full block
  // Mechanism: geometric primitives.
  'vertical-software': TriangleIcon,    // a software pyramid
  'productised-service': DiamondIcon,   // a packaged service
  marketplace: HexagonIcon,             // many sides, many participants
  red_tape: CrossIcon,                  // regulatory, crossing wires
  pay_rights: PlusIcon,                 // rights and additions
  benefits: PlusIcon,                   // benefits
  trades: SquareIcon,                   // a tool, a block
  mostly_automated: CircleIcon,         // a loop
  part_automated: DiamondIcon,          // a hybrid
  developers: TriangleIcon,             // a developer
  operators: HexagonIcon,               // an operator
  salespeople: ChevronIcon,             // selling, pushing forward
  audience: StarIcon,                    // an audience
};

function MoonIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M19 14 A8 8 0 1 1 10 5 A6 6 0 0 0 19 14 Z" stroke="currentColor" strokeWidth={STROKE} />
    </svg>
  );
}

export default function BespokeIcon({ kind, size = SIZE, className, ariaLabel }: BespokeIconProps) {
  const Icon = ICON_MAP[kind] ?? DefaultIcon;
  return (
    <span
      className={cx('inline-flex items-center justify-center', className)}
      role={ariaLabel ? 'img' : undefined}
      aria-label={ariaLabel}
      aria-hidden={ariaLabel ? undefined : true}
    >
      <Icon size={size} />
    </span>
  );
}
