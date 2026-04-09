import os
import base64
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from flask import Flask, flash, redirect, render_template, request, url_for
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------
_REQUIRED_ENV = ("MAI_ENDPOINT", "MAI_API_KEY", "MAI_DEPLOYMENT_NAME")
_missing = [k for k in _REQUIRED_ENV if not os.environ.get(k)]
if _missing:
    raise SystemExit(f"ERROR: Missing required environment variables: {', '.join(_missing)}")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
GENERATED_DIR = BASE_DIR / "static" / "generated"
DATA_DIR = BASE_DIR / "data"
GALLERY_INDEX = DATA_DIR / "gallery.json"

GENERATED_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)
if not GALLERY_INDEX.exists():
    GALLERY_INDEX.write_text("[]", encoding="utf-8")

# Resolution presets — dimensions enforced as integers to satisfy MAI API
PRESET_RESOLUTIONS = {
    "512": (512, 512),
    "1024": (1024, 1024),
}
CUSTOM_MIN, CUSTOM_MAX = 64, 2048

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__)
# Falls back to a per-process random key for local dev if not set in .env
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or os.urandom(24)


# ---------------------------------------------------------------------------
# MAI image generation service
# ---------------------------------------------------------------------------
def generate_image(prompt: str, width: int, height: int) -> bytes:
    """Call the MAI image generation API and return raw PNG bytes."""
    endpoint = os.environ["MAI_ENDPOINT"]
    api_key = os.environ["MAI_API_KEY"]
    deployment_name = os.environ["MAI_DEPLOYMENT_NAME"]

    url = f"{endpoint}/mai/v1/images/generations"
    payload = {
        "model": deployment_name,
        "prompt": prompt,
        "width": int(width),   # MAI API rejects string values — must be integers
        "height": int(height),
    }
    headers = {
        "Content-Type": "application/json",
        "api-key": api_key,
    }

    last_exc = None
    for attempt in range(3):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=120)
            resp.raise_for_status()
            break
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
        except requests.exceptions.HTTPError as exc:
            raise RuntimeError(
                f"MAI API error {resp.status_code}: {resp.text[:300]}"
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise RuntimeError(f"Network error contacting MAI API: {exc}") from exc
    else:
        raise RuntimeError(
            "MAI API timed out after 3 attempts. Please try again."
        ) from last_exc

    result = resp.json()
    image_data = [item for item in result.get("data", []) if "b64_json" in item]
    if not image_data:
        raise RuntimeError(f"Unexpected MAI response format: {result}")

    return base64.b64decode(image_data[0]["b64_json"])


# ---------------------------------------------------------------------------
# Gallery persistence
# ---------------------------------------------------------------------------
def load_gallery() -> list:
    try:
        return json.loads(GALLERY_INDEX.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def append_gallery_entry(entry: dict) -> None:
    items = load_gallery()
    items.append(entry)
    # Atomic write via temp file to avoid corrupt index on crash
    tmp = GALLERY_INDEX.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=2), encoding="utf-8")
    tmp.replace(GALLERY_INDEX)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    items = list(reversed(load_gallery()))
    return render_template("index.html", items=items)


@app.route("/generate", methods=["POST"])
def generate():
    prompt = request.form.get("prompt", "").strip()
    resolution = request.form.get("resolution", "512")

    if not prompt:
        flash("Please enter a prompt.", "error")
        return redirect(url_for("index"))

    if resolution in PRESET_RESOLUTIONS:
        width, height = PRESET_RESOLUTIONS[resolution]
    elif resolution == "custom":
        try:
            width = int(request.form.get("custom_width", ""))
            height = int(request.form.get("custom_height", ""))
        except (ValueError, TypeError):
            flash("Custom dimensions must be whole numbers.", "error")
            return redirect(url_for("index"))
        if not (CUSTOM_MIN <= width <= CUSTOM_MAX and CUSTOM_MIN <= height <= CUSTOM_MAX):
            flash(
                f"Custom dimensions must be between {CUSTOM_MIN} and {CUSTOM_MAX} pixels.",
                "error",
            )
            return redirect(url_for("index"))
    else:
        flash("Invalid resolution selection.", "error")
        return redirect(url_for("index"))

    try:
        image_bytes = generate_image(prompt, width, height)
    except RuntimeError as exc:
        flash(str(exc), "error")
        return redirect(url_for("index"))

    filename = (
        f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.png"
    )
    (GENERATED_DIR / filename).write_bytes(image_bytes)

    append_gallery_entry({
        "filename": filename,
        "prompt": prompt,
        "width": width,
        "height": height,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    flash("Image generated successfully.", "success")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
