"""Registration, verification and rehashing share the password memory budget."""

from concurrent.futures import ThreadPoolExecutor, wait
from contextlib import nullcontext
from threading import Event, Lock
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.application import auth


def test_concurrent_password_work_is_bounded_and_releases_after_failure(monkeypatch):
    release = Event()
    occupied = Event()
    lock = Lock()
    active = peak = calls = 0

    def password_work(*args):
        nonlocal active, peak, calls
        with lock:
            active += 1
            peak = max(peak, active)
            calls += 1
            if active == 2:
                occupied.set()
        try:
            assert release.wait(5), "password workers did not finish"
            return "synthetic-hash"
        finally:
            with lock:
                active -= 1

    hasher = Mock(hash=password_work, verify=password_work)
    hasher.check_needs_rehash.return_value = True
    monkeypatch.setattr(auth, "PASSWORD_HASHER", hasher)
    monkeypatch.setattr(auth.AuthService, "_new_session", lambda *args: None)

    def request(index):
        session = Mock()
        session.begin.side_effect = nullcontext
        session.scalar.return_value = SimpleNamespace(password_hash="old-hash")
        service = auth.AuthService(session)
        if index % 2:
            service.login("synthetic@example.com", "synthetic password")
        else:
            service.register("synthetic@example.com", "synthetic password", "Test")

    with ThreadPoolExecutor(max_workers=6) as workers:
        futures = [workers.submit(request, i) for i in range(6)]
        try:
            assert occupied.wait(5)
            assert not wait(futures, timeout=0.1).done
            assert peak == 2
        finally:
            release.set()
        for future in futures:
            future.result(timeout=5)
    assert active == 0 and peak == 2 and calls == 9

    hasher.verify = Mock(side_effect=auth.VerificationError("synthetic failure"))
    session = Mock()
    session.begin.side_effect = nullcontext
    session.scalar.return_value = SimpleNamespace(password_hash="old-hash")
    with pytest.raises(auth.AuthenticationRequired):
        auth.AuthService(session).login("synthetic@example.com", "wrong password")
    acquired = 0
    try:
        for _ in range(2):
            assert auth.PASSWORD_WORK.acquire(blocking=False)
            acquired += 1
    finally:
        for _ in range(acquired):
            auth.PASSWORD_WORK.release()
