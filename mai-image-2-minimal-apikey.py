import os
import base64
import requests
from dotenv import load_dotenv
load_dotenv()

endpoint = os.environ["MAI_ENDPOINT"]
api_key = os.environ["MAI_API_KEY"]
deployment_name = os.environ["MAI_DEPLOYMENT_NAME"]

url = f"{endpoint}/mai/v1/images/generations"

payload = {
    "model": deployment_name,
    "prompt": "A photorealistic image of a mountain lake at sunrise",
    "width": 1024,
    "height": 1024,
}

response = requests.post(
    url,
    headers={
        "Content-Type": "application/json",
        "api-key": api_key,
    },
    json=payload,
)
response.raise_for_status()

result = response.json()

image_data = [
    output
    for output in result.get("data", [])
    if "b64_json" in output
]

if image_data:
    image_base64 = image_data[0]["b64_json"]
    output_path = "output.png"
    with open(output_path, "wb") as f:
        f.write(base64.b64decode(image_base64))
    print(f"Image saved to {output_path}")
else:
    print("Unexpected response format:", result)