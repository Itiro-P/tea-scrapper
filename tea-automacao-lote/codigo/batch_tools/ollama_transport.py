"""Streaming com limite total; uma requisição por chamada de transporte."""
from __future__ import annotations

import http.client
import json
import socket
import threading
import time
from urllib.parse import urlsplit


class OllamaRequestError(RuntimeError):
    def __init__(self, message, partial_response=None, status=None):
        super().__init__(message)
        self.partial_response = partial_response
        self.status = status


class OllamaDeadlineError(OllamaRequestError):
    pass


def stream_chat(base_url, body, timeout, on_progress=None, progress_interval=10, cancel_event=None):
    """Recebe NDJSON até done=true; o relógio também limita streams ativos."""
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Endpoint Ollama deve ser uma URL http(s) válida.")
    if timeout <= 0 or progress_interval <= 0:
        raise ValueError("Timeout e intervalo de progresso devem ser positivos.")
    cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    connection = cls(parsed.hostname, parsed.port, timeout=min(timeout, 10))
    started = time.monotonic()
    expired = threading.Event()
    finished = threading.Event()
    socket_holder = []
    pieces = []
    stats = {"content_chars": 0, "thinking_chars": 0}

    def partial():
        return {"done": False, "message": {"role": "assistant", "content": "".join(pieces)},
                **stats, "client_elapsed_seconds": time.monotonic() - started}

    def abort():
        expired.set()
        sock = socket_holder[0] if socket_holder else connection.sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def heartbeat():
        previous = time.monotonic()
        while not finished.wait(min(progress_interval, 0.25)):
            if cancel_event is not None and cancel_event.is_set():
                abort()
                return
            if on_progress and time.monotonic() - previous >= progress_interval:
                on_progress({"elapsed_seconds": time.monotonic() - started, **stats})
                previous = time.monotonic()

    timer = threading.Timer(timeout, abort)
    timer.daemon = True
    timer.start()
    notifier = threading.Thread(target=heartbeat, daemon=True)
    notifier.start()
    response = None
    try:
        connection.connect()
        socket_holder.append(connection.sock)
        if expired.is_set():
            raise OllamaDeadlineError(f"Geração excedeu {timeout:g} s; chamada encerrada.", partial())
        # O timer acima é o limite total. Este também limita uma leitura ociosa.
        connection.sock.settimeout(timeout)
        payload = {**body, "stream": True}
        path = parsed.path.rstrip("/") + "/api/chat"
        connection.request("POST", path, json.dumps(payload, ensure_ascii=False).encode(),
                           {"Content-Type": "application/json", "Accept": "application/x-ndjson"})
        response = connection.getresponse()
        if response.status >= 400:
            detail = response.read(8192).decode(errors="replace")
            raise OllamaRequestError(f"Ollama HTTP {response.status}: {detail[:500]}", partial(), response.status)
        while not expired.is_set():
            line = response.readline()
            if not line:
                break
            if not line.strip():
                continue
            try:
                chunk = json.loads(line)
            except ValueError as exc:
                raise OllamaRequestError("Stream Ollama contém uma linha JSON inválida.", partial()) from exc
            if not isinstance(chunk, dict):
                raise OllamaRequestError("Objeto inesperado no stream Ollama.", partial())
            if chunk.get("error"):
                raise OllamaRequestError(f"Ollama: {chunk['error']}", partial())
            message = chunk.get("message") or {}
            if not isinstance(message, dict):
                raise OllamaRequestError("Mensagem inesperada no stream Ollama.", partial())
            content = message.get("content") or ""
            thinking = message.get("thinking") or ""
            if not isinstance(content, str) or not isinstance(thinking, str):
                raise OllamaRequestError("Conteúdo inesperado no stream Ollama.", partial())
            pieces.append(content)
            stats["content_chars"] += len(content)
            stats["thinking_chars"] += len(thinking)
            if chunk.get("done"):
                if expired.is_set():
                    break
                return {**chunk, "message": {"role": message.get("role", "assistant"), "content": "".join(pieces)},
                        **stats, "client_elapsed_seconds": time.monotonic() - started}
        if expired.is_set():
            raise OllamaDeadlineError(f"Geração excedeu {timeout:g} s; chamada encerrada.", partial())
        raise OllamaRequestError("Conexão encerrada antes de done=true.", partial())
    except (OSError, http.client.HTTPException) as exc:
        if expired.is_set() or isinstance(exc, TimeoutError):
            raise OllamaDeadlineError(f"Geração excedeu o limite de espera ({timeout:g} s).", partial()) from exc
        raise OllamaRequestError(f"Falha de conexão com Ollama: {exc}.", partial()) from exc
    finally:
        finished.set()
        timer.cancel()
        if response is not None:
            response.close()
        connection.close()
        notifier.join(timeout=0.2)
