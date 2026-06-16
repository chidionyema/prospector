/**
 * Paddle.js loader — the ONLY place the Paddle client token is read.
 * 
 * Paddle Overlay checkout: the buyer's card data is handled by Paddle in a hosted iframe,
 * so PCI compliance is Paddle's responsibility (not ours). We just need to initialize
 * Paddle with the client token and call `Paddle.Checkout.open()` with the price ID.
 * 
 * `paddleConfigured` gates the Buy button visibility.
 */
import { PADDLE_SETTINGS } from '@/lib/config';

declare global {
  interface Window {
    Paddle?: {
      Environment: { set: (env: string) => void };
      Initialize: (options: { token: string; onReady?: () => void }) => void;
      Checkout: {
        open: (options: {
          items: Array<{ priceId: string; quantity: number }>;
          customer?: { email?: string };
          customData?: Record<string, string>;
        }) => void;
      };
    };
  }
}

let initialized = false;

export function initPaddle(): Promise<void> {
  if (initialized) return Promise.resolve();
  if (!PADDLE_SETTINGS.clientToken) {
    console.warn('Paddle client token not configured. Set NEXT_PUBLIC_PADDLE_CLIENT_TOKEN.');
    return Promise.resolve();
  }

  return new Promise((resolve) => {
    const script = document.createElement('script');
    script.src = 'https://cdn.paddle.com/paddle/v2/paddle.js';
    script.async = true;
    script.onload = () => {
      if (window.Paddle) {
        window.Paddle.Environment.set(PADDLE_SETTINGS.environment);
        window.Paddle.Initialize({
          token: PADDLE_SETTINGS.clientToken,
          onReady: () => {
            initialized = true;
            resolve();
          },
        });
      }
    };
    document.head.appendChild(script);
  });
}

export function openPaddleCheckout(priceId: string, buyerEmail?: string): void {
  if (!window.Paddle) {
    console.error('Paddle not initialized. Call initPaddle() first.');
    return;
  }

  window.Paddle.Checkout.open({
    items: [{ priceId, quantity: 1 }],
    customer: buyerEmail ? { email: buyerEmail } : undefined,
  });
}

/** True when a client token is configured — gate Buy button on this. */
export const paddleConfigured = Boolean(PADDLE_SETTINGS.clientToken);