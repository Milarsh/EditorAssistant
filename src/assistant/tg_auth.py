import os
import asyncio
import platform
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PasswordHashInvalidError

from pathlib import Path

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION_FILE = "./secrets/" + os.getenv("TG_SESSION", "telegram.session")

SUBMIT_TIMEOUT = float(os.getenv("TG_AUTH_SUBMIT_TIMEOUT", "10"))


_loop: asyncio.AbstractEventLoop | None = None
_loop_thread: threading.Thread | None = None

def _ensure_background_loop():
    global _loop, _loop_thread
    if _loop is not None:
        return _loop
    _loop = asyncio.new_event_loop()
    def _runner():
        asyncio.set_event_loop(_loop)
        _loop.run_forever()
    _loop_thread = threading.Thread(target=_runner, name="tg-auth-loop", daemon=True)
    _loop_thread.start()
    return _loop

def _submit(coroutine: "asyncio.coroutines", timeout: float = SUBMIT_TIMEOUT) -> Any:
    loop = _ensure_background_loop()
    fut = asyncio.run_coroutine_threadsafe(coroutine, loop)
    try:
        return fut.result(timeout=timeout)
    except TimeoutError as error:
        fut.cancel()
        raise TimeoutError(f"submit timeout after {timeout}s") from error

@dataclass
class AuthState:
    status: str = "unauthorized"  # unauthorized/pending/password_required/authorized/expired/error
    qr_url: Optional[str] = None
    expires_at: Optional[datetime] = None
    error: Optional[str] = None
    user: Optional[Dict[str, Any]] = None


