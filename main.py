import os
import tempfile
import time
import requests
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from flask import Flask, request

app = App(
    token=os.environ["SLACK_BOT_TOKEN"],
    signing_secret=os.environ["SLACK_SIGNING_SECRET"],
)

LTX_API_URL = os.environ.get("LTX_API_URL", "")
LTX_API_KEY = os.environ.get("LTX_API_KEY", "")


def generate_gif(prompt: str) -> bytes:
    """Generate a GIF from a text prompt using LTX 2.3 API."""
    # Submit generation request
    resp = requests.post(
        f"{LTX_API_URL}/generate",
        headers={"Authorization": f"Bearer {LTX_API_KEY}"},
        json={"prompt": prompt, "output_format": "gif"},
        timeout=30,
    )
    resp.raise_for_status()
    job = resp.json()
    job_id = job["id"]

    # Poll for result
    for _ in range(60):
        time.sleep(5)
        status_resp = requests.get(
            f"{LTX_API_URL}/jobs/{job_id}",
            headers={"Authorization": f"Bearer {LTX_API_KEY}"},
            timeout=10,
        )
        status_resp.raise_for_status()
        data = status_resp.json()
        if data["status"] == "completed":
            gif_url = data["output_url"]
            return requests.get(gif_url, timeout=30).content
        elif data["status"] == "failed":
            raise RuntimeError(f"LTX generation failed: {data.get('error')}")

    raise TimeoutError("LTX generation timed out")


@app.command("/gif")
def handle_gif_command(ack, respond, command, client):
    ack()
    prompt = command.get("text", "").strip()
    if not prompt:
        respond("Please provide a prompt: `/gif <your prompt>`")
        return

    respond(f"Generating GIF for: _{prompt}_ ...")

    try:
        gif_bytes = generate_gif(prompt)
        with tempfile.NamedTemporaryFile(suffix=".gif", delete=False) as f:
            f.write(gif_bytes)
            tmp_path = f.name

        client.files_upload_v2(
            channel=command["channel_id"],
            file=tmp_path,
            filename="generated.gif",
            initial_comment=f"*{prompt}*",
            thread_ts=command.get("thread_ts"),
        )
    except Exception as e:
        respond(f"Failed to generate GIF: {e}")


flask_app = Flask(__name__)
handler = SlackRequestHandler(app)


@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    return handler.handle(request)


@flask_app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}, 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)
