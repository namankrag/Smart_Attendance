# Model weights are NOT bundled in this repo.
#
# Before building the worker image, place the ONNX weights here:
#   scrfd_10g_bnkps.onnx   (SCRFD detector, InsightFace)
#   arcface_r100.onnx      (ArcFace recognition, InsightFace — or an AdaFace ONNX export)
#   minifasnet.onnx        (passive PAD, MiniFASNet — or a CDCN ONNX export)
#   aasist.onnx            (voice anti-spoofing, AASIST ONNX export)
#
# See worker/README.md for sources. The build FAILS if any file is
# missing (Dockerfile.worker COPYs this directory), and the worker
# refuses to start ready (/readyz → 503) without them. Weights are
# never downloaded at runtime.
#
# ECAPA-TDNN (speechbrain/spkrec-ecapa-voxceleb) and pyannote
# diarization (pyannote/speaker-diarization-3.1) weights must likewise
# be baked into the image (model cache) at build time.
