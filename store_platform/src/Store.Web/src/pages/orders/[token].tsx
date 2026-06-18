import { useRouter } from 'next/router';
import { useEffect, useState } from 'react';
import type { OrderDetails } from '@/lib/api/client';
import { fetchOrder } from '@/lib/api/client';

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
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-gray-500">Loading order…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-gray-900 mb-2">Order not found</h1>
          <p className="text-gray-600">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-8 max-w-md w-full mx-4">
        <h1 className="text-2xl font-bold text-gray-900 mb-2">Thank you for your purchase</h1>
        <p className="text-gray-600 mb-6">
          Your order for <strong>{order?.packTitle}</strong> is ready.
        </p>

        <a
          href={order?.downloadPath ?? '#'}
          className="block w-full text-center bg-blue-600 text-white font-medium py-3 px-6 rounded-lg hover:bg-blue-700 transition-colors"
          download
        >
          Download now
        </a>

        <p className="text-xs text-gray-400 mt-4 text-center">
          This link expires after 5 minutes. Your download will be available once.
        </p>
      </div>
    </div>
  );
}
