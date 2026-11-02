#!/usr/bin/env pvpython
# ==============================================================================
# Comprehensive ParaView Automated Postprocessing & Pipeline Generator
# Designed for WAAM Arc Case (OpenFOAM 2412 / beamWeldFoam)
#
# Workflows supported:
#   1. Headless CLI:
#      /Applications/ParaView-5.13.3.app/Contents/bin/pvpython postprocess_paraview.py
#      or 'pvpython postprocess_paraview.py' (Linux / i9 Workstation)
#   2. ParaView GUI Python Shell:
#      View -> Python Shell -> Run Script -> postprocess_paraview.py
#   3. Instant GUI State Restoration:
#      File -> Load State... -> waam_visualization.pvsm
# ==============================================================================

import os
import sys
import csv
from paraview.simple import *

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# ------------------------------------------------------------------------------
# 1. Path & Setup
# ------------------------------------------------------------------------------
case_dir = os.path.dirname(os.path.abspath(__file__))
foam_file = os.path.join(case_dir, "waam_arc.foam")
output_dir = os.path.join(case_dir, "postprocessing_visuals")
os.makedirs(output_dir, exist_ok=True)

if not os.path.exists(foam_file):
    with open(foam_file, 'w') as f:
        pass

print("================================================================")
print(" Comprehensive WAAM ParaView Postprocessing Generator")
print(f" Case Directory:    {case_dir}")
print(f" Output Directory:  {output_dir}")
print("================================================================")

paraview.simple._DisableFirstRenderCameraReset()

# ------------------------------------------------------------------------------
# 2. OpenFOAM Reader Pipeline
# ------------------------------------------------------------------------------
print("[1/6] Loading OpenFOAM case data...")
reader = OpenFOAMReader(registrationName='waam_arc.foam', FileName=foam_file)
reader.MeshRegions = ['internalMesh']
reader.CellArrays = [
    'Temperature', 'U', 'alpha.phase1', 'epsilon1', 
    'p_rgh', 'Marangoni', 'DC', 'LatentHeat'
]
reader.UpdatePipeline()

# Discover timesteps
scene = GetAnimationScene()
scene.UpdateAnimationUsingDataTimeSteps()
time_keeper = GetTimeKeeper()
time_steps = list(time_keeper.TimestepValues)

if not time_steps:
    print("Warning: No time steps discovered in reader. Updating pipeline...")
    reader.UpdatePipeline()
    time_steps = list(time_keeper.TimestepValues)

latest_time = time_steps[-1] if time_steps else 0.0
print(f"Discovered {len(time_steps)} time steps. Latest time: t = {latest_time:.4f} s")
time_keeper.Time = latest_time

# ------------------------------------------------------------------------------
# 3. Colormap & Color Transfer Functions
# ------------------------------------------------------------------------------
t_LUT = GetColorTransferFunction('Temperature')
t_LUT.ApplyPreset('Black-Body Radiation', True)
t_LUT.RescaleTransferFunction(300.0, 1800.0)

t_PWF = GetOpacityTransferFunction('Temperature')
t_PWF.RescaleTransferFunction(300.0, 1800.0)

# ------------------------------------------------------------------------------
# 4. View 1: 3D Isometric View with HAZ & Melt Pool Threshold
# ------------------------------------------------------------------------------
print("[2/6] Rendering 3D Isometric HAZ & Melt Pool...")
view_3d = CreateView('RenderView')
view_3d.ViewSize = [1920, 1080]
view_3d.Background = [0.13, 0.14, 0.16]

# Camera positioned close to the weld bead
view_3d.CameraFocalPoint = [0.0, 0.006, -0.005]
view_3d.CameraPosition = [0.025, 0.022, 0.022]
view_3d.CameraViewUp = [-0.25, 0.90, -0.35]
view_3d.CameraParallelProjection = 0

# Domain bounding outline
domain_outline = Outline(registrationName='Domain_Outline', Input=reader)
outline_disp = Show(domain_outline, view_3d)
outline_disp.Representation = 'Wireframe'
outline_disp.AmbientColor = [0.6, 0.6, 0.6]

# Semi-transparent substrate base
base_disp = Show(reader, view_3d, 'UniformGridRepresentation')
base_disp.Representation = 'Surface'
base_disp.ColorArrayName = ['CELLS', 'Temperature']
base_disp.LookupTable = t_LUT
base_disp.Opacity = 0.15

