FROM node:25.3.0-slim
WORKDIR /app
COPY package.json ./
RUN npm i
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