class TelegramAuthManager:
    def __init__(self):
        self._client: Optional[TelegramClient] = None
        self._qr_login = None  # объект из client.qr_login()
        self._qr_task: Optional[asyncio.Task] = None
        self._state = AuthState()
        self._lock = asyncio.Lock()

    async def _disconnect_client(self):
        if self._client:
            try:
                await self._client.disconnect()
                try:
                    await asyncio.wait_for(self._client.disconnected, timeout=2.0)
                except asyncio.TimeoutError:
                    pass
                await asyncio.sleep(0)
            except Exception:
                pass
            finally:
                self._client = None

    async def _ensure_client(self) -> TelegramClient:
        if not API_ID or not API_HASH:
            raise RuntimeError("API_ID/API_HASH are not set")
        Path(os.path.dirname(SESSION_FILE)).mkdir(parents=True, exist_ok=True)
        if self._client is None:
            session_str = None
            try:
                session_str = Path(SESSION_FILE).read_text(encoding="utf-8").strip() or None
            except (FileNotFoundError, UnicodeDecodeError):
                pass
            self._client = TelegramClient(
                StringSession(session_str), API_ID, API_HASH,
                device_model=platform.node() + " " + platform.machine(),
                system_version=platform.system() + " " + platform.release(),
                app_version="1.0.0", system_lang_code="ru-RU", lang_code="ru"
            )
        if not self._client.is_connected():
            await self._client.connect()
        return self._client

    async def _authorized_user(self) -> Optional[Dict[str, Any]]:
        client = await self._ensure_client()
        if await client.is_user_authorized():
            me = await client.get_me()
            return {
                "id": me.id,
                "first_name": getattr(me, "first_name", None),
                "last_name": getattr(me, "last_name", None),
                "username": getattr(me, "username", None),
                "phone": getattr(me, "phone", None),
            }
        return None

    def _persist_session(self):
        try:
            if self._client and self._client.session:
                session_str = self._client.session.save()
                Path(SESSION_FILE).write_text(session_str, encoding="utf-8")
        except Exception:
            pass

    async def _watch_qr(self, qr_login):
        current_task = asyncio.current_task()
        try:
            await qr_login.wait()
            self._persist_session()
            self._state = AuthState(status="authorized", user=await self._authorized_user())
            await self._disconnect_client()
        except SessionPasswordNeededError:
            if self._qr_login is qr_login:
                self._state = AuthState(status="password_required")
        except asyncio.TimeoutError:
            if self._qr_login is qr_login:
                await self._disconnect_client()
                self._state = AuthState(status="expired")
        except asyncio.CancelledError:
            raise
        except Exception as exception:
            if self._qr_login is qr_login:
                message = str(exception) or exception.__class__.__name__
                self._state = AuthState(status="error", error=message)
        finally:
            if self._qr_login is qr_login:
                self._qr_login = None
            if self._qr_task is current_task:
                self._qr_task = None

    async def status(self) -> AuthState:
        async with self._lock:
            now = datetime.now(timezone.utc)
            if self._state.status == "pending" and self._state.expires_at and now >= self._state.expires_at:
                if self._qr_task and not self._qr_task.done():
                    self._qr_task.cancel()
                self._qr_task = None
                self._qr_login = None
                await self._disconnect_client()
                self._state = AuthState(status="expired")
                return self._state

            try:
                client = await self._ensure_client()
                if await client.is_user_authorized():
                    self._persist_session()
                    self._state = AuthState(status="authorized", user=await self._authorized_user())
                    await self._disconnect_client()
                    return self._state

                if self._state.status in {"pending", "password_required"}:
                    return self._state

                await self._disconnect_client()

                if self._state.status == "expired":
                    return self._state

                if self._state.status not in {"expired", "error"}:
                    self._state = AuthState(status="unauthorized")
                return self._state
            except Exception as exception:
                message = str(exception) or exception.__class__.__name__
                self._state = AuthState(status="error", error=message)
                return self._state

    async def start_qr(self, force: bool = False) -> AuthState:
        async with self._lock:
            client = await self._ensure_client()
            if await client.is_user_authorized() and not force:
                self._persist_session()
                self._state = AuthState(status="authorized", user=await self._authorized_user())
                return self._state

            if (
                    not force
                    and self._qr_login is not None
                    and self._state.status == "pending"
                    and self._state.expires_at
                    and datetime.now(timezone.utc) < self._state.expires_at
                    and self._state.qr_url
            ):
                return self._state

            self._qr_login = await client.qr_login()
            self._state = AuthState(
                status="pending",
                qr_url=self._qr_login.url,
                expires_at=self._qr_login.expires,
            )
            if self._qr_task and not self._qr_task.done():
                self._qr_task.cancel()
            self._qr_task = asyncio.create_task(self._watch_qr(self._qr_login))
            return self._state

    async def submit_password(self, password: str) -> AuthState:
        async with self._lock:
            if self._state.status != "password_required":
                self._state = AuthState(status="unauthorized", error="2fa_not_requested")
                return self._state

            client = await self._ensure_client()
            try:
                await client.sign_in(password=password)
                self._persist_session()
                self._qr_login = None
                if self._qr_task and not self._qr_task.done():
                    self._qr_task.cancel()
                self._qr_task = None
                self._state = AuthState(status="authorized", user=await self._authorized_user())
                return self._state
            except PasswordHashInvalidError:
                self._state = AuthState(status="password_required", error="bad_password")
                return self._state
            except Exception as exception:
                message = str(exception) or exception.__class__.__name__
                self._state = AuthState(status="error", error=message)
                return self._state

    async def logout(self) -> AuthState:
        async with self._lock:
            try:
                client = await self._ensure_client()
                if not client.is_connected():
                    await client.connect()
                try:
                    await client.log_out()
                finally:
                    await self._disconnect_client()
                    try:
                        Path(SESSION_FILE).unlink(missing_ok=True)
                    except Exception:
                        pass
            except Exception:
                pass
            if self._qr_task and not self._qr_task.done():
                self._qr_task.cancel()
            self._qr_task = None
            self._qr_login = None
            self._state = AuthState(status="unauthorized")
            return self._state


_auth_manager = TelegramAuthManager()


def start_qr_sync(force: bool = False) -> Dict[str, Any]:
    state = _submit(_auth_manager.start_qr(force=force))
    return _to_dict(state)


def status_sync() -> Dict[str, Any]:
    state = _submit(_auth_manager.status())
    return _to_dict(state)


def submit_password_sync(password: str) -> Dict[str, Any]:
    state = _submit(_auth_manager.submit_password(password))
    return _to_dict(state)


def logout_sync() -> Dict[str, Any]:
    state = _submit(_auth_manager.logout())
    return _to_dict(state)


def _to_dict(state: AuthState) -> Dict[str, Any]:
    return {
        "status": state.status,
        "qr_url": state.qr_url,
        "expires_at": state.expires_at,
        "error": state.error,
        "user": state.user,
    }