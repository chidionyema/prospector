import killNames from '@/data/kill-log-names.json';
import { cx } from '@/components/ui/cx';

/*
  The 1,328 rejected ideas, as the hero's backdrop.

  WHAT PROBLEM THIS SOLVES. The kill log is the most distinctive thing this shop owns and the only
  part of the pitch a stranger cannot get anywhere else, and it was rendered as three lines of text
  in a panel below the shelf. Meanwhile the hero was a headline, a paragraph and two buttons: the
  page's most valuable screen carried none of its evidence. The fix is not to move the panel up,
  which is what a previous pass tried and correctly reverted (see the note in `pages/index.tsx`
  above the featured slot: the largest coloured object on the first screen became a list of things
  we do not sell). The fix is to make the dead ideas AMBIENT. As a backdrop they are texture and
  scale, at the weight of a watermark; as a panel they were a competing product.

  That distinction is the whole design. Nothing here is above `text-caption`, nothing here is
  interactive, and the whole column runs at 55% opacity behind a fade to the page background, so it
  reads as the substrate the survivors were cut from rather than as content to be read. The reader
  who leans in can read individual struck names, which is the point: it is real data, not a
  decorative pattern, and every string on screen is a title the engine actually rejected.

  WHY IT IS `aria-hidden`. A screen reader must not wade through 120 rejected product names to
  reach the headline. The FACT this column expresses (how many were rejected, and that you can read
  them) is carried in text by `HeroEvidenceStrip` directly beside it, and links to `/kill-log` where the
  same records are a real, navigable table. The visual is the only thing being hidden.
*/

/* `kill-log-names.json`, deliberately: see the note in `LiveKillCard`. This column needs a name
   and a reason, and the full log is ~507 KB of reasons and citations it would never render. */
type Entry = { title: string; gate: string; gateLabel: string };

const ENTRIES = (killNames as Entry[]).map((entry) => ({
  // The catalogue's titles are "Name, the thing it does for whom" -- the clause after the first
  // comma is a sentence and would wrap to three lines at this width, turning a column of names
  // into a wall of grey prose. The name alone is what reads as a headstone.
  name: entry.title.split(',')[0].trim(),
  // `entry.gateLabel`, not `entry.gate.replace(/_/g, ' ')`. The old form printed the engine's
  // schema names down the hero -- "value durability", "payer solvency" -- and rendered ONE gate
  // under two different names in the same visible column, because the log carries both
  // `distribution` and `route_to_market` for the same check (5 and 3 of 400 entries). The label
  // collapses them to the one sentence /kill-log prints, so the same failure cannot appear twice
  // under two names 40px apart.
  reason: entry.gateLabel,
}));

/*
  The list is rendered TWICE, back to back, and the animation travels exactly -50%. That is what
  makes the loop seamless: at the instant the keyframe wraps, the second copy sits pixel-for-pixel
  where the first one started. A single copy would visibly snap back to the top every cycle, and a
  JS-driven infinite scroll would cost a re-render on every frame for a decoration.
*/
const LOOP = [...ENTRIES, ...ENTRIES];

export function AmbientKillColumn({ className }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={cx(
        // `opacity-[0.55]` is the fix, not decoration: the block comment above has always
        // documented this column at "55% opacity... the weight of a watermark", but no opacity
        // was ever applied here. `--subtle` (tokens.css) is chosen for 4.83:1 AA contrast -- a
        // fully readable body colour, not a watermark tone -- so without this the "ambient" kill
        // names rendered at full visual weight, competing with the hero and the featured card
        // beside it instead of receding behind them. Measured live on mumchimp.com/ 2026-08-09.
        'pointer-events-none absolute inset-y-0 right-0 z-0 hidden w-[42%] overflow-hidden opacity-[0.55] lg:block',
        className,
      )}
      style={{
        // Fades to nothing at all four edges so the column has no hard boundary anywhere. A visible
        // top or bottom edge would read as a panel with its border removed, which is exactly the
        // object this is not.
        maskImage:
          'linear-gradient(to bottom, transparent, #000 18%, #000 82%, transparent), linear-gradient(to right, transparent, #000 55%)',
        WebkitMaskImage:
          'linear-gradient(to bottom, transparent, #000 18%, #000 82%, transparent), linear-gradient(to right, transparent, #000 55%)',
        maskComposite: 'intersect',
        WebkitMaskComposite: 'source-in',
      }}
    >
      <div className="kill-drift flex flex-col gap-1.5">
        {LOOP.map((entry, i) => (
          <div key={i} className="flex items-baseline gap-2 whitespace-nowrap">
            {/* `line-through` on the name, and the name only. Striking the reason too would
                say the REASON was withdrawn, when the reason is the part that still stands. */}
            <span className="font-mono text-caption text-subtle line-through decoration-kill/50">
              {entry.name}
            </span>
            <span className="font-mono text-caption text-kill/45">{entry.reason}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default AmbientKillColumn;
