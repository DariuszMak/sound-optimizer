docker-compose down --remove-orphans ; 
docker-compose build ; 
docker-compose up -d ; 

Start-Process "http://127.0.0.1:5005" ; 
