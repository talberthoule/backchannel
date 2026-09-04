FROM node:24-alpine AS build
WORKDIR /app
# npm ci, not npm install, so the image resolves the committed lockfile
# exactly - the same tree CI tests and the desktop bundles ship (ALP-246).
# The lockfile is required, not optional: the old `package-lock.json*` glob
# tolerated its absence, which npm install would silently resolve around and
# npm ci cannot. Copy it unglobbed so a missing lockfile fails here, at COPY,
# instead of further down with a less obvious error.
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
