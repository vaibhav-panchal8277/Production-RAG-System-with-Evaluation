FROM node:20-alpine

WORKDIR /app

# Install deps first (better layer caching)
COPY package.json yarn.lock* ./
RUN yarn install --frozen-lockfile || yarn install

# Copy the rest
COPY . .

EXPOSE 3000

CMD ["yarn", "start"]
