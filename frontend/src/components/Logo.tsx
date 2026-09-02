/**
 * The brand mark: a car with its hood up, which is the name and the product in
 * one glyph — کاپوت opens the bonnet on a listing instead of reprinting what
 * the seller chose to say. Drawn rather than imported so it inherits the
 * theme's colours and never ships a second asset request in front of the hero.
 *
 * The geometry is tuned for the sizes it is actually used at: the raised hood
 * is a single sweeping stroke and the sills are broken rather than tucked
 * behind the wheels, so nothing merges into a blob once the tile drops to the
 * 16px favicon. `HoodMark` is the bare glyph for anywhere that brings its own
 * container — the header tile below is the default dress.
 */
export function HoodMark({
  className = "h-full w-full",
  /** Thinner at poster sizes: the weight that keeps the favicon legible reads
   *  as a slab once the glyph is 500px wide. */
  strokeWidth = 1.75,
}: {
  className?: string;
  strokeWidth?: number;
}) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      {/* The hood, hinged at the windscreen and swung open over the bay. */}
      <path d="M4 6.5C8 6.3 12.4 7.7 15.5 10.2" />
      {/* Cabin and rear. */}
      <path d="M15.5 10.2h2c.9 0 1.7.5 2.1 1.3l1.1 2.2" />
      {/* Front clip, rising to meet the open hood's hinge. */}
      <path d="M2.9 15.5v-3.2c0-.9.6-1.7 1.5-1.9l4.7-1" />
      <path d="M2.9 15.5h1.9M9.4 15.5h5.4M19.4 15.5h1.7" />
      <circle cx="7.1" cy="15.5" r="2.3" />
      <circle cx="17.1" cy="15.5" r="2.3" />
    </svg>
  );
}

export function Logo({ className = "h-9 w-9" }: { className?: string }) {
  return (
    <span
      className={`${className} inline-flex shrink-0 items-center justify-center rounded-xl
                  bg-brand text-white shadow-card`}
      aria-hidden
    >
      <HoodMark className="h-[64%] w-[64%]" />
    </span>
  );
}
