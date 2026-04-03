#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, HTTPServer
import logging

class SimpleRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        logging.info("GET request received, path: %s", self.path)
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        response_text = f"Received GET request for path: {self.path}"
        self.wfile.write(response_text.encode("utf-8"))

    def do_POST(self):
        content_length = int(self.headers['Content-Length']) # Get the size of data
        post_data = self.rfile.read(content_length) # Get the data itself
        logging.info("POST request received")
        #print(f"Received POST data: {post_data.decode('utf-8')}") # Print the received text to console
        print(f"Received POST data: {post_data}") # Print the received text to console

        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        response_text = f"Received POST data"
        #response_text = f"Received POST data: {post_data.decode('utf-8')}"
        self.wfile.write(response_text.encode("utf-8"))

def run(server_class=HTTPServer, handler_class=SimpleRequestHandler, port=8000):
    logging.basicConfig(level=logging.INFO)
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    logging.info(f"Server starting on port {port}...\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()
    logging.info("Server stopping.")

if __name__ == "__main__":
    run()