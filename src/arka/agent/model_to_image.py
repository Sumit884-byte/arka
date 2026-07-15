"""Render a 3D mesh to a transparent PNG and remove residual background."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path


def render_model(source: str, output: str, *, size: int = 1024, remove_bg: bool = True) -> Path:
    src = Path(source).expanduser().resolve()
    dest = Path(output).expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(f"3D model not found: {src}")
    blender = shutil.which("blender")
    if not blender:
        raise RuntimeError("3D rendering requires Blender: install Blender and ensure `blender` is on PATH")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="arka-model-render-") as tmp:
        script = Path(tmp) / "render.py"
        script.write_text(_blender_script(src, dest, size), encoding="utf-8")
        proc = subprocess.run([blender, "--background", "--python", str(script)], capture_output=True, text=True, timeout=180, check=False)
        if proc.returncode != 0 or not dest.is_file():
            raise RuntimeError(f"Blender render failed: {(proc.stderr or proc.stdout)[-1000:]}")
    if remove_bg:
        from arka.agent.background_remove import remove_background
        return remove_background(str(dest), str(dest))
    return dest


def _blender_script(src: Path, dest: Path, size: int) -> str:
    src_q, dest_q = repr(str(src)), repr(str(dest))
    return f'''import bpy, math
from mathutils import Vector
bpy.ops.wm.read_factory_settings(use_empty=True)
path={src_q}
ext=path.lower().rsplit('.',1)[-1]
if ext == 'obj': bpy.ops.wm.obj_import(filepath=path)
elif ext == 'stl': bpy.ops.wm.stl_import(filepath=path)
elif ext in ('glb','gltf'): bpy.ops.import_scene.gltf(filepath=path)
else: raise RuntimeError('Unsupported mesh format: '+ext)
objs=[o for o in bpy.context.scene.objects if o.type == 'MESH']
if not objs: raise RuntimeError('model contains no mesh')
for o in objs: o.select_set(True)
bpy.context.view_layer.objects.active=objs[0]
bpy.ops.object.join()
obj=bpy.context.object
obj.location=(0,0,0)
obj.rotation_euler=(math.radians(8),0,math.radians(-18))
bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
obj.dimensions=(2.8,2.8,2.8)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
mat=bpy.data.materials.new('ArkaMaterial'); mat.diffuse_color=(0.18,0.42,0.95,1); obj.data.materials.append(mat)
camera_data=bpy.data.cameras.new('Camera'); camera=bpy.data.objects.new('Camera', camera_data); bpy.context.collection.objects.link(camera); bpy.context.scene.camera=camera
camera.location=(4,-4,3); camera.rotation_euler=(math.radians(67),0,math.radians(45))
light_data=bpy.data.lights.new('Key','AREA'); light_data.energy=900; light_data.shape='DISK'; light_data.size=5; light=bpy.data.objects.new('Key',light_data); bpy.context.collection.objects.link(light); light.location=(3,-4,5)
scene=bpy.context.scene; scene.render.engine='BLENDER_EEVEE_NEXT'; scene.render.resolution_x={size}; scene.render.resolution_y={size}; scene.render.resolution_percentage=100; scene.render.image_settings.file_format='PNG'; scene.render.image_settings.color_mode='RGBA'; scene.render.film_transparent=True; scene.render.filepath={dest_q}; bpy.ops.render.render(write_still=True)
'''


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka model-to-image")
    parser.add_argument("source")
    parser.add_argument("--output", required=True)
    parser.add_argument("--size", type=int, default=1024)
    parser.add_argument("--keep-background", action="store_true")
    args = parser.parse_args(argv)
    try:
        print(render_model(args.source, args.output, size=max(128, min(args.size, 4096)), remove_bg=not args.keep_background))
    except (FileNotFoundError, RuntimeError, OSError) as exc:
        parser.error(str(exc))
    return 0
