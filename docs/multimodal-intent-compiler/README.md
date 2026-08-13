# Multimodal Intent Compiler - Implementation Handbook

This handbook is the build specification for a Mac-first prototype using the hardware currently available:

- MacBook
- Neurosity Crown for EEG
- OpenBCI Ganglion for EMG
- Built-in or iPhone camera
- Built-in microphone
- A software robot simulator until the SO-ARM101 arrives

The prototype must demonstrate a complete loop:

`human signals -> synchronized evidence -> confidence-scored intent -> deterministic safety decision -> simulated machine action -> outcome and correction`

## Read and execute in this order

1. [General system plan](00_GENERAL_SYSTEM.md)
2. [Local Mac setup](01_LOCAL_SETUP.md)
3. [Shared contracts](02_SHARED_CONTRACTS.md)
4. [Neurosity Crown adapter](adapters/01_NEUROSITY_CROWN_ADAPTER.md)
5. [OpenBCI Ganglion EMG adapter](adapters/02_OPENBCI_GANGLION_EMG_ADAPTER.md)
6. [Audio adapter](adapters/03_AUDIO_ADAPTER.md)
7. [Vision adapter](adapters/04_VISION_ADAPTER.md)
8. [Robot simulator adapter](adapters/05_ROBOT_SIMULATOR_ADAPTER.md)
9. [Event hub and synchronization runtime](runtime/01_EVENT_HUB_AND_SYNCHRONIZATION.md)
10. [Intent fusion runtime](runtime/02_INTENT_FUSION_RUNTIME.md)
11. [Safety gateway](runtime/03_SAFETY_GATEWAY.md)
12. [Session storage and replay](runtime/04_SESSION_STORAGE_AND_REPLAY.md)
13. [Developer console UI](ui/01_DEVELOPER_CONSOLE.md)
14. [Testing and evaluation](testing/01_TESTING_AND_EVALUATION.md)
15. [SO-ARM101 integration](roadmap/01_SO_ARM101_INTEGRATION.md)

## Operating principle

Every component is independently replaceable. Adapters never command a robot. Models never bypass the safety gateway. The robot consumes only an approved `ActionCommand` defined in the shared contracts.

## MVP definition of done

The first release is complete when:

- All five adapters run concurrently on one Mac.
- A session can be started and stopped from the UI.
- EEG, EMG, voice, vision, decisions, and simulator state share a normalized timeline.
- The user can request one of four tabletop objects using a constrained voice command.
- Vision can identify visible objects and estimate pointing/head-direction evidence.
- EMG can classify `rest`, `confirm`, and `cancel` for the primary user.
- EEG runs in shadow mode and produces quality/readiness features without affecting action.
- Fusion beats the voice-only baseline in a recorded evaluation.
- Ambiguous evidence causes `ASK_CONFIRMATION` or `HOLD`, never an automatic action.
- Cancel always overrides pending actions.
- Every decision is replayable with its evidence and model versions.

## Instructions to Codex

Treat each linked file as an implementation brief. Implement one file at a time, run its acceptance tests, and record completion in the repository's main `README.md`. Do not skip contracts or testing to reach the visual demo faster.
