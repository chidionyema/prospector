// @vitest-environment jsdom
//
// The storefront crash has to leave the browser.
//
// Until 2026-08-20 `ErrorBoundary.componentDidCatch` called `console.error` and stopped. That
// trace exists in one buyer's devtools on one phone, which is the same as no trace: the money
// surface was the one surface the central log could not answer for. These tests pin the report,
// and pin that a broken reporter cannot break the recovery panel it sits inside.
//
// Rendered with `react-dom/client` and `React.act` rather than React Testing Library. RTL is a
// devDependency this estate's installs do not carry -- there is no
// `store_platform/src/Store.Web/node_modules/@testing-library` on this machine or in the shared
// checkout -- so a test importing it is a test that only ever runs on CI. React and react-dom
// are already here.
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ErrorBoundary } from '@/components/ErrorBoundary';

function Boom(): React.ReactElement {
  throw new Error('undefined is not an object');
}

let container: HTMLDivElement;
let root: Root;

function draw(children: React.ReactNode): void {
  act(() => {
    root.render(<ErrorBoundary>{children}</ErrorBoundary>);
  });
}

function sent(fetchMock: ReturnType<typeof vi.fn>) {
  const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
  return { url, init, body: JSON.parse(String(init.body)) as Record<string, string> };
}

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  // React prints the caught error itself; without this the suite output is the crash it expects.
  vi.spyOn(console, 'error').mockImplementation(() => {});
  window.sessionStorage.clear();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('a render-time crash', () => {
  it('is posted to /api/client-log with the message, the stack and the correlation id', () => {
    const fetchMock = vi.fn(async () => ({ ok: true, status: 204 }) as unknown as Response);
    vi.stubGlobal('fetch', fetchMock);

    draw(<Boom />);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const { url, init, body } = sent(fetchMock);
    expect(url).toBe('/api/client-log');
    expect(init.method).toBe('POST');
    // keepalive, because the buyer's next act is a reload and a normal fetch dies with the
    // navigation that follows it.
    expect(init.keepalive).toBe(true);
    const headers = init.headers as Record<string, string>;
    expect(headers['Content-Type']).toBe('application/json');
    expect(headers['X-Correlation-Id'], "the crash cannot be joined to the buyer's API calls")
      .toBeTruthy();
    expect(body.where).toBe('ErrorBoundary');
    expect(body.message).toBe('undefined is not an object');
    expect(body.stack).toContain('Error');
    expect(body.componentStack).toContain('Boom');
  });

  it('still shows the recovery panel when the report itself throws', () => {
    // The reporter runs inside a boundary that has already caught one error. If it could throw,
    // the buyer would get the blank white page the boundary exists to prevent.
    vi.stubGlobal('fetch', () => {
      throw new Error('no network');
    });

    draw(<Boom />);

    expect(container.textContent).toContain('Something went wrong');
  });

  it('leaves a healthy tree alone and reports nothing', () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    draw(<p>all fine</p>);
    expect(container.textContent).toContain('all fine');
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
