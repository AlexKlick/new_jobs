/**
 * CacheStatusBadge — Shows "from cache" badge for TTS cache hits
 *
 * After TTS synthesis, checks X-Cache response header and displays
 * a green "from cache" badge if HIT. Badge fades after 5 seconds.
 */

import { useState, useEffect } from 'react';

interface CacheStatusBadgeProps {
  cacheStatus: 'HIT' | 'MISS' | null;
}

export function CacheStatusBadge({ cacheStatus }: CacheStatusBadgeProps) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (cacheStatus === 'HIT') {
      setVisible(true);
      const timer = setTimeout(() => setVisible(false), 5000);
      return () => clearTimeout(timer);
    }
    setVisible(false);
  }, [cacheStatus]);

  if (!visible || cacheStatus !== 'HIT') {
    return null;
  }

  return (
    <span className="cache-status-badge">
      from cache
    </span>
  );
}

export default CacheStatusBadge;
