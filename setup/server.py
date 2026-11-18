"""Loopback setup interface for the bounded EmbeddedSim runner."""
import argparse
import base64
import binascii
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import mimetypes
import os
from pathlib import Path
import re
import signal
from tempfile import TemporaryDirectory
from threading import Lock, Thread
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from config import BODY_LIMITS, ENDPOINTS, PINS, ROOT, SetupError, default_config, validate
from elf import MAX_ELF_BYTES, validate_elf
from runner import build_example, run_job
from live import LiveSession

OUTPUT = Path(os.environ.get("EMBEDDEDSIM_ARTIFACTS", ROOT / "setup/out/jobs")).expanduser().resolve()
MAX_REQUEST = ((MAX_ELF_BYTES + 2) // 3) * 4 + 65536
JOB_ROUTE = re.compile(r"/jobs/([0-9a-f]{32})(?:/(recording\.csv|config\.json|events\.json|renode\.log))?")
LIVE_ROUTE = re.compile(r"/api/live/([0-9a-f]{32})")
STATIC = {
    "/": "setup/index.html", "/setup/": "setup/index.html",
    **{f"/setup/{file}": f"setup/{file}" for file in ("app.mjs", "style.css")},
    "/viewer/": "viewer/index.html",
    **{f"/viewer/{file}": f"viewer/{file}" for file in ("style.css", "viewer.mjs", "trace.mjs", "drawing.mjs", "live.mjs")},
    "/tests/robot/out/main.csv": "tests/robot/out/main.csv",
}


class Server(ThreadingHTTPServer):
    def __init__(self, port, example):
        self.live = None
        super().__init__(("127.0.0.1", port), Handler)
        self.example = example
        self.authorities = {f"{host}:{self.server_port}" for host in ("127.0.0.1", "localhost")}
        self.lock = Lock()
        self.jobs = {}
        self.busy = False

    def server_close(self):
        try:
            if self.live:
                self.live.close()
        finally:
            super().server_close()

    def submit(self, image, config, operation, seconds):
        with self.lock:
            if self.busy or (self.live and self.live.active()):
                return None
            if operation == "live":
                if self.live:
                    self.live.close()
                self.live = LiveSession(image, config, OUTPUT)
                return self.live.status()
            identifier = uuid4().hex
            self.jobs[identifier] = {"id": identifier, "state": "running", "operation": operation}
            self.busy = True
            Thread(target=self.execute, args=(identifier, image, config, operation, seconds), daemon=True).start()
            return dict(self.jobs[identifier])

    def execute(self, identifier, image, config, operation, seconds):
        try:
            result = run_job(image, config, OUTPUT / identifier, operation, seconds)
            update = {"state": "complete", "result": result}
        except Exception as error:
            update = {"state": "failed", "error": str(error)}
        finally:
            with self.lock:
                self.jobs[identifier].update(update)
                self.busy = False


class Handler(BaseHTTPRequestHandler):
    def log_request(self, code="-", size="-"):
        if self.command == "GET" and code == HTTPStatus.OK and LIVE_ROUTE.fullmatch(urlsplit(self.path).path):
            return
        super().log_request(code, size)

    def authorized(self):
        if self.headers.get("Host") not in self.server.authorities:
            self.send_error(HTTPStatus.FORBIDDEN, "Use the loopback address shown by the server.")
            return False
        return True

    def respond(self, status, data, mime):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; object-src 'none'")
        self.end_headers()
        self.wfile.write(data)

    def json(self, value, status=HTTPStatus.OK):
        self.respond(status, json.dumps(value, allow_nan=False).encode(), "application/json; charset=utf-8")

    def file(self, path, content_type=None):
        if not path.is_file():
            return self.json({"error": "File unavailable."}, HTTPStatus.NOT_FOUND)
        mime = content_type or mimetypes.guess_type(path)[0] or "application/octet-stream"
        self.respond(HTTPStatus.OK, path.read_bytes(), mime)

    def do_GET(self):
        if not self.authorized():
            return
        route = urlsplit(self.path).path
        if route in STATIC:
            return self.file(ROOT / STATIC[route])
        if route == "/api/preset":
            return self.json({"config": default_config(), "endpoints": ENDPOINTS, "pins": PINS, "limits": BODY_LIMITS})
        live_route = LIVE_ROUTE.fullmatch(route)
        if route == "/api/live" or live_route:
            with self.server.lock:
                live = self.server.live
            if route == "/api/live":
                return self.json({"id": live.id if live else None})
            if live and live.id == live_route[1]:
                query = parse_qs(urlsplit(self.path).query)
                cursor = query.get("cursor", [""])[0]
                if re.fullmatch(r"[0-9]{1,10}:[0-9]{1,4}", cursor):
                    generation, offset = map(int, cursor.split(":"))
                    return self.json(live.status(cursor=(generation, offset)))
                since = query.get("since", [""])[0]
                return self.json(live.status(int(since) if re.fullmatch(r"[0-9]{1,10}", since) else None))
            return self.json({"error": "That live session is no longer available. Saved recordings remain accessible."},
                             HTTPStatus.NOT_FOUND)
        match = JOB_ROUTE.fullmatch(route)
        if match:
            identifier, artifact = match.groups()
            if artifact == "renode.log":
                log = OUTPUT / identifier / artifact
                if log.is_file():
                    with log.open("rb") as handle:
                        handle.seek(max(0, log.stat().st_size - 262144))
                        return self.respond(HTTPStatus.OK, handle.read(262144), "text/plain; charset=utf-8")
            elif artifact:
                return self.file(OUTPUT / identifier / artifact)
            with self.server.lock:
                job = dict(self.server.jobs.get(identifier, {}))
            if job:
                return self.json(job)
        return self.json({"error": "Unknown route or job."}, HTTPStatus.NOT_FOUND)

    def do_POST(self):
        if not self.authorized():
            return
        if self.headers.get("Origin") != f"http://{self.headers.get('Host')}":
            return self.json({"error": "Requests must come from this local setup page."}, HTTPStatus.FORBIDDEN)
        route = urlsplit(self.path).path
        live_route = LIVE_ROUTE.fullmatch(route)
        if (route not in ("/api/jobs", "/api/config") and not live_route) or self.headers.get_content_type() != "application/json":
            return self.json({"error": "Expected a local JSON request."}, HTTPStatus.BAD_REQUEST)
        try:
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size <= (65536 if route == "/api/config" or live_route else MAX_REQUEST):
                raise SetupError("Select an ELF up to 16 MiB and a version 1 configuration.")
            job = json.loads(self.rfile.read(size))
            if route == "/api/config":
                return self.json(validate(job, discovery=True))
            if live_route:
                if not isinstance(job, dict) or job.get("action") not in ("start", "pause", "resume", "stop", "reset", "load", "fault"):
                    raise SetupError("Unknown live control.")
                response_code, update = HTTPStatus.ACCEPTED, None
                with self.server.lock:
                    live = self.server.live
                    if not live or live.id != live_route[1]:
                        response_code, update = HTTPStatus.NOT_FOUND, {"error": "Unknown live session."}
                    elif self.server.busy:
                        response_code, update = HTTPStatus.CONFLICT, {"error": "Wait for the offline job to finish."}
                    else:
                        try:
                            if job["action"] == "fault" and set(job) != {"action", "channel", "level"}:
                                raise SetupError("A fault command requires channel and level.")
                            value = {"channel": job["channel"], "level": job["level"]} if job["action"] == "fault" else job.get("right_Nms")
                            update = live.submit(job["action"], value)
                        except SetupError as error:
                            response_code, update = HTTPStatus.CONFLICT, {"error": str(error)}
                return self.json(update, response_code)
            if not isinstance(job, dict) or job.get("operation") not in ("discover", "run", "live"):
                raise SetupError("Specify discover, run or live.")
            operation = job["operation"]
            config = validate(job.get("config"), operation == "discover")
            seconds = job.get("seconds", 0.5)
            if operation == "discover" and (type(seconds) not in (int, float) or not 0.01 <= seconds <= 3):
                raise SetupError("Discovery virtual time must be between 0.01 and 3 seconds.")
            if job.get("firmware") == "example":
                image = self.server.example
            else:
                if not isinstance(job.get("firmware"), str):
                    raise SetupError("Select an ELF or choose the example ELF.")
                image = base64.b64decode(job["firmware"], validate=True)
            validate_elf(image)
        except (ValueError, TypeError, UnicodeError, binascii.Error, RecursionError, TimeoutError) as error:
            return self.json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        result = self.server.submit(image, config, operation, seconds)
        if result is None:
            return self.json({"error": "An emulator is reserved by a job or live session. Finish or stop it first."}, HTTPStatus.CONFLICT)
        return self.json(result, HTTPStatus.ACCEPTED)

    def setup(self):
        super().setup()
        self.connection.settimeout(15)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()
    def terminate(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate)
    try:
        with TemporaryDirectory(prefix="embeddedsim-example-") as temp:
            file = Path(temp) / "example.elf"
            build_example(file)
            image = file.read_bytes()
        with Server(args.port, image) as server:
            print(f"Open http://127.0.0.1:{server.server_port}/setup/", flush=True)
            server.serve_forever()
    except (SetupError, OSError, OverflowError) as error:
        parser.exit(1, f"{error}\n")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