# Heat Affected Zone threshold (T >= 1000 K)
haz_thresh = Threshold(registrationName='HAZ_Region_T1000', Input=reader)
haz_thresh.Scalars = ['CELLS', 'Temperature']
haz_thresh.ThresholdMethod = 'Between'
haz_thresh.LowerThreshold = 1000.0
haz_thresh.UpperThreshold = 3500.0

haz_disp = Show(haz_thresh, view_3d, 'UnstructuredGridRepresentation')
haz_disp.Representation = 'Surface'
haz_disp.ColorArrayName = ['CELLS', 'Temperature']
haz_disp.LookupTable = t_LUT
haz_disp.Opacity = 0.92

# Melt pool threshold (T >= 1400 K)
pool_thresh = Threshold(registrationName='MeltPool_T1400', Input=reader)
pool_thresh.Scalars = ['CELLS', 'Temperature']
pool_thresh.ThresholdMethod = 'Between'
pool_thresh.LowerThreshold = 1400.0
pool_thresh.UpperThreshold = 3500.0

pool_disp = Show(pool_thresh, view_3d, 'UnstructuredGridRepresentation')
pool_disp.Representation = 'Surface With Edges'
pool_disp.ColorArrayName = ['CELLS', 'Temperature']
pool_disp.LookupTable = t_LUT
pool_disp.Opacity = 1.0

# Temperature color bar
t_bar3 = GetScalarBar(t_LUT, view_3d)
t_bar3.Title = 'Temperature [K]'
t_bar3.ComponentTitle = ''
t_bar3.Visibility = 1
t_bar3.TitleFontSize = 14
t_bar3.LabelFontSize = 12

img_3d = os.path.join(output_dir, "paraview_3d_temperature_haz.png")
SaveScreenshot(img_3d, view_3d, ImageResolution=[1920, 1080])
print(f" -> Generated: {img_3d}")

# ------------------------------------------------------------------------------
# 5. View 2: Longitudinal Centerline Slice (Y-Z Plane at X = 0)
# ------------------------------------------------------------------------------
print("[3/6] Rendering Longitudinal Centerline Slice...")
slice_long = Slice(registrationName='Longitudinal_Slice_X0', Input=reader)
slice_long.SliceType = 'Plane'
slice_long.SliceType.Origin = [0.0, 0.0065, 0.0]
slice_long.SliceType.Normal = [1.0, 0.0, 0.0] # Slice at X = 0

c2p_long = CellDatatoPointData(registrationName='Longitudinal_PointData', Input=slice_long)

view_long = CreateView('RenderView')
view_long.ViewSize = [1920, 960]
view_long.Background = [0.11, 0.12, 0.14]

# Facing from -X towards +X so +Z (travel direction) advances to the right
view_long.CameraFocalPoint = [0.0, 0.0065, -0.005]
view_long.CameraPosition = [-0.10, 0.0065, -0.005]
view_long.CameraViewUp = [0.0, 1.0, 0.0]
view_long.CameraParallelProjection = 1
view_long.CameraParallelScale = 0.018

slice_long_disp = Show(c2p_long, view_long, 'GeometryRepresentation')
slice_long_disp.Representation = 'Surface'
slice_long_disp.ColorArrayName = ['POINTS', 'Temperature']
slice_long_disp.LookupTable = t_LUT

# Smooth isotherms
iso_long = Contour(registrationName='Isotherms_Longitudinal', Input=c2p_long)
iso_long.ContourBy = ['POINTS', 'Temperature']
iso_long.Isosurfaces = [500.0, 800.0, 1000.0, 1200.0, 1400.0, 1723.0]

iso_long_disp = Show(iso_long, view_long, 'GeometryRepresentation')
iso_long_disp.Representation = 'Wireframe'
iso_long_disp.AmbientColor = [1.0, 1.0, 1.0]
iso_long_disp.LineWidth = 2.0

# Velocity vector arrows
glyphs_long = Glyph(registrationName='Velocity_Vectors_Longitudinal', Input=slice_long)
glyphs_long.OrientationArray = ['CELLS', 'U']
glyphs_long.ScaleArray = ['CELLS', 'U']
glyphs_long.ScaleFactor = 0.3
glyphs_long.GlyphType = 'Arrow'
glyphs_long.MaximumNumberOfSamplePoints = 250

glyphs_disp = Show(glyphs_long, view_long, 'GeometryRepresentation')
glyphs_disp.Representation = 'Surface'
glyphs_disp.AmbientColor = [0.3, 0.9, 1.0]

t_bar_long = GetScalarBar(t_LUT, view_long)
t_bar_long.Title = 'Temperature [K]'
t_bar_long.ComponentTitle = ''
t_bar_long.Visibility = 1

