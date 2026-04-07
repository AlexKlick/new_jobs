import { useState, useEffect } from 'react';

interface CircuitBreakerBannerProps {
  resetsIn: number;  // seconds until circuit resets
}

export function CircuitBreakerBanner({ resetsIn: initialResetsIn }: CircuitBreakerBannerProps) {
  const [countdown, setCountdown] = useState(initialResetsIn);

  useEffect(() => {
    setCountdown(initialResetsIn);

    const interval = setInterval(() => {
      setCountdown(prev => {
        if (prev <= 1) {
          clearInterval(interval);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(interval);
  }, [initialResetsIn]);

  return (
    <div className="circuit-breaker-banner">
      <div className="circuit-breaker-icon">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
          <path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z" />
        </svg>
      </div>
      <div className="circuit-breaker-text">
        <strong>Too many attempts.</strong>
        <span> Please wait {countdown} seconds before trying again.</span>
      </div>
    </div>
  );
}
