# VEYRA web image (Next.js standalone output)
FROM node:22-alpine AS deps
RUN corepack enable
WORKDIR /repo
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml* ./
COPY apps/web/package.json apps/web/
COPY packages/api-client/package.json packages/api-client/
COPY packages/design-tokens/package.json packages/design-tokens/
RUN pnpm install --frozen-lockfile

FROM deps AS build
ARG NEXT_PUBLIC_VEYRA_ENV=dev
ARG VEYRA_API_INTERNAL_URL=http://api:8000
ENV NEXT_PUBLIC_VEYRA_ENV=$NEXT_PUBLIC_VEYRA_ENV VEYRA_API_INTERNAL_URL=$VEYRA_API_INTERNAL_URL NEXT_TELEMETRY_DISABLED=1
COPY . .
RUN pnpm --filter @veyra/web build

FROM node:22-alpine AS run
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
WORKDIR /app
RUN adduser -D -u 10001 veyra
COPY --from=build --chown=veyra /repo/apps/web/.next/standalone ./
COPY --from=build --chown=veyra /repo/apps/web/.next/static ./apps/web/.next/static
USER veyra
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
