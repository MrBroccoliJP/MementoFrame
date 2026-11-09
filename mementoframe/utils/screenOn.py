"""Request screen power through the sole GPIO owner: the display service."""
import urllib.request

request = urllib.request.Request("http://127.0.0.1:5001/screen/on", method="POST")
with urllib.request.urlopen(request, timeout=5) as response:
    print(response.read().decode())
