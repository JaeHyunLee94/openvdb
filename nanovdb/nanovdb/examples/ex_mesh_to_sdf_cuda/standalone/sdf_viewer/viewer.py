#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""GPU sparse SDF viewer. Python standard library only; see README.md."""
import argparse
import ctypes as C
import http.server
import json
import math
import os
from pathlib import Path
import struct
import sys
import tempfile
import threading
import time
import webbrowser
import zlib

HERE = Path(__file__).resolve().parent


class Settings(C.Structure):
    _fields_ = [(k, C.c_float * 3) for k in ("eye", "target", "up", "color", "background")] + [
        (k, C.c_float) for k in ("fov", "orthoScale", "step", "iso", "density", "shell", "ao", "exposure", "clipPosition")
    ] + [(k, C.c_int32) for k in ("mode", "clipAxis", "orthographic", "transparent")]


class GridInfo(C.Structure):
    _fields_ = [(k, C.c_double * 3) for k in ("worldMin", "worldMax", "voxelSize")] + [
        (k, C.c_int32 * 3) for k in ("indexMin", "indexMax")
    ] + [(k, C.c_uint64) for k in ("activeVoxels", "gridBytes", "freeDeviceBytes")] + [("indexGrid", C.c_int32)]


def as_dict(value):
    return {name: list(getattr(value, name)) if issubclass(kind, C.Array) else getattr(value, name)
            for name, kind in value._fields_}


def validate_settings(data):
    if not isinstance(data, dict):
        raise ValueError("settings must be an object")
    result = Settings()
    for name, kind in Settings._fields_:
        value = data[name]
        if issubclass(kind, C.Array):
            if not isinstance(value, list) or len(value) != 3:
                raise ValueError(f"{name} must contain three numbers")
            values = [float(v) for v in value]
            if not all(math.isfinite(v) and abs(v) < 1e20 for v in values):
                raise ValueError(f"invalid {name}")
            setattr(result, name, kind(*values))
        else:
            v = float(value)
            if not math.isfinite(v) or abs(v) >= 1e20:
                raise ValueError(f"invalid {name}")
            if kind == C.c_int32 and v != int(v):
                raise ValueError(f"{name} must be an integer")
            setattr(result, name, int(v) if kind == C.c_int32 else v)
    if not (.05 <= result.step <= 1 and .001 <= result.shell <= 1000 and 0 <= result.density <= 100):
        raise ValueError("step must be .05–1, shell .001–1000, density 0–100")
    if not (1 <= result.fov <= 170 and result.orthoScale > 0 and -10 <= result.exposure <= 10 and 0 <= result.ao <= 2):
        raise ValueError("invalid camera or lighting settings")
    if result.mode not in range(6) or result.clipAxis not in range(-1, 3):
        raise ValueError("invalid mode / clipping axis")
    if result.orthographic not in (0, 1) or result.transparent not in (0, 1):
        raise ValueError("invalid projection / background setting")
    f = [result.target[i] - result.eye[i] for i in range(3)]
    cross = [f[1]*result.up[2]-f[2]*result.up[1], f[2]*result.up[0]-f[0]*result.up[2], f[0]*result.up[1]-f[1]*result.up[0]]
    if sum(v*v for v in cross) < 1e-20:
        raise ValueError("camera eye, target and up are degenerate")
    return result


