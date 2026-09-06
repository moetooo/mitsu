export default function InkWashSpinner({ 
  size = 32, 
  className = '', 
  label = null,
  color = 'var(--accent-vermillion)'
}) {
  const s = size;

  return (
    <div className={`inline-flex items-center gap-3 ${className}`}>
      {/* Container with exact dimensions ensuring geometric stability */}
      <div 
        className="relative shrink-0 flex items-center justify-center select-none"
        style={{ width: `${s}px`, height: `${s}px` }}
      >
        {/* Rotating SVG Enso Ink-Brush Ring - spins 100% stable around (24, 24) center */}
        <svg
          viewBox="0 0 48 48"
          className="w-full h-full animate-spin"
          style={{ 
            animationDuration: '1.25s', 
            animationTimingFunction: 'linear',
            transformOrigin: '24px 24px'
          }}
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <defs>
            <linearGradient id="ink-wash-brush-grad" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor={color} stopOpacity="1" />
              <stop offset="40%" stopColor={color} stopOpacity="0.85" />
              <stop offset="75%" stopColor={color} stopOpacity="0.2" />
              <stop offset="100%" stopColor={color} stopOpacity="0" />
            </linearGradient>
            <filter id="ink-wash-bleed" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="0.4" />
            </filter>
          </defs>

          {/* Faint subtle background ink guide circle */}
          <circle
            cx="24"
            cy="24"
            r="19"
            stroke={color}
            strokeWidth="1.5"
            strokeOpacity="0.12"
            strokeDasharray="3 5"
          />

          {/* Primary Sumi-e Enso Brush Arc with tapered head and tail */}
          <circle
            cx="24"
            cy="24"
            r="19"
            stroke="url(#ink-wash-brush-grad)"
            strokeWidth="3.2"
            strokeLinecap="round"
            strokeDasharray="88 32"
            filter="url(#ink-wash-bleed)"
          />

          {/* Delicate ink droplets along the brush path */}
          <circle
            cx="24"
            cy="5"
            r="2.2"
            fill={color}
            opacity="0.95"
          />
          <circle
            cx="29.5"
            cy="6.2"
            r="1.2"
            fill={color}
            opacity="0.75"
          />
        </svg>

        {/* Perfectly centered stationary Mon emblem - never wobbles or shakes */}
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <span 
            className="font-serif-jp leading-none select-none animate-pulse"
            style={{ 
              color: color,
              fontSize: `${Math.max(10, Math.round(s * 0.38))}px`
            }}
          >
            ❖
          </span>
        </div>
      </div>

      {label && (
        <span className="text-xs font-mono tracking-wide text-[var(--text-muted)] animate-pulse select-none">
          {label}
        </span>
      )}
    </div>
  );
}
