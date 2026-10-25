Add this to the project docker compose 
```yml
services:
  falkordb:
    image: falkordb/falkordb:latest
    container_name: falkordb
    ports:
      - "6379:6379"
      - "4001:3000"
    environment:
      FALKORDB_PASSWORD: ${FALKORDB_PASSWORD:?Set FALKORDB_PASSWORD in .env}
      REDIS_ARGS: "--requirepass ${FALKORDB_PASSWORD:?Set FALKORDB_PASSWORD in .env} --appendonly yes"
      FALKORDB_ARGS: "THREAD_COUNT 8 TIMEOUT_MAX 30000"
    volumes:
      - falkordb_data:/var/lib/falkordb/data
    restart: unless-stopped
    healthcheck:
      test:
        - CMD-SHELL
        - 'redis-cli -a "$${FALKORDB_PASSWORD}" ping 2>/dev/null | grep -q PONG'
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  falkordb_data:
    driver: local
```

Think Thoroughly and start the Agent Loop, and finally create a unslopped ASD-STE100 readme file for humans.

Yours truly,
Apoorv