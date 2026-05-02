FROM node:22-alpine

WORKDIR /app

COPY package.json ./
RUN npm install

# Keep an immutable snapshot of the freshly installed node_modules. The runtime
# entrypoint copies it into /app/node_modules if the bind mount from the host is empty.
RUN cp -a /app/node_modules /opt/node_modules_baked

COPY . .

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 3000

ENV HOST=0.0.0.0 \
    PORT=3000 \
    CHOKIDAR_USEPOLLING=true \
    NUXT_TELEMETRY_DISABLED=1

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

# Shell form keeps sh as PID 1 wrapper, which is fine for dev;
# --no-fork prevents the CLI from double-forking a child process.
CMD ["sh", "-c", "node_modules/.bin/nuxt dev --host 0.0.0.0 --no-fork"]
