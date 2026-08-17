import threading

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

