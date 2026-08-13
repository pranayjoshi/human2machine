import type { PlotSnapshot } from "@/lib/types";

export function Sparkline({ plot, label }: { plot: PlotSnapshot; label: string }) {
  const width = 320;
  const height = 72;
  const names = plot.channel_names.slice(0, 4);
  const paths = names.map((name, index) => {
    const values = plot.samples[name] ?? [];
    if (values.length < 2) return "";
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min || 1;
    return values
      .map((value, i) => {
        const x = (i / Math.max(1, values.length - 1)) * width;
        const y = 6 + ((max - value) / span) * (height - 12) + index * 0;
        return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");
  });

  return (
    <figure>
      <figcaption className="muted">{label}</figcaption>
      <svg className="spark" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${label} sparkline`}>
        {paths.map((d, i) =>
          d ? (
            <path
              key={names[i]}
              d={d}
              fill="none"
              stroke={i % 2 === 0 ? "#e2e8f0" : "#94a3b8"}
              strokeWidth="1.4"
            />
          ) : null,
        )}
      </svg>
    </figure>
  );
}
