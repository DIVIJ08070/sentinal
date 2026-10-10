# Frontend: build the Vite/React app, then serve the static bundle with nginx,
# which also reverse-proxies /api and /ws to the backend (same-origin, so the
# app's relative calls and the alerts WebSocket work unchanged in production).
FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
