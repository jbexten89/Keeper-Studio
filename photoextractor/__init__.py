"""Standalone background-removal tool: extract subjects to transparent PNGs.

Kept separate from photocropper on purpose -- it carries a heavy model and
onnxruntime, so it ships as its own app rather than bloating the cropper.
"""