img_long = os.path.join(output_dir, "paraview_longitudinal_centerline_slice.png")
SaveScreenshot(img_long, view_long, ImageResolution=[1920, 960])
print(f" -> Generated: {img_long}")

# ------------------------------------------------------------------------------
# 6. View 3: Transverse Cross-Section (X-Y Plane across Arc)
# ------------------------------------------------------------------------------
print("[4/6] Rendering Transverse Bead Cross-Section...")
slice_trans = Slice(registrationName='Transverse_Slice_BeadCrossSection', Input=reader)
slice_trans.SliceType = 'Plane'
slice_trans.SliceType.Origin = [0.0, 0.0065, -0.005] # Peak thermal plane
slice_trans.SliceType.Normal = [0.0, 0.0, 1.0]      # Normal along travel axis

c2p_trans = CellDatatoPointData(registrationName='Transverse_PointData', Input=slice_trans)

view_trans = CreateView('RenderView')
view_trans.ViewSize = [1280, 960]
view_trans.Background = [0.11, 0.12, 0.14]

view_trans.CameraFocalPoint = [0.0, 0.0065, -0.005]
view_trans.CameraPosition = [0.0, 0.0065, 0.05]
view_trans.CameraViewUp = [0.0, 1.0, 0.0]
view_trans.CameraParallelProjection = 1
view_trans.CameraParallelScale = 0.011

slice_trans_disp = Show(c2p_trans, view_trans, 'GeometryRepresentation')
slice_trans_disp.Representation = 'Surface'
slice_trans_disp.ColorArrayName = ['POINTS', 'Temperature']
slice_trans_disp.LookupTable = t_LUT

iso_trans = Contour(registrationName='Isotherms_Transverse', Input=c2p_trans)
iso_trans.ContourBy = ['POINTS', 'Temperature']
iso_trans.Isosurfaces = [500.0, 800.0, 1000.0, 1200.0, 1400.0, 1723.0]

iso_trans_disp = Show(iso_trans, view_trans, 'GeometryRepresentation')
iso_trans_disp.Representation = 'Wireframe'
iso_trans_disp.AmbientColor = [1.0, 1.0, 1.0]
iso_trans_disp.LineWidth = 2.0

t_bar_trans = GetScalarBar(t_LUT, view_trans)
t_bar_trans.Title = 'Temperature [K]'
t_bar_trans.ComponentTitle = ''
t_bar_trans.Visibility = 1

img_trans = os.path.join(output_dir, "paraview_transverse_bead_cross_section.png")
SaveScreenshot(img_trans, view_trans, ImageResolution=[1280, 960])
print(f" -> Generated: {img_trans}")

# ------------------------------------------------------------------------------
# 7. Animated Time-Lapse Generation
# ------------------------------------------------------------------------------
if HAS_PIL and len(time_steps) > 1:
    print("[5/6] Generating Animated Thermal Time-Lapse GIF...")
    tmp_frames_dir = os.path.join(output_dir, "_tmp_frames")
    os.makedirs(tmp_frames_dir, exist_ok=True)
    
    step = max(1, len(time_steps) // 20)
    sampled = time_steps[::step]
    if time_steps[-1] not in sampled:
        sampled.append(time_steps[-1])
        
    frames = []
    for idx, t in enumerate(sampled):
        time_keeper.Time = t
        frame_file = os.path.join(tmp_frames_dir, f"frame_{idx:03d}.png")
        SaveScreenshot(frame_file, view_long, ImageResolution=[1280, 640])
        frames.append(Image.open(frame_file))
        
    gif_path = os.path.join(output_dir, "waam_thermal_timelapse.gif")
    if frames:
        frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=150, loop=0)
        print(f" -> Generated Animated GIF: {gif_path} ({len(frames)} frames)")
        
    for f in os.listdir(tmp_frames_dir):
        os.remove(os.path.join(tmp_frames_dir, f))
    os.rmdir(tmp_frames_dir)
    
    # Restore latest time
    time_keeper.Time = latest_time
else:
    print("[5/6] Skipping GIF generation (PIL not available or single timestep).")

# ------------------------------------------------------------------------------
# 8. Save Full ParaView State File (.pvsm)
# ------------------------------------------------------------------------------
print("[6/6] Saving ParaView Pipeline State File...")
state_file = os.path.join(case_dir, "waam_visualization.pvsm")
SaveState(state_file)
print(f" -> State File Saved: {state_file}")

print("================================================================")
print(" Postprocessing Pipeline Successfully Completed!")
print("================================================================")
