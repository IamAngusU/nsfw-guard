import io
import json
from pathlib import Path

from PIL import Image

from nsfw_guard.backend import Prediction
from nsfw_guard.bridge import BridgeServer, serve_stream
from nsfw_guard.contracts import BRIDGE_PROTOCOL
from nsfw_guard.policy import get_policy
from nsfw_guard.scanner import Scanner


class FakeBackend:
    @property
    def evidence(self) -> dict[str, object]:
        return {"id": "fake", "artifact_sha256": "0" * 64}

    def predict(self, image: Image.Image) -> Prediction:
        return Prediction(0.1, 0.9, 0.1, 0.2)


def make_server(root: Path) -> BridgeServer:
    scanner = Scanner(backend=FakeBackend(), policy=get_policy("balanced-v1"))
    return BridgeServer(scanner, [root])


def write_image(path: Path) -> None:
    Image.new("RGB", (20, 20), "white").save(path, format="PNG")


def test_bridge_scans_inside_root_without_echoing_path(tmp_path: Path) -> None:
    image_path = tmp_path / "image.png"
    write_image(image_path)
    response = make_server(tmp_path).handle(
        {
            "protocol": BRIDGE_PROTOCOL,
            "id": "request-1",
            "operation": "scan",
            "artifact": {"kind": "file", "path": str(image_path)},
            "policy": {"profile": "balanced-v1"},
        }
    )
    assert response["ok"] is True
    assert response["result"]["verdict"] == "ALLOW"
    assert str(image_path) not in json.dumps(response)


def test_bridge_denies_path_outside_root(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.png"
    write_image(outside)
    response = make_server(allowed).handle(
        {
            "protocol": BRIDGE_PROTOCOL,
            "id": "request-2",
            "operation": "scan",
            "artifact": {"kind": "file", "path": str(outside)},
        }
    )
    assert response["ok"] is False
    assert response["error"]["code"] == "path_outside_allowed_roots"


def test_bridge_rejects_unknown_protocol() -> None:
    response = make_server(Path.cwd()).handle(
        {"protocol": "unknown/v1", "id": "request-3", "operation": "health"}
    )
    assert response["ok"] is False
    assert response["error"]["code"] == "bridge_protocol_error"


def test_stream_returns_machine_readable_error_for_invalid_json(tmp_path: Path) -> None:
    output = io.StringIO()
    serve_stream(make_server(tmp_path), io.StringIO("not-json\n"), output)
    response = json.loads(output.getvalue())
    assert response["ok"] is False
    assert response["error"]["code"] == "bridge_protocol_error"


def test_health_exposes_capabilities_and_model_identity(tmp_path: Path) -> None:
    response = make_server(tmp_path).handle(
        {"protocol": BRIDGE_PROTOCOL, "id": "health-1", "operation": "health"}
    )
    assert response["ok"] is True
    assert "image.scan" in response["result"]["capabilities"]
    assert response["result"]["model"]["id"] == "fake"
