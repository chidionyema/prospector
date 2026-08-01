# syntax=docker/dockerfile:1
#
# Store.Web production image (Next.js standalone output — see next.config `output: "standalone"`).
#
# Build context = this directory (src/Store.Web). NEXT_PUBLIC_API_URL is inlined into the client
# bundle at BUILD time, so it must be the PUBLIC Store.Api URL and is passed as a build arg.
# NEXT_PUBLIC_SITE_URL is likewise build-time (canonical/og tags). Deploy with (run from
# src/Store.Web — the build context is this directory, so `.` is required and the repo root fails
# with "/package.json": not found):
#   fly deploy . --config ../../deploy/fly/web.fly.toml \
#     --build-arg NEXT_PUBLIC_API_URL=https://<your-api-app>.fly.dev \
#     --build-arg NEXT_PUBLIC_SITE_URL=https://<your-storefront-domain>
# Plain Docker equivalent:
#   docker build --build-arg NEXT_PUBLIC_API_URL=https://api.example.com \
#     --build-arg NEXT_PUBLIC_SITE_URL=https://example.com -t store-web .

FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS build
WORKDIR /app
# Baked into the client bundle — must be the real public API origin. .env*.local is excluded via
# .dockerignore so it can never shadow this at build time.
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
# Also build-time: config.ts exports SITE_URL from this, and Seo.tsx / _document.tsx emit the
# canonical tag, og:url, og:image and the JSON-LD organization block ONLY when it is set. Without
# this ARG the build arg is accepted on the command line and silently discarded, so the site ships
# with no canonical URLs and no social preview card — a failure with no error message anywhere.
ARG NEXT_PUBLIC_SITE_URL
ENV NEXT_PUBLIC_SITE_URL=$NEXT_PUBLIC_SITE_URL
# Same silent-discard trap as SITE_URL above, but this one costs money rather than SEO. lib/stripe.ts
# reads this to decide `stripeConfigured`; undeclared, the --build-arg is dropped and the bundle
# ships with no key, so resolveStripeCheckout skips the embedded surface entirely and every buyer
# is redirected to hosted checkout. That degrades safely — which is exactly why it can sit
# unnoticed. The MODE must match the API's secret key: a pk_test_ bundle against a live API cannot
# confirm a live PaymentIntent. scripts/deploy_web.sh enforces both facts before a build starts.
ARG NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY
ENV NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=$NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY
# Search-console ownership tokens (lib/seo/verification.ts -> _document.tsx). Same silent-discard
# trap again: undeclared, the --build-arg is accepted and dropped, no meta tag is emitted, and the
# console just keeps saying "ownership not verified" with nothing to debug. Both are OPTIONAL — an
# unset one emits no tag at all, which is correct, because an empty `content=""` is a FAILED
# verification rather than an absent one.
ARG NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION
ENV NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION=$NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION
ARG NEXT_PUBLIC_BING_SITE_VERIFICATION
ENV NEXT_PUBLIC_BING_SITE_VERIFICATION=$NEXT_PUBLIC_BING_SITE_VERIFICATION
# NOTE — INDEXNOW_KEY is deliberately NOT here. It is read at request time by
# pages/indexnow-key.txt.tsx, so it is a runtime secret (`fly secrets set INDEXNOW_KEY=...`), and
# baking it in would mean a rotation needs a rebuild. It must match the engine's own INDEXNOW_KEY.
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0
# Next standalone: a minimal server.js plus the traced node_modules subset.
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