class Renderer:
    def __init__(self, path, library, grid_index=0):
        self.lib = C.CDLL(str(library))
        self.lib.sdf_error.restype = C.c_char_p
        self.lib.sdf_open.argtypes = [C.c_char_p, C.c_int32, C.POINTER(GridInfo)]
        self.lib.sdf_open.restype = C.c_void_p
        self.lib.sdf_close.argtypes = [C.c_void_p]
        self.lib.sdf_close.restype = None
        self.lib.sdf_render.argtypes = [C.c_void_p, C.POINTER(Settings)] + [C.c_int32]*7 + [C.POINTER(C.c_uint8)]
        self.lib.sdf_render.restype = C.c_int
        self.lib.sdf_probe.argtypes = [C.c_void_p, C.c_int32, C.POINTER(C.c_int32), C.POINTER(C.c_float)]
        self.lib.sdf_probe.restype = C.c_int
        info = GridInfo()
        self.context = self.lib.sdf_open(os.fsencode(path), grid_index, C.byref(info))
        if not self.context:
            raise RuntimeError(self.error())
        self.info = as_dict(info)
        self.info.update(file=str(Path(path).resolve()), gridIndex=grid_index)
        self.lock = threading.Lock()

    def error(self):
        return self.lib.sdf_error().decode("utf-8", errors="replace")

    def close(self):
        if self.context:
            self.lib.sdf_close(self.context)
            self.context = None

    def defaults(self):
        lo, hi = self.info["worldMin"], self.info["worldMax"]
        center = [(a+b)/2 for a, b in zip(lo, hi)]
        radius = math.sqrt(sum((b-a)**2 for a, b in zip(lo, hi)))/2
        direction = [.55, .30, 1.0]
        length = math.sqrt(sum(v*v for v in direction))
        eye = [center[i] + direction[i]/length*radius*3.2 for i in range(3)]
        return dict(eye=eye, target=center, up=[0, 1, 0], color=[.055, .22, .68], background=[1, 1, 1],
                    fov=38, orthoScale=radius*2.3, step=.5, iso=0, density=2, shell=1,
                    ao=.6, exposure=0, clipPosition=(self.info["indexMin"][2]+self.info["indexMax"][2])/2,
                    mode=0, clipAxis=-1, orthographic=0, transparent=0)

    def tile(self, settings, width, height, x, y, tw, th, samples):
        pixels = (C.c_uint8 * (tw*th*4))()
        if not self.lib.sdf_render(self.context, C.byref(settings), width, height, x, y, tw, th, samples, pixels):
            raise RuntimeError(self.error())
        return bytes(pixels)

    def probe(self, positions):
        coords = (C.c_int32*(len(positions)*3))(*(v for p in positions for v in p))
        values = (C.c_float*len(positions))()
        with self.lock:
            if not self.lib.sdf_probe(self.context, len(positions), coords, values):
                raise RuntimeError(self.error())
        return list(values)

    def png(self, data, width, height, samples):
        settings = validate_settings(data)
        if any(isinstance(v, bool) or not isinstance(v, int) for v in (width, height, samples)):
            raise ValueError("image dimensions and samples must be integers")
        if not (1 <= width <= 16384 and 1 <= height <= 16384 and width*height <= 100_000_000 and 1 <= samples <= 256):
            raise ValueError("maximum image: 16384 per side, 100 MP, 256 samples")
        metadata = dict(format="mesh-sdf-viewer-v1", settings=data, width=width, height=height, samples=samples, grid=self.info)
        yield b"\x89PNG\r\n\x1a\n"
        yield png_chunk(b"IHDR", struct.pack(">2I5B", width, height, 8, 6, 0, 0, 0))
        yield png_chunk(b"sRGB", b"\x00")
        yield png_chunk(b"pHYs", struct.pack(">IIB", 11811, 11811, 1))  # 300 dpi
        yield png_chunk(b"tEXt", b"MeshSDF\x00" + json.dumps(metadata, ensure_ascii=True).encode("ascii"))
        compressor = zlib.compressobj(3)
        # A strip costs at most 4 MiB at 16K width; grid resolution is never changed.
        with self.lock:
            for y in range(0, height, 64):
                rows = min(64, height-y)
                pixels = self.tile(settings, width, height, 0, y, width, rows, samples)
                for row in range(rows):
                    compressed = compressor.compress(b"\x00"+pixels[row*width*4:(row+1)*width*4])
                    if compressed:
                        yield png_chunk(b"IDAT", compressed)
            tail = compressor.flush()
            if tail:
                yield png_chunk(b"IDAT", tail)
        yield png_chunk(b"IEND", b"")


