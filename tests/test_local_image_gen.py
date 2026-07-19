import base64
import json

from arka.agent.local_image_gen import generate


def test_local_image_generation_uses_sd_api(monkeypatch, tmp_path):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return json.dumps({"images": [base64.b64encode(b"png").decode()]}).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())
    result = generate("a blue mountain", str(tmp_path / "out.png"))
    assert result["backend"] == "stable-diffusion-webui"
    assert (tmp_path / "out.png").read_bytes() == b"png"
