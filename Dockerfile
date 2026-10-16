FROM node:22-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY tsconfig.json ./
COPY src ./src
RUN npm run build

VOLUME ["/app/output", "/app/dedup"]

CMD ["npm", "run", "scrape"]
