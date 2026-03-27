import os
import subprocess
import tempfile
import time

import requests
from flask import Flask, request
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler

app = App(
    token=os.environ["SLACK_BOT_TOKEN"],
    signing_secret=os.environ["SLACK_SIGNING_SECRET"],
)

LTX_API_URL = "https://api.ltx.video/v1"
LTX_API_KEY = os.environ["LTX_API_KEY"]


def generate_gif(prompt: str) -> str:
    """Generate a GIF from a text prompt using LTX 2.3 API. Returns path to temp GIF file."""
    # Submit generation request
    resp = requests.post(
        f"{LTX_API_URL}/text-to-video",
        headers={"Authorization": f"Bearer {LTX_API_KEY}"},
        json={
            "prompt": prompt,
            "duration": 6,
            "resolution": "1080p",
            "aspect_ratio": "16:9",
            "fps": 25,
            "generate_audio": False,
        },
        timeout=30,
    )
    resp.raise_for_status()
    job = resp.json()
    job_id = job["id"]

    # Poll until complete
    for _ in range(60):
        time.sleep(5)
        status_resp = requests.get(
            f"{LTX_API_URL}/tasks/{job_id}",
            headers={"Authorization": f"Bearer {LTX_API_KEY}"},
            timeout=10,
        )
        status_resp.raise_for_status()
        data = status_resp.json()
        status = data.get("status")
        if status == "SUCCESS":
            video_url = data["output"]["url"]
            break
        elif status == "FAILED":
            raise RuntimeError(f"LTX generation failed: {data.get('error')}")
    else:
        raise TimeoutError("LTX generation timed out after 5 minutes")

    # Download MP4
    mp4_resp = requests.get(video_url, timeout=60)
    mp4_resp.raise_for_status()

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        f.write(mp4_resp.content)
        mp4_path = f.name

    # Convert MP4 → GIF using ffmpeg
    gif_path = mp4_path.replace(".mp4", ".gif")
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", mp4_path,
            "-vf", "fps=15,scale=480:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
            "-loop", "0",
            gif_path,
        ],
        check=True,
        capture_output=True,
    )
    os.unlink(mp4_path)
    return gif_path


def post_gif(client, channel: str, prompt: str, thread_ts: str | None = None):
    gif_path = generate_gif(prompt)
    try:
        client.files_upload_v2(
            channel=channel,
            file=gif_path,
            filename="generated.gif",
            initial_comment=f"*{prompt}*",
            thread_ts=thread_ts,
        )
    finally:
        os.unlink(gif_path)


# Slash command: /gif <prompt>
@app.command("/gif")
def handle_gif_command(ack, respond, command, client):
    ack()
    prompt = command.get("text", "").strip()
    if not prompt:
        respond("Usage: `/gif <your prompt>`")
        return

    respond(f"Generating GIF for: _{prompt}_ ...")
    try:
        post_gif(client, command["channel_id"], prompt, thread_ts=command.get("thread_ts"))
    except Exception as e:
        respond(f"Failed to generate GIF: {e}")


# Message shortcut: right-click a message → "Generate GIF reply"
@app.shortcut("generate_gif_reply")
def handle_gif_shortcut(ack, shortcut, client):
    ack()
    message = shortcut.get("message", {})
    channel_id = shortcut["channel"]["id"]
    thread_ts = message.get("thread_ts") or message.get("ts")
    # Use the message text as the prompt
    prompt = message.get("text", "").strip()[:500]
    if not prompt:
        client.chat_postEphemeral(
            channel=channel_id,
            user=shortcut["user"]["id"],
            text="Could not extract prompt from message.",
        )
        return

    client.chat_postEphemeral(
        channel=channel_id,
        user=shortcut["user"]["id"],
        text=f"Generating GIF for: _{prompt}_ ...",
    )
    try:
        post_gif(client, channel_id, prompt, thread_ts=thread_ts)
    except Exception as e:
        client.chat_postEphemeral(
            channel=channel_id,
            user=shortcut["user"]["id"],
            text=f"Failed to generate GIF: {e}",
        )


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
