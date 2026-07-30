"use client";

/**
 * A walking chicken, for loading states.
 *
 * Hand-drawn SVG with CSS keyframes rather than a GIF, for reasons that
 * are practical rather than aesthetic:
 *
 *   * ~2 kB inline against 50-200 kB for a GIF, and no extra HTTP request
 *     on a page a farmer may open over rural mobile data.
 *   * Vector, so it stays sharp on a phone screen and on a wall display.
 *   * Colours come from the app's CSS variables, so it follows the theme
 *     instead of carrying baked-in pixels that clash after a restyle.
 *   * It can honour `prefers-reduced-motion`. A GIF cannot: it animates
 *     regardless of what the operating system has been told about the
 *     viewer's tolerance for movement.
 *
 * The gait is deliberately simple -- body bob, alternating legs, an
 * occasional head peck. Enough to read as "alive and working", not so much
 * that it draws the eye away from the content it is standing in for.
 */

export default function ChickenLoader({
  label = "Loading…",
  size = 84,
}: {
  label?: string;
  size?: number;
}) {
  return (
    <div
      className="chicken-loader"
      role="status"
      aria-live="polite"
      style={{ display: "grid", placeItems: "center", gap: 10, padding: 18 }}
    >
      <svg
        width={size}
        height={size * 0.72}
        viewBox="0 0 100 72"
        aria-hidden="true"
        style={{ overflow: "visible" }}
      >
        {/* Ground line: gives the walk something to walk ON, which is what
            makes the bob read as steps rather than floating. */}
        <line
          x1="8" y1="64" x2="92" y2="64"
          stroke="var(--ink-muted)" strokeWidth="1.5"
          strokeLinecap="round" opacity="0.25"
        />

        <g className="ck-body">
          {/* legs — alternating, behind the body */}
          <g stroke="var(--orange, #fb923c)" strokeWidth="3" strokeLinecap="round">
            <g className="ck-leg ck-leg-back">
              <line x1="44" y1="50" x2="44" y2="63" />
              <line x1="44" y1="63" x2="49" y2="63" />
            </g>
            <g className="ck-leg ck-leg-front">
              <line x1="54" y1="50" x2="54" y2="63" />
              <line x1="54" y1="63" x2="59" y2="63" />
            </g>
          </g>

          {/* tail */}
          <path
            d="M32 34 Q22 24 26 38 Q20 34 30 44 Z"
            fill="var(--ink)" opacity="0.85"
          />

          {/* body */}
          <ellipse cx="50" cy="40" rx="20" ry="14" fill="var(--ink)" opacity="0.95" />
          {/* wing */}
          <path
            className="ck-wing"
            d="M46 38 Q54 32 60 40 Q52 44 46 38 Z"
            fill="var(--surface-3, #24314a)"
          />

          {/* head + neck, pecks on a slower cycle than the steps */}
          <g className="ck-head">
            <circle cx="68" cy="26" r="9" fill="var(--ink)" opacity="0.95" />
            {/* comb */}
            <path
              d="M64 18 q3 -5 5 0 q3 -5 5 1"
              fill="none" stroke="var(--red, #f87171)"
              strokeWidth="3" strokeLinecap="round"
            />
            {/* beak */}
            <path d="M77 26 l8 3 l-8 3 Z" fill="var(--orange, #fb923c)" />
            {/* wattle */}
            <path d="M74 32 q2 5 -2 6 q-2 -3 0 -6 Z" fill="var(--red, #f87171)" />
            {/* eye */}
            <circle cx="71" cy="23" r="1.6" fill="var(--bg, #0b1220)" />
          </g>
        </g>
      </svg>

      {label && (
        <div className="muted" style={{ fontSize: 12.5 }}>
          {label}
        </div>
      )}
    </div>
  );
}
