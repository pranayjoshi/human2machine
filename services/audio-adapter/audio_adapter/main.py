from __future__ import annotations

import argparse
import signal
import time

from intent_runtime.config import load_stacked_config

from audio_adapter.capture import AudioHardwareRuntime, list_sound_devices
from audio_adapter.mock import AudioMockRuntime, find_repo_root
from audio_adapter.publisher import BoundedAdapterPush, ListSink


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local audio intent adapter")
    parser.add_argument("--mock", action="store_true", default=True)
    parser.add_argument("--hardware", action="store_true")
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--duration-seconds", type=float, default=0.0)
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument(
        "--phrase",
        default=None,
        help="Operator transcript fallback when ASR is unavailable",
    )
    parser.add_argument(
        "--research-recording",
        action="store_true",
        default=False,
        help="Keep utterance PCM in memory for this session (opt-in; never streamed)",
    )
    return parser


def main(argv: list[str] | None = None, sink: BoundedAdapterPush | ListSink | None = None) -> int:
    args = build_parser().parse_args(argv)
    mock = not args.hardware
    config = load_stacked_config(find_repo_root() / "configs")
    endpoint = args.endpoint or config.get("runtime", {}).get("ports", {}).get(
        "adapter_push", "tcp://127.0.0.1:5555"
    )
    audio_cfg = config.get("audio", {})
    devices_cfg = config.get("devices", {}).get("audio", {})

    if args.list_devices:
        if mock:
            print("mock-fixture")
            return 0
        rows = list_sound_devices()
        if not rows:
            print("sounddevice is unavailable or no input devices were found")
            return 0
        for row in rows:
            print(row)
        return 0

    publisher = sink or BoundedAdapterPush(endpoint)
    stop = False

    def _halt(_signum=None, _frame=None) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _halt)
    signal.signal(signal.SIGTERM, _halt)

    runtime: AudioMockRuntime | AudioHardwareRuntime
    hardware: AudioHardwareRuntime | None = None
    try:
        if mock:
            runtime = AudioMockRuntime(model_id=str(audio_cfg.get("parser", "grammar_v1")))
        else:
            device_name = devices_cfg.get("device_name")
            sample_rate = int(
                devices_cfg.get("sample_rate_hz") or audio_cfg.get("sample_rate_hz") or 16000
            )
            hardware = AudioHardwareRuntime(
                sample_rate_hz=sample_rate,
                device_name=device_name,
                phrase=args.phrase,
                model_id=str(audio_cfg.get("parser", "grammar_v1")),
                preroll_ms=int(audio_cfg.get("preroll_ms", 250)),
                silence_end_ms=int(audio_cfg.get("silence_end_ms", 400)),
                max_utterance_ms=int(audio_cfg.get("max_utterance_ms", 4000)),
                research_recording=bool(args.research_recording),
            )
            try:
                hardware.start()
            except Exception as exc:
                publisher.send_event(
                    hardware._device_status("offline", f"failed to open microphone: {exc}")
                )
                return 1
            runtime = hardware

        started = time.monotonic()
        last_heartbeat = 0.0
        last_at = 0
        if mock and isinstance(runtime, AudioMockRuntime):
            last_at = max((int(row["at_ms"]) for row in runtime.utterances), default=0)
        while not stop:
            now = time.monotonic()
            if mock and isinstance(runtime, AudioMockRuntime):
                elapsed_ms = int((now - started) * 1000)
                for event in runtime.events_due(elapsed_ms):
                    publisher.send_event(event)
            else:
                assert isinstance(runtime, AudioHardwareRuntime)
                try:
                    polled = runtime.poll()
                except Exception as exc:
                    polled = [
                        runtime._device_status("degraded", f"microphone stream failure: {exc}")
                    ]
                for event in polled:
                    publisher.send_event(event)
            if now - last_heartbeat >= 2.0:
                publisher.send_event(runtime.heartbeat(now - started, publisher.dropped_count))
                last_heartbeat = now
            if args.duration_seconds > 0 and (now - started) >= args.duration_seconds:
                break
            if mock and args.duration_seconds == 0:
                elapsed_ms = int((now - started) * 1000)
                if elapsed_ms > last_at + 500:
                    time.sleep(0.2)
                    continue
            time.sleep(0.05)
        publisher.send_event(runtime.shutdown())
        return 0
    finally:
        if hardware is not None:
            hardware.stop()
        publisher.close()


if __name__ == "__main__":
    raise SystemExit(main())
