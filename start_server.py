import http.server
import socketserver
import webbrowser
import sys

PORT = 8000
Handler = http.server.SimpleHTTPRequestHandler

# Allow port customization via command line arg
if len(sys.argv) > 1:
    try:
        PORT = int(sys.argv[1])
    except ValueError:
        pass

print(f"Starting Westfield Newmarket Gravity Simulation Portal local server...")
print(f"URL: http://localhost:{PORT}")
print("Press Ctrl+C to stop the server.")

# Open the user's default browser to the local server URL
webbrowser.open(f"http://localhost:{PORT}")

# Start the server
socketserver.TCPServer.allow_reuse_address = True
try:
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        httpd.serve_forever()
except KeyboardInterrupt:
    print("\nServer stopped.")
except Exception as e:
    print(f"\nError starting server: {e}")
