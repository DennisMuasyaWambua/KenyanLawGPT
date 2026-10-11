"""Download the speaker-diarization models into DEST, verifying SHA-256.

Run at image build time so the service never fetches model files at runtime.
"""
import hashlib
import io
import sys
import tarfile
import urllib.request
from pathlib import Path

BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
SEGMENTATION = (f"{BASE}/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2",
                "24615ee884c897d9d2ba09bb4d30da6bb1b15e685065962db5b02e76e4996488")
# The "recongition" spelling is the upstream release tag's.
EMBEDDING = (f"{BASE}/speaker-recongition-models/wespeaker_en_voxceleb_resnet34_LM.onnx",
             "e9848563da86f263117134dfd7ad63c92355b37de492b55e325400c9d9c39012")


def fetch(url: str, sha256: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as resp:
        data = resp.read()
    got = hashlib.sha256(data).hexdigest()
    if got != sha256:
        sys.exit(f"checksum mismatch for {url}: {got}")
    return data


def main(dest: str) -> None:
    out = Path(dest)
    out.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(fetch(*SEGMENTATION)), mode="r:bz2") as tar:
        member = tar.getmember("sherpa-onnx-pyannote-segmentation-3-0/model.onnx")
        (out / "segmentation.onnx").write_bytes(tar.extractfile(member).read())
    (out / "embedding.onnx").write_bytes(fetch(*EMBEDDING))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/opt/diarization")
