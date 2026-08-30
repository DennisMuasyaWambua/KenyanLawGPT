FROM node:22-alpine
WORKDIR /app

# Install deps first for layer caching. No lockfile is committed, so `npm install`
# resolves within the pinned semver ranges in package.json.
COPY package.json ./
RUN npm install --omit=dev --no-audit --no-fund

COPY server.js ./

ENV NODE_ENV=production
EXPOSE 3100
CMD ["node", "server.js"]
