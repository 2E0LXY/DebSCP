import threading
import time

from debscp.transfer_queue import TransferJob, TransferQueue, TransferState


def test_transfer_queue_completes() -> None:
    finished = threading.Event()
    seen = []

    def update(job):
        seen.append(job.state)
        if job.state in (TransferState.COMPLETE, TransferState.FAILED):
            finished.set()

    transfers = TransferQueue(update)
    transfers.submit(TransferJob("copy", lambda progress: progress(10, 10)))
    assert finished.wait(2)
    transfers.shutdown()
    assert TransferState.COMPLETE in seen


def test_shutdown_waits_for_active_transfer() -> None:
    release = threading.Event()
    started = threading.Event()
    transfers = TransferQueue()

    def operation(_progress):
        started.set()
        release.wait(2)

    transfers.submit(TransferJob("slow", operation))
    assert started.wait(1)
    assert transfers.active
    timer = threading.Timer(0.1, release.set)
    timer.start()
    before = time.monotonic()
    transfers.shutdown()
    assert time.monotonic() - before >= 0.08
    assert not transfers._worker.is_alive()
    assert not transfers.active
