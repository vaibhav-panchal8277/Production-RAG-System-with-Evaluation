# --- build stage -------------------------------------------------------------
FROM node:20-alpine AS build

WORKDIR /app

# Install deps first (better layer caching)
COPY package.json yarn.lock* ./
RUN yarn install --frozen-lockfile || yarn install

COPY . .

# CRA inlines REACT_APP_* at build time, so the backend URL is a build arg —
# changing it requires a rebuild, not just a restart.
ARG REACT_APP_BACKEND_URL=http://localhost:8001
ARG REACT_APP_RAG_API_KEY=
ENV REACT_APP_BACKEND_URL=$REACT_APP_BACKEND_URL \
    REACT_APP_RAG_API_KEY=$REACT_APP_RAG_API_KEY \
    CI=false
RUN yarn build

# --- runtime stage -----------------------------------------------------------
# Serve the static bundle instead of running `craco start`: the CRA dev server
# is unminified, ships source maps and a websocket, and is explicitly not for
# production. The `unprivileged` image already runs as a non-root user.
FROM nginxinc/nginx-unprivileged:1.27-alpine

COPY --from=build /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000

# For hot-reload development use `make dev-frontend` (yarn start) on the host.
