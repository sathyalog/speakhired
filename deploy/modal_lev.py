"""Deploy LEV on your own Modal account (https://modal.com), protected by proxy auth.

    pip install modal && modal setup
    modal deploy deploy/modal_lev.py

The URL printed will look like https://<workspace>--lev-server-serve.modal.run
Create a proxy auth token in Modal (Settings -> Proxy Auth Tokens) and put it in .env as
MODAL_KEY (wk-...) and MODAL_SECRET (ws-...). Not run by the SpeakHired tests; adjust GPU/timeouts to your Modal plan.
"""
import subprocess

import modal

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git")
    .pip_install("lev[serve] @ git+https://github.com/InterfazeAI/lev#subdirectory=packages/lev")
)
weights = modal.Volume.from_name("lev-weights", create_if_missing=True)
app = modal.App("lev-server", image=image)


@app.function(gpu="T4", volumes={"/root/.cache/huggingface": weights}, requires_proxy_auth=True,
              scaledown_window=300, timeout=900)
@modal.web_server(port=8000, startup_timeout=600)
def serve():
    subprocess.Popen(["lev", "serve", "--checkpoint", "interfaze-ai/lev", "--host", "0.0.0.0", "--port", "8000"])