def png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind+data) & 0xffffffff)


def render_file(renderer, filename, settings, width, height, samples):
    filename = Path(filename)
    filename.parent.mkdir(parents=True, exist_ok=True)
    # Failed renders never replace an existing completed figure.
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=filename.parent, suffix=".png.tmp", delete=False) as output:
            temp = Path(output.name)
            for chunk in renderer.png(settings, width, height, samples):
                output.write(chunk)
        temp.replace(filename)
    finally:
        if temp and temp.exists():
            temp.unlink()


def serve(renderer, settings, port, open_browser):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, code, body, mime):
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/":
                self.reply(200, (HERE/"index.html").read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/info":
                self.reply(200, json.dumps(dict(grid=renderer.info, settings=settings)).encode(), "application/json")
            else:
                self.reply(404, b"Not found", "text/plain")

        def do_POST(self):
            if self.path not in ("/render", "/export"):
                self.reply(404, b"Not found", "text/plain")
                return
            # Browser requests must be same-origin; server binds only to loopback.
            origin = self.headers.get("Origin")
            if origin and origin not in (f"http://127.0.0.1:{server.server_port}", f"http://localhost:{server.server_port}"):
                self.reply(403, b"Use the viewer's local URL", "text/plain")
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 65536:
                    raise ValueError("invalid request size")
                data = json.loads(self.rfile.read(length))
                width, height, samples = data["width"], data["height"], data["samples"]
                if self.path == "/render" and (width > 2048 or height > 2048 or samples > 16):
                    raise ValueError("use Export for large images")
                start = time.perf_counter()
                # Spooling avoids keeping paper-resolution images in server RAM.
                # Complete the render before HTTP 200 so CUDA errors reach the UI.
                with tempfile.SpooledTemporaryFile(max_size=4*1024*1024) as image:
                    for chunk in renderer.png(data["settings"], width, height, samples):
                        image.write(chunk)
                    size = image.tell()
                    image.seek(0)
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(size))
                    self.send_header("X-Render-Ms", str(round(1000*(time.perf_counter()-start), 1)))
                    self.end_headers()
                    while chunk := image.read(65536):
                        self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as exc:
                self.reply(400, str(exc).encode(), "text/plain; charset=utf-8")

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = False
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"Viewer: {url}  (Ctrl+C to stop)", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("grid", type=Path, help="MeshToSDF or float LevelSet .nvdb")
    parser.add_argument("--library", type=Path, default=HERE/"build"/"libsdf_renderer.so")
    parser.add_argument("--grid-index", type=int, default=0)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="open the local UI in your browser")
    parser.add_argument("--settings", type=Path, help="camera/settings JSON exported by the UI")
    parser.add_argument("--render", type=Path, help="render PNG without a browser or display")
    parser.add_argument("--width", type=int, default=3840)
    parser.add_argument("--height", type=int, default=2160)
    parser.add_argument("--samples", type=int, default=16)
    args = parser.parse_args()
    if not args.library.is_file():
        parser.error(f"Build the CUDA backend first; missing {args.library}")
    renderer = None
    try:
        start = time.perf_counter()
        renderer = Renderer(args.grid, args.library, args.grid_index)
        settings = renderer.defaults()
        if args.settings:
            data = json.loads(args.settings.read_text())
            settings.update(data.get("settings", data))
        validate_settings(settings)
        print(json.dumps(renderer.info, indent=2), flush=True)
        print(f"Loaded in {time.perf_counter()-start:.2f} s", flush=True)
        if args.render:
            start = time.perf_counter()
            render_file(renderer, args.render, settings, args.width, args.height, args.samples)
            print(f"Saved {args.render} ({args.width}×{args.height}, {args.samples} spp) in {time.perf_counter()-start:.2f} s")
        else:
            serve(renderer, settings, args.port, args.open)
    except (RuntimeError, ValueError, OSError, KeyError, TypeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        if renderer:
            renderer.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
