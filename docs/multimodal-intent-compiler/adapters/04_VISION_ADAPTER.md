# Vision Adapter

## Goal

Identify tabletop objects and estimate which object a user is indicating through hand pointing and coarse head direction using one built-in, USB, or iPhone camera.

This adapter does not claim eye-gaze tracking.

## Technology

- Python
- OpenCV
- MediaPipe Hands/Pose/Face Landmarker as appropriate
- ArUco/AprilTag markers or controlled color segmentation for the first reliable object detector
- Optional learned detector after the closed loop works
- ZeroMQ and shared contracts

## Physical setup

- Fixed camera with the complete table visible.
- Four lightweight objects with distinct markers or colors.
- Printed table calibration markers at known positions.
- Consistent lighting for the initial benchmark.
- A privacy-aware framing that avoids unnecessary background capture.

## Implementation steps

### 1. Camera acquisition

- Enumerate cameras and store the selected device.
- Start at 1280x720 and 30 FPS, then reduce if processing cannot stay real time.
- Capture on a dedicated thread into a latest-frame buffer.
- Timestamp frames immediately.
- Drop old frames rather than increasing latency.

### 2. Camera calibration

Provide a guided calibration that records:

- Image resolution
- Optional lens intrinsics
- Table plane/homography
- Workspace polygon
- Known marker dimensions

Store calibration with camera identifier and resolution. Refuse to load calibration at a different resolution without an explicit transform.

### 3. Object detection and tracking

MVP approach:

1. Detect ArUco/AprilTag marker or controlled color.
2. Assign stable `object_id`.
3. Estimate bounding box and table-plane center.
4. Track across frames.
5. Mark an object stale after a configured absence.

Do not begin with open-world object recognition. Reliability in a constrained scene is more valuable for proving fusion.

### 4. Hand pointing

- Detect hand landmarks.
- Construct a pointing ray using index MCP to fingertip or another validated landmark pairing.
- Intersect the ray with the table plane in image/table coordinates.
- Score objects by distance from the intersection and directional consistency.
- Smooth candidate scores across several frames.
- Return no candidate when the hand is not confidently pointing.

### 5. Head direction

- Estimate coarse yaw/pitch from face landmarks when a face is visible.
- Project only a broad directional cone.
- Use head direction as weak supporting evidence, not a decisive target selector.
- Label the feature `head_direction`, never `gaze`.

### 6. Quality

Report:

- Frame age
- Camera FPS
- Detector confidence
- Hand landmark confidence
- Calibration availability
- Lighting/exposure warnings if detectable
- Occlusion/staleness

### 7. Privacy modes

- `features_only`: do not persist video.
- `research_recording`: store synchronized MP4 with explicit consent.
- Blur or exclude background regions when practical.
- Never record automatically before a session starts.

### 8. Mock mode

Replay prerecorded video or emit deterministic object/pointing fixtures. Include object disappearance, two close targets, occlusion, camera freeze, and incorrect calibration.

## Outputs

- `vision.objects`
- `vision.hands`
- `vision.head_direction`
- `device.status`
- `service.heartbeat`

Publish object-level events at 10-15 Hz even if camera capture is 30 FPS. The fusion runtime does not need every frame.

## Acceptance criteria

- Four marked objects have at least 95% detection recall in the defined setup.
- Stable IDs persist during small movements.
- Pointing target top-1 accuracy is at least 85% across 100 trials.
- Camera-to-feature p95 latency is under 200 ms.
- Frozen camera is detected within one second.
- No target is emitted when hand confidence is below threshold.
- A calibration mismatch fails explicitly.

## Instructions to Codex

Build the marker-based detector and prerecorded-video test suite first. Add learned detection only behind a common detector interface after the benchmark is stable.
