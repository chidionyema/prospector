import { useRouter } from 'next/router';
import { useEffect, useState } from 'react';
import type { OrderDetails } from '@/lib/api/client';
import { fetchOrder } from '@/lib/api/client';
import { API_BASE_URL } from '@/lib/config';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Skeleton } from '@/components/ui';

export default function OrderPage() {
  const router = useRouter();
  const { token } = router.query;
  const [order, setOrder] = useState<OrderDetails | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token || typeof token !== 'string') return;

    fetchOrder(token)
      .then((data) => {
        setOrder(data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message === 'not_found' ? 'Order not found.' : 'Could not load order.');
        setLoading(false);
      });
  }, [token]);

  if (loading) {
    return (
      <MarketingLayout>
        <div className="flex min-h-dvh items-center justify-center px-6">
          <div className="w-full max-w-md space-y-5">
            <Skeleton className="h-8 w-3/4" />
            <Skeleton className="h-5 w-full" />
            <Skeleton className="h-5 w-2/3" />
          </div>
        </div>
      </MarketingLayout>
    );
  }

  if (error) {
    return (
      <MarketingLayout>
        <div className="flex min-h-dvh items-center justify-center px-6">
          <div className="text-center">
            <h1 className="text-2xl font-bold text-text mb-2">Order not found</h1>
            <p className="text-muted">{error}</p>
          </div>
        </div>
      </MarketingLayout>
    );
  }

  // Only follow a first-party relative path or an explicit https URL. This neutralises a
  // `javascript:`/`data:` value (which `download` does NOT block) if the API is ever
  // compromised or buggy. `\/(?!\/)` rejects protocol-relative `//evil.com`.
  //
  // The API returns downloadPath as a root-relative path ("/download/<token>"), but /download
  // is served by the API, not by this storefront and not proxied to it, using the bare path
  // resolved against the web origin and 404'd. Relative paths are resolved against the API.
  const rawDownload = order?.downloadPath ?? '';
  const downloadHref = /^https:\/\//.test(rawDownload)
    ? rawDownload
    : /^\/(?!\/)/.test(rawDownload)
      ? `${API_BASE_URL}${rawDownload}`
      : '#';

  return (
    <MarketingLayout>
      <div className="flex min-h-dvh items-center justify-center px-6 py-16">
        <div className="bg-surface rounded-xl shadow-sm border border-border p-8 max-w-md w-full mx-4">
          <h1 className="text-2xl font-bold text-text mb-2">Thank you for your purchase</h1>
          <p className="text-muted mb-6">
            Your order for <strong>{order?.packTitle}</strong> is ready.
          </p>

          <a
            href={downloadHref}
            className="block w-full text-center bg-primary text-on-primary font-medium py-3 px-6 rounded-lg hover:bg-primary/90 transition-colors"
            download
          >
            Download now
          </a>

          {/* The old copy here ("expires after 5 minutes… available once") described the presigned
              R2 URL that /download mints internally, NOT this page. The buyer's grant token has
              ExpiresAt = null and a 50-download cap (DeliveryEndpoints.cs:25). Telling a paying
              customer their permanent recovery link is already dead is how a sale becomes a refund. */}
          <p className="text-xs text-muted mt-4 text-center">
            Bookmark this page, it is your permanent access link and does not expire. You can
            re-download your pack here whenever you need it.
          </p>
        </div>
      </div>
    </MarketingLayout>
  );
}
