from pathlib import Path

from nsfw_guard import OnnxBackend, Scanner, get_policy


def main() -> None:
    backend = OnnxBackend(provider="cpu")
    scanner = Scanner(backend=backend, policy=get_policy("balanced-v1"))
    result = scanner.scan_path(Path("image.jpg"))
    print(result.to_dict())


if __name__ == "__main__":
    main()
