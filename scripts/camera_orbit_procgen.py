import os
import math
import argparse
import cv2
import numpy as np
import sys

# Robustly add VirtualHome's simulation package to sys.path, independent of CWD
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_SIM_PATHS = [
    os.path.join(_SCRIPT_DIR, '..', 'virtualhome'),
]

for _p in _SIM_PATHS:
    _abs = os.path.abspath(_p)
    if os.path.isdir(_abs) and _abs not in sys.path:
        sys.path.append(_abs)
from unity_simulator.comm_unity import UnityCommunication


def compute_scene_center(graph):
    centers = []
    for node in graph.get('nodes', []):
        bbox = node.get('bounding_box', {})
        center = bbox.get('center')
        if isinstance(center, dict):
            centers.append([center.get('x', 0.0), center.get('y', 0.0), center.get('z', 0.0)])
    if not centers:
        return [0.0, 0.0, 0.0]
    centers = np.array(centers, dtype=np.float32)
    mean = centers.mean(axis=0)
    return [float(mean[0]), float(mean[1]), float(mean[2])]


def ensure_dir(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def look_at_euler(from_pos, to_pos):
    # Compute yaw (Y) and pitch (X) in degrees to look at target point
    dx = to_pos[0] - from_pos[0]
    dy = to_pos[1] - from_pos[1]
    dz = to_pos[2] - from_pos[2]
    horiz_dist = math.sqrt(dx * dx + dz * dz) + 1e-6
    # Unity-like convention approximation: yaw around Y from +Z towards +X
    yaw_deg = math.degrees(math.atan2(dx, dz))
    pitch_deg = math.degrees(math.atan2(dy, horiz_dist))
    roll_deg = 0.0
    return [pitch_deg, yaw_deg, roll_deg]


def main():
    parser = argparse.ArgumentParser(description='Orbit a camera around a VirtualHome scene and record a video.')
    parser.add_argument('--seed', type=int, default=0, help='Procedural generation seed (if supported)')
    parser.add_argument('--scene_id', type=int, default=0, help='Fallback scene id to load when procedural gen is unavailable')
    parser.add_argument('--frames', type=int, default=300, help='Number of frames to record')
    parser.add_argument('--fps', type=int, default=20, help='Frames per second for output video')
    parser.add_argument('--radius', type=float, default=4.0, help='Orbit radius around scene center')
    parser.add_argument('--height', type=float, default=1.6, help='Camera height (Y)')
    parser.add_argument('--width', type=int, default=800, help='Output frame width')
    parser.add_argument('--height_px', type=int, default=450, help='Output frame height')
    parser.add_argument('--output', type=str, default='virtualhome/demo/output/camera_orbit.mp4', help='Output video path (mp4)')
    parser.add_argument('--save_images_dir', type=str, default='', help='If set, save each frame as an image (PNG) to this directory')
    parser.add_argument('--remove_terrain', action='store_true', help='Remove terrain for cleaner top-level visuals')
    args = parser.parse_args()

    if args.output:
        ensure_dir(os.path.dirname(args.output))
    if args.save_images_dir:
        ensure_dir(args.save_images_dir)

    print('Connecting to Unity... Make sure the simulator executable is running.')
    comm = UnityCommunication()

    # Try procedural generation if supported by the running executable, else fallback to reset(scene_id)
    used_procgen = False
    try:
        print(f'Generating procedural scene (seed={args.seed})...')
        success, msg = comm.procedural_generation(args.seed)
        if success:
            used_procgen = True
        else:
            print(f'Procedural generation not available or failed: {msg}. Falling back to scene {args.scene_id}.')
    except Exception as e:
        print(f'Procedural generation not supported: {e}. Falling back to scene {args.scene_id}.')

    if not used_procgen:
        comm.reset(args.scene_id)

    if args.remove_terrain:
        try:
            comm.remove_terrain()
        except Exception:
            pass

    print('Fetching environment graph to compute scene center...')
    s, graph = comm.environment_graph()
    if not s:
        raise RuntimeError('Failed to obtain environment graph.')
    center = compute_scene_center(graph)
    target = [center[0], center[1], center[2]]

    # Initial camera pose on orbit (theta=0)
    cam_pos = [center[0] + args.radius, args.height, center[2]]
    cam_rot = look_at_euler(cam_pos, target)

    print('Adding scene camera...')
    s, _ = comm.add_camera(position=cam_pos, rotation=cam_rot, field_view=60)
    if not s:
        raise RuntimeError('Failed to add camera.')
    s, camera_count = comm.camera_count()
    if not s or camera_count <= 0:
        raise RuntimeError('Failed to query camera count after adding camera.')
    cam_id = camera_count - 1

    print(f'Recording orbit: frames={args.frames}, fps={args.fps}, radius={args.radius}')
    writer = None
    if args.output:
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(args.output, fourcc, float(args.fps), (args.width, args.height_px))
        if not writer.isOpened():
            raise RuntimeError(f'Could not open VideoWriter for {args.output}')

    for i in range(args.frames):
        theta = (2.0 * math.pi) * (i / float(args.frames))
        cam_x = center[0] + args.radius * math.cos(theta)
        cam_z = center[2] + args.radius * math.sin(theta)
        cam_y = args.height
        cam_pos = [cam_x, cam_y, cam_z]
        cam_rot = look_at_euler(cam_pos, target)

        comm.update_camera(cam_id, position=cam_pos, rotation=cam_rot, field_view=60)
        s, images = comm.camera_image([cam_id], image_width=args.width, image_height=args.height_px)
        if not s or not images:
            if writer is not None:
                writer.release()
            raise RuntimeError('Failed to capture camera image.')
        frame_bgr = images[0]
        if frame_bgr.shape[1] != args.width or frame_bgr.shape[0] != args.height_px:
            frame_bgr = cv2.resize(frame_bgr, (args.width, args.height_px), interpolation=cv2.INTER_LINEAR)
        if writer is not None:
            writer.write(frame_bgr)
        if args.save_images_dir:
            out_path = os.path.join(args.save_images_dir, f"frame_{i:04d}.png")
            cv2.imwrite(out_path, frame_bgr)

    if writer is not None:
        writer.release()
    if args.output:
        print(f'Done. Video saved to: {args.output}')
    if args.save_images_dir:
        print(f'Frames saved to: {args.save_images_dir}')


if __name__ == '__main__':
    main()


