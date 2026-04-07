interface SkeletonProps {
  className?: string;
  lines?: number;
}

export function Skeleton({ className = '', lines = 1 }: SkeletonProps) {
  const baseClass = 'bg-bg-tertiary rounded animate-pulse';

  if (lines === 1) {
    return <div className={`${baseClass} h-4 ${className}`} />;
  }

  return (
    <div className={`flex flex-col gap-2 ${className}`}>
      {Array.from({ length: lines }, (_, i) => (
        <div
          key={i}
          className={`${baseClass} h-4`}
          style={{ width: i === lines - 1 ? '70%' : '100%' }}
        />
      ))}
    </div>
  );
}

export function SkeletonTableRow({ cols = 6 }: { cols?: number }) {
  const baseClass = 'bg-bg-tertiary rounded animate-pulse h-4';
  return (
    <tr className="border-b border-border-color">
      {Array.from({ length: cols }, (_, i) => (
        <td key={i} className="p-3">
          <div className={baseClass} style={{ width: i === 0 ? '2rem' : '80%' }} />
        </td>
      ))}
    </tr>
  );
}

export function SkeletonCard({ lines = 3 }: { lines?: number }) {
  return (
    <div className="bg-bg-secondary border border-border-color rounded-lg p-4 space-y-3">
      <div className="bg-bg-tertiary rounded h-5 w-1/3 animate-pulse" />
      {Array.from({ length: lines }, (_, i) => (
        <div
          key={i}
          className="bg-bg-tertiary rounded h-3 animate-pulse"
          style={{ width: i === lines - 1 ? '60%' : '100%' }}
        />
      ))}
    </div>
  );
}
