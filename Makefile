dev: 
	docker compose build && docker compose up 

build-prod-image:
	docker compose -f unified-docker-compose.yml build  --build-arg COLDBREW_FRONTEND_API_URL=${COLDBREW_FRONTEND_API_URL} && docker compose -f unified-docker-compose.yml up -d

#prod:
#    cd frontend && npm install && npm run build && cd ..
#    mkdir backend/src/build
#    cp -r frontend/dist/* backend/src/build/
#    cd backend
#    source bin/activate && pip install -r requirements/base.txt && pip install -r requirements/pi.txt
#    fastapi dev brewserver/server.py --host 0.0.0.0



