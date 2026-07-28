FROM nginx:1.27-alpine
COPY index.html guide.html pricing.json /usr/share/nginx/html/
COPY assets /usr/share/nginx/html/assets
EXPOSE 80
