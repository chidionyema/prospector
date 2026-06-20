# syntax=docker/dockerfile:1
#
# Store.Web production image (Next.js standalone output — see next.config `output: "standalone"`).
#
# Build context = this directory (src/Store.Web). NEXT_PUBLIC_API_URL is inlined into the client
# bundle at BUILD time, so it must be the PUBLIC Store.Api URL and is passed as a build arg.
# Deploy with (run from src/Store.Web):
#   fly deploy --config ../../deploy/fly/web.fly.toml \
#     --build-arg NEXT_PUBLIC_API_URL=https://<your-api-app>.fly.dev
# Plain Docker equivalent:
#   docker build --build-arg NEXT_PUBLIC_API_URL=https://api.example.com -t store-web .

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
