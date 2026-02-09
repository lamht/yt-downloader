# Queue Update Flow - Verified

## Architecture
```
Executor Thread                 Event Loop
(yt-dlp hooks)                 (FastAPI)
     ↓                              ↓
  my_hook()                   _monitor_update_queue_global()
     ↓                              ↓
queue.sync_q.put_nowait() ←→ queue.async_q.get() await
     ↓                              ↓
  janus.Queue (thread-safe bridge)
```

## Initialization Flow
1. **App Startup** (`lifespan()`)
   ```python
   downloader._update_queue = janus.Queue()  # Requires active event loop
   monitor_task = asyncio.create_task(_monitor_update_queue_global())
   ```
   - Janus queue created when event loop exists
   - Monitor task started immediately

2. **Download Request**
   - `/download` POST → `bg_download()` task created
   - `loop.run_in_executor(None, download_video, ...)`
   - At this point: `_update_queue` is already initialized

3. **In Executor Thread** (yt-dlp running)
   ```python
   # Inside download_video()
   sync_queue = _update_queue.sync_q if _update_queue else None
   progress_hooks = [functools.partial(my_hook, key=key, update_queue=sync_queue)]
   ```
   - Hook receives `.sync_q` (thread-safe side)
   - When yt-dlp calls hook:
     ```python
     update_queue.sync_q.put_nowait({...})  # Thread-safe, non-blocking
     ```

4. **In Event Loop** (monitor task)
   ```python
   async_queue = _update_queue.async_q  # Get async side
   update = await async_queue.get()      # Await on async queue
   await manager.broadcast({...})        # Send to all WebSocket clients
   ```
   - Monitor awaits directly on async queue
   - Wakes immediately when item arrives (no polling)
   - Broadcasts to all connected clients

## Key Points ✅

| Component | Usage | Why |
|-----------|-------|-----|
| `_update_queue` (Global) | `janus.Queue()` | Async/thread bridge |
| `.sync_q` (Thread Side) | In executor `my_hook()` | Thread-safe, non-blocking put |
| `.async_q` (Async Side) | In async monitor | Direct await support |
| `functools.partial()` | Pre-fills parameters | Captures `.sync_q` at download start |
| No Polling | Direct `await get()` | Instant wakeup when items arrive |
| No Timeouts | Infinite await | More responsive than event/sleep |

## Queue Lifetime

```
App Start: queue created, monitor started ↓
├─ Download 1: sync_q.put() ← my_hook() calls
├─ Download 2: sync_q.put() ← my_hook() calls  ← async_q.get() wakes
├─ Download 3: sync_q.put() ← my_hook() calls
└─ All updates: broadcast to WebSocket clients
App Stop: queue.close() + wait_closed()
```

## Error Handling

1. **Queue Not Initialized** 
   - Guard: `sync_queue = _update_queue.sync_q if _update_queue else None`
   - Hook checks: `if update_queue and key is not None:`
   - Result: Silent skip if queue unavailable

2. **Put Failure** (should not happen)
   - Try/except: `try: update_queue.sync_q.put_nowait(...)`
   - Logged: `logger.warning("Failed to put update in queue: %s", e)`
   - Non-fatal: Download continues, just no progress updates

3. **Monitor Task Failure**
   - Logged: `logger.error("Queue monitor error: %s", e)`
   - Stops: Monitor breaks out of while loop
   - Impact: No updates sent to WebSocket clients, but downloads continue

## Testing Verification

✅ **To verify this works:**
1. Start app: `ENV=local python app/main.py`
2. Paste YouTube URL, click Inspect
3. Click Download
4. Watch progress updates in real-time on client
5. Verify WebSocket connection established (`/ws`)
6. Confirm no polling (monitor only wakes on queue items)

Expected behavior:
- Progress updates appear instantly (not after 1-2 seconds)
- Multiple downloads simultaneously work independently
- WebSocket stays connected throughout
- No excessive CPU usage (no polling)
