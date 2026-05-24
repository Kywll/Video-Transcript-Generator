import queue
import threading
import time


JOB_QUEUE = queue.Queue()
JOB_RESULTS = {}  # job_id -> {status, result?, error?}

NUM_WORKERS = 2  # adjust (2–3 for small server)

def worker():
    while True:
        job_id, func, args = JOB_QUEUE.get()
        try:
            job = JOB_RESULTS.get(job_id)
            if job:
                job["status"] = "processing"
            result = func(*args)
            job = JOB_RESULTS.get(job_id)
            if job:
                job["status"] = "done"
                job["result"] = result
        except Exception as e:
            print(f"[JOB ERROR] {job_id}: {e}")
            job = JOB_RESULTS.get(job_id)
            if job:
                job["status"] = "failed"
                job["error"] = str(e)
        finally:
            JOB_QUEUE.task_done()

def cleanup_jobs():
    while True:
        time.sleep(1800)  # 30 minutes
        keys_to_delete = []

        for job_id, job in list(JOB_RESULTS.items()):
            if job.get("status") in ["done", "failed"]:
                keys_to_delete.append(job_id)

        for k in keys_to_delete:
            JOB_RESULTS.pop(k, None)


# start workers
for _ in range(NUM_WORKERS):
    threading.Thread(target=worker, daemon=True).start()


# start cleanup thread
threading.Thread(target=cleanup_jobs, daemon=True).start()


