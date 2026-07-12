# syntax=docker/dockerfile:1

FROM node:24.12.0-alpine AS dependencies
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:24.12.0-alpine AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
RUN node -e 'const { isIP } = require("node:net"); const raw = process.env.NEXT_PUBLIC_API_URL; const fail = () => { console.error("NEXT_PUBLIC_API_URL must be exactly /api/v1, a canonical public HTTPS URL ending in /api/v1, or canonical http://localhost:<port>/api/v1 for local development"); process.exit(1); }; if (!raw || /\s/.test(raw)) fail(); if (raw === "/api/v1") process.exit(0); let url; try { url = new URL(raw); } catch { fail(); } const hostname = url.hostname.replace(/^\[|\]$/g, ""); const hasDelimiters = raw.includes("?") || raw.includes("#") || raw.slice(raw.indexOf("//") + 2, raw.indexOf("/", raw.indexOf("//") + 2)).includes("@"); const canonical = raw === url.href && url.pathname === "/api/v1" && !hasDelimiters && !url.username && !url.password; if (!canonical) fail(); if (url.protocol === "http:" && url.hostname === "localhost" && /^[1-9][0-9]*$/.test(url.port) && Number(url.port) <= 65535) process.exit(0); const labels = hostname.split("."); const canonicalHostname = hostname.length <= 253 && labels.length > 1 && labels.every((label) => label.length <= 63 && /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/.test(label)); const localHostname = hostname === "localhost" || hostname.endsWith(".localhost") || hostname.endsWith(".local") || hostname.endsWith(".internal") || hostname.endsWith(".lan"); if (url.protocol !== "https:" || isIP(hostname) !== 0 || !canonicalHostname || localHostname) fail();'
COPY --from=dependencies /app/node_modules ./node_modules
COPY . .
RUN npm run build \
    && npm prune --omit=dev

FROM node:24.12.0-alpine AS runtime
WORKDIR /app
ENV HOSTNAME=0.0.0.0 \
    NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 --ingroup nodejs nextjs

COPY --from=builder --chown=nextjs:nodejs /app/package.json ./package.json
COPY --from=builder --chown=nextjs:nodejs /app/next.config.ts ./next.config.ts
COPY --from=builder --chown=nextjs:nodejs /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next ./.next
COPY --from=builder --chown=nextjs:nodejs /app/node_modules ./node_modules

USER nextjs

EXPOSE 3000

CMD ["npm", "run", "start", "--", "-H", "0.0.0.0"]
