/** H2M mark: two gripper jaws holding a block, read as an H. Same geometry as public/h2m-mark.svg. */
export function H2MMark({ size = 22 }: { size?: number }) {
  return (
    <svg className="h2m-mark" width={size} height={size} viewBox="0 0 56 56" aria-hidden="true" focusable="false">
      <rect x="9" y="8" width="10" height="40" rx="2" fill="currentColor" />
      <rect x="37" y="8" width="10" height="40" rx="2" fill="currentColor" />
      <rect x="23" y="22" width="10" height="12" rx="2" fill="currentColor" />
    </svg>
  );
}

export function H2MLogo({ size = 22 }: { size?: number }) {
  return (
    <span className="h2m-logo">
      <H2MMark size={size} />
      <strong className="h2m-wordmark">H2M</strong>
    </span>
  );
}
