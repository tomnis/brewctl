dev: 
	docker compose build && docker compose up 

prod:
	docker compose -f unified-docker-compose.yml build  --build-arg COLDBREW_FRONTEND_API_URL=${COLDBREW_FRONTEND_API_URL} && docker compose -f unified-docker-compose.yml up -d

