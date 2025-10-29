FROM docker.io/library/node:20.19-alpine AS build-stage

# Check https://github.com/nodejs/docker-node/tree/b4117f9333da4138b03a546ec926ef50a31506c3#nodealpine to understand why libc6-compat might be needed.
RUN apk add --no-cache libc6-compat git

WORKDIR /app

COPY package.json yarn.lock ./

RUN yarn install --frozen-lockfile

COPY . .

ARG ENV=stage

RUN yarn build:${ENV}


FROM docker.io/library/nginx:alpine-slim

RUN <<EOF cat > /etc/nginx/conf.d/default.conf
server {
  listen 80;
  root /usr/share/nginx/html;
  location / {
    try_files \$uri \$uri/index.html /index.html =404;
  }
  error_page 404              /404.html;
  error_page 500 502 503 504  /50x.html;
}
EOF

COPY --from=build-stage /app/dist/ /usr/share/nginx/html/
