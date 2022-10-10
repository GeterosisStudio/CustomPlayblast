import copy
import os
import sys
import traceback

from PySide2 import QtCore
from PySide2 import QtGui
from PySide2 import QtWidgets

from shiboken2 import wrapInstance

import maya.cmds as cmds
import maya.mel as mel
import maya.OpenMaya as om
import maya.OpenMayaUI as omui


class GeterosisPlayblast(QtCore.QObject):

    VERSION = "1.0.12"

    DEFAULT_FFMPEG_PATH = ""

    RESOLUTION_LOOKUP = {
        "Render": (),
        "HD 1080": (1920, 1080),
        "HD 720": (1280, 720),
        "HD 540": (960, 540),
    }

    FRAME_RANGE_PRESETS = [
        "Render",
        "Playback",
        "Animation",
    ]

    VIDEO_ENCODER_LOOKUP = {
        "mov": ["h264"],
        "mp4": ["h264"],
        "Image": ["jpg", "png", "tif"],
    }

    H264_QUALITIES = {
        "Very High": 18,
        "High": 20,
        "Medium": 23,
        "Low": 26,
    }

    H264_PRESETS = [
        "veryslow",
        "slow",
        "medium",
        "fast",
        "faster",
        "ultrafast",
    ]

    VIEWPORT_VISIBILITY_LOOKUP = [
        ["Controllers", "controllers"],
        ["NURBS Curves", "nurbsCurves"],
        ["NURBS Surfaces", "nurbsSurfaces"],
        ["NURBS CVs", "cv"],
        ["NURBS Hulls", "hulls"],
        ["Polygons", "polymeshes"],
        ["Subdiv Surfaces", "subdivSurfaces"],
        ["Planes", "planes"],
        ["Lights", "lights"],
        ["Cameras", "cameras"],
        ["Image Planes", "imagePlane"],
        ["Joints", "joints"],
        ["IK Handles", "ikHandles"],
        ["Deformers", "deformers"],
        ["Dynamics", "dynamics"],
        ["Particle Instancers", "particleInstancers"],
        ["Fluids", "fluids"],
        ["Hair Systems", "hairSystems"],
        ["Follicles", "follicles"],
        ["nCloths", "nCloths"],
        ["nParticles", "nParticles"],
        ["nRigids", "nRigids"],
        ["Dynamic Constraints", "dynamicConstraints"],
        ["Locators", "locators"],
        ["Dimensions", "dimensions"],
        ["Pivots", "pivots"],
        ["Handles", "handles"],
        ["Texture Placements", "textures"],
        ["Strokes", "strokes"],
        ["Motion Trails", "motionTrails"],
        ["Plugin Shapes", "pluginShapes"],
        ["Clip Ghosts", "clipGhosts"],
        ["Grease Pencil", "greasePencils"],
        ["Grid", "grid"],
        ["HUD", "hud"],
        ["Hold-Outs", "hos"],
        ["Selection Highlighting", "sel"],
    ]

    VIEWPORT_VISIBILITY_PRESETS = {
        "Viewport": [],
        "Geo": ["NURBS Surfaces", "Polygons"],
        "Dynamics": ["NURBS Surfaces", "Polygons", "Dynamics", "Fluids", "nParticles"],
    }


    DEFAULT_CAMERA = None
    DEFAULT_RESOLUTION = "HD 1080"
    DEFAULT_FRAME_RANGE = "Playback"

    DEFAULT_CONTAINER = "mov"
    DEFAULT_ENCODER = "h264"
    DEFAULT_H264_QUALITY = "High"
    DEFAULT_H264_PRESET = "fast"
    DEFAULT_IMAGE_QUALITY = 100

    DEFAULT_VISIBILITY = "Geo"

    DEFAULT_PADDING = 4

    OutputLogged = QtCore.Signal(str)


    def __init__(self, FfmpegPath="", LogToMaya=True):
        super(GeterosisPlayblast, self).__init__()

        self.SetFfmpegPath(FfmpegPath)
        self.SetMayaLoggingEnabled(LogToMaya)

        self.SetCamera(GeterosisPlayblast.DEFAULT_CAMERA)
        self.SetResolution(GeterosisPlayblast.DEFAULT_RESOLUTION)
        self.SetFrameRange(GeterosisPlayblast.DEFAULT_FRAME_RANGE)

        self.SetEncoding(GeterosisPlayblast.DEFAULT_CONTAINER, GeterosisPlayblast.DEFAULT_ENCODER)
        self.Seth264Settings(GeterosisPlayblast.DEFAULT_H264_QUALITY, GeterosisPlayblast.DEFAULT_H264_PRESET)
        self.SetImageSettings(GeterosisPlayblast.DEFAULT_IMAGE_QUALITY)

        self.SetVisibility(GeterosisPlayblast.DEFAULT_VISIBILITY)

        self.InitializeFfmpegProcess()

    def SetFfmpegPath(self, FfmpegPath):
        if FfmpegPath:
            self._FfmpegPath = FfmpegPath
        else:
            self._FfmpegPath = GeterosisPlayblast.DEFAULT_FFMPEG_PATH

    def GetFfmpegPath(self):
        return self._FfmpegPath

    def SetMayaLoggingEnabled(self, Enable):
        self._LogToMaya = Enable

    def SetCamera(self, Camera):
        if Camera and Camera not in cmds.listCameras():
            self.LogError("Camera does not exist: {0}".format(Camera))
            Camera = None

        self._Camera = Camera

    def SetResolution(self, Resolution):
        self._ResolutionPreset = None

        try:
            WidthHeight = self.PresetToResolution(Resolution)
            self._ResolutionPreset = Resolution
        except:
            WidthHeight = Resolution

        ValidResolution = True
        try:
            if not (isinstance(WidthHeight[0], int) and isinstance(WidthHeight[1], int)):
                ValidResolution = False
        except:
            ValidResolution = False

        if ValidResolution:
            if WidthHeight[0] <=0 or WidthHeight[1] <= 0:
                self.LogError("Invalid resolution: {0}. Values must be greater than zero.".format(WidthHeight))
                return
        else:
            presets = []
            for preset in GeterosisPlayblast.RESOLUTION_LOOKUP.keys():
                presets.append("'{0}'".format(preset))

            self.LogError("Invalid resoluton: {0}. Expected one of [int, int], {1}".format(WidthHeight, ", ".join(presets)))
            return

        self._WidthHeight = (WidthHeight[0], WidthHeight[1])

    def GetResolutionWidthHeight(self):
        if self._ResolutionPreset:
            return self.PresetToResolution(self._ResolutionPreset)

        return self._WidthHeight

    def PresetToResolution(self, ResolutionPreset):
        if ResolutionPreset == "Render":
            Width = cmds.getAttr("defaultResolution.width")
            Height = cmds.getAttr("defaultResolution.height")
            return (Width, Height)
        elif ResolutionPreset in GeterosisPlayblast.RESOLUTION_LOOKUP.keys():
            return GeterosisPlayblast.RESOLUTION_LOOKUP[ResolutionPreset]
        else:
            raise RuntimeError("Invalid resolution preset: {0}".format(ResolutionPreset))

    def SetFrameRange(self, FrameRange):
        ResolvedFrameRange = self.ResolveFrameRange(FrameRange)
        if not ResolvedFrameRange:
            return

        self._FrameRangePreset = None
        if FrameRange in GeterosisPlayblast.FRAME_RANGE_PRESETS:
            self._FrameRangePreset = FrameRange

        self._StartFrame = ResolvedFrameRange[0]
        self._EndFrame = ResolvedFrameRange[1]

    def GetStartEndFrame(self):
        if self._FrameRangePreset:
            return self.PresetToFrameRange(self._FrameRangePreset)

        return (self._StartFrame, self._EndFrame)

    def ResolveFrameRange(self, FrameRange):
        try:
            if type(FrameRange) in [list, tuple]:
                StartFrame = FrameRange[0]
                EndFrame = FrameRange[1]
            else:
                StartFrame, EndFrame = self.PresetToFrameRange(FrameRange)

            return (StartFrame, EndFrame)

        except:
            Presets = []
            for Preset in GeterosisPlayblast.FRAME_RANGE_PRESETS:
                Presets.append("'{0}'".format(Preset))
            self.LogError('Invalid frame range. Expected one of (start_frame, end_frame), {0}'.format(", ".join(Presets)))

        return None

    def PresetToFrameRange(self, FrameRangePreset):
        if FrameRangePreset == "Render":
            StartFrame = int(cmds.getAttr("defaultRenderGlobals.startFrame"))
            EndFrame = int(cmds.getAttr("defaultRenderGlobals.endFrame"))
        elif FrameRangePreset == "Playback":
            StartFrame = int(cmds.playbackOptions(q=True, minTime=True))
            EndFrame = int(cmds.playbackOptions(q=True, maxTime=True))
        elif FrameRangePreset == "Animation":
            StartFrame = int(cmds.playbackOptions(q=True, animationStartTime=True))
            EndFrame = int(cmds.playbackOptions(q=True, animationEndTime=True))
        else:
            raise RuntimeError("Invalid frame range preset: {0}".format(FrameRangePreset))

        return (StartFrame, EndFrame)

    def SetVisibility(self, VisibilityData):
        if not VisibilityData:
            VisibilityData = []

        if not type(VisibilityData) in [list, tuple]:
            VisibilityData = self.PresetToVisibility(VisibilityData)

            if VisibilityData is None:
                return

        self._Visibility = copy.copy(VisibilityData)

    def GetVisibility(self):
        if not self._Visibility:
            return self.GetViewportVisibility()

        return self._Visibility

    def PresetToVisibility(self, VisibilityPreset):
        if not VisibilityPreset in GeterosisPlayblast.VIEWPORT_VISIBILITY_PRESETS.keys():
            self.LogError("Invaild visibility preset: {0}".format(VisibilityPreset))
            return None

        VisibilityData = []

        PresetNames = GeterosisPlayblast.VIEWPORT_VISIBILITY_PRESETS[VisibilityPreset]
        if PresetNames:
            for lookup_item in GeterosisPlayblast.VIEWPORT_VISIBILITY_LOOKUP:
                VisibilityData.append(lookup_item[0] in PresetNames)

        return VisibilityData

    def GetViewportVisibility(self):
        ModelPanel = self.GetViewportPanel()
        if not ModelPanel:
            self.LogError("Failed to get viewport visibility. A viewport is not active.")
            return None

        ViewportVisibility = []
        try:
            for Item in GeterosisPlayblast.VIEWPORT_VISIBILITY_LOOKUP:
                Kwargs = {Item[1]: True}
                ViewportVisibility.append(cmds.modelEditor(ModelPanel, q=True, **Kwargs))
        except:
            traceback.print_exc()
            self.LogError("Failed to get active viewport visibility. See script editor for details.")
            return None

        return ViewportVisibility

    def SetViewportVisibility(self, ModelEditor, VisibilityFlags):
        cmds.modelEditor(ModelEditor, e=True, **VisibilityFlags)

    def CreateViewportVisibilityFlags(self, VisibilityData):
        VisibilityFlags = {}

        DataIndex = 0
        for Item in GeterosisPlayblast.VIEWPORT_VISIBILITY_LOOKUP:
            VisibilityFlags[Item[1]] = VisibilityData[DataIndex]
            DataIndex += 1

        return VisibilityFlags

    def SetEncoding(self, ContainerFormat, Encoder):
        if ContainerFormat not in GeterosisPlayblast.VIDEO_ENCODER_LOOKUP.keys():
            self.LogError("Invalid container: {0}. Expected one of {1}".format(ContainerFormat, GeterosisPlayblast.VIDEO_ENCODER_LOOKUP.keys()))
            return

        if Encoder not in GeterosisPlayblast.VIDEO_ENCODER_LOOKUP[ContainerFormat]:
            self.LogError("Invalid encoder: {0}. Expected one of {1}".format(Encoder, GeterosisPlayblast.VIDEO_ENCODER_LOOKUP[ContainerFormat]))
            return

        self._ContainerFormat = ContainerFormat
        self._Encoder = Encoder

    def Seth264Settings(self, Quality, Preset):
        if not Quality in GeterosisPlayblast.H264_QUALITIES.keys():
            self.LogError("Invalid h264 quality: {0}. Expected one of {1}".format(Quality, GeterosisPlayblast.H264_QUALITIES.keys()))
            return

        if not Preset in GeterosisPlayblast.H264_PRESETS:
            self.LogError("Invalid h264 preset: {0}. Expected one of {1}".format(Preset, GeterosisPlayblast.H264_PRESETS))
            return

        self._h264Quality = Quality
        self._h264Preset = Preset

    def Geth264Settings(self):
        return {
            "quality": self._h264Quality,
            "preset": self._h264Preset,
        }

    def SetImageSettings(self, Quality):
        if Quality > 0 and Quality <= 100:
            self._ImageQuality = Quality
        else:
            self.LogError("Invalid image quality: {0}. Expected value between 1-100")

    def GetImageSettings(self):
        return {
            "quality": self._ImageQuality,
        }

    def execute(self, OutputDir, FileName, Padding=4, Overscan=False, ShowOrnaments=True, ShowInViewer=True, Overwrite=False):

        if self.RequiresFfmpeg() and not self.ValidateFfmpeg():
            self.LogError("Ffmpeg executable is not configured. See script editor for details.")
            return

        ViewportModelPanel = self.GetViewportPanel()
        if not ViewportModelPanel:
            self.LogError("An active viewport is not selected. Select a viewport and retry.")
            return

        if not OutputDir:
            self.LogError("Output directory path not set")
            return
        if not FileName:
            self.LogError("Output file name not set")
            return

        OutputDir = self.ResolveOutputDirectoryPath(OutputDir)
        FileName = self.ResolveOutputFilename(FileName)

        if Padding <= 0:
            Padding = GeterosisPlayblast.DEFAULT_PADDING

        if self.RequiresFfmpeg():
            OutputPath = os.path.normpath(os.path.join(OutputDir, "{0}.{1}".format(FileName, self._ContainerFormat)))
            if not Overwrite and os.path.exists(OutputPath):
                self.LogError("Output file already exists. Eanble overwrite to ignore.")
                return

            PlayblastOutputDir = "{0}/playblast_temp".format(OutputDir)
            PlayblastOutput = os.path.normpath(os.path.join(PlayblastOutputDir, FileName))
            ForceOverwrite = True
            Compression = "png"
            ImageQuality = 100
            IndexFromZero = True
            Viewer = False
        else:
            PlayblastOutput = os.path.normpath(os.path.join(OutputDir, FileName))
            ForceOverwrite = Overwrite
            Compression = self._Encoder
            ImageQuality = self._ImageQuality
            IndexFromZero = False
            Viewer = ShowInViewer

        WidthHeight = self.GetResolutionWidthHeight()
        StartFrame, EndFrame = self.GetStartEndFrame()

        Options = {
            "filename": PlayblastOutput,
            "widthHeight": WidthHeight,
            "percent": 100,
            "startTime": StartFrame,
            "endTime": EndFrame,
            "clearCache": True,
            "forceOverwrite": ForceOverwrite,
            "format": "image",
            "compression": Compression,
            "quality": ImageQuality,
            "indexFromZero": IndexFromZero,
            "framePadding": Padding,
            "showOrnaments": ShowOrnaments,
            "viewer": Viewer,
        }

        self.LogOutput("Playblast options: {0}".format(Options))

        # Store original viewport settings
        OriginalCamera = self.GetActiveCamera()

        Camera = self._Camera
        if not Camera:
            Camera = OriginalCamera

        if not Camera in cmds.listCameras():
            self.LogError("Camera does not exist: {0}".format(Camera))
            return

        self.SetActiveCamera(Camera)

        OriginVisibilityFlags = self.CreateViewportVisibilityFlags(self.GetViewportVisibility())
        PlayblastVisibilityFlags = self.CreateViewportVisibilityFlags(self.GetVisibility())
            
        ModelEditor = cmds.modelPanel(ViewportModelPanel, q=True, modelEditor=True)
        self.SetViewportVisibility(ModelEditor, PlayblastVisibilityFlags)
        
        # Store original camera settings
        if not Overscan:
            OverscanAttr = "{0}.overscan".format(Camera)
            OrigOverscan = cmds.getAttr(OverscanAttr)
            cmds.setAttr(OverscanAttr, 1.0)

        PlayblastFailed = False
        try:
            cmds.playblast(**Options)
        except:
            traceback.print_exc()
            self.LogError("Failed to create playblast. See script editor for details.")
            PlayblastFailed = True
        finally:
            # Restore original camera settings
            if not Overscan:
                cmds.setAttr(OverscanAttr, OrigOverscan)
            
            # Restore original viewport settings
            self.SetActiveCamera(OriginalCamera)
            self.SetViewportVisibility(ModelEditor, OriginVisibilityFlags)

        if PlayblastFailed:
            return

        if self.RequiresFfmpeg():
            SourcePath = "{0}/{1}.%0{2}d.png".format(PlayblastOutputDir, FileName, Padding)

            if self._Encoder == "h264":
                self.Encodeh264(SourcePath, OutputPath, StartFrame)
            else:
                self.LogError("Encoding failed. Unsupported encoder ({0}) for container ({1}).".format(self._Encoder, self._ContainerFormat))
                self.RemoveTempDir(PlayblastOutputDir)
                return

            self.RemoveTempDir(PlayblastOutputDir)

            if ShowInViewer:
                self.OpenInViewer(OutputPath)

    def RemoveTempDir(self, TempDirPath):
        PlayblastDir = QtCore.QDir(TempDirPath)
        PlayblastDir.setNameFilters(["*.png"])
        PlayblastDir.setFilter(QtCore.QDir.Files)
        for i in PlayblastDir.entryList():
            PlayblastDir.remove(i)

        if not PlayblastDir.rmdir(TempDirPath):
            self.LogWarning("Failed to remove temporary directory: {0}".format(TempDirPath))

    def OpenInViewer(self, Path):
        if not os.path.exists(Path):
            self.LogError("Failed to open in viewer. File does not exists: {0}".format(Path))
            return

        if self._ContainerFormat in ("mov", "mp4") and cmds.optionVar(exists="PlayblastCmdQuicktime"):
            ExecutablePath = cmds.optionVar(q="PlayblastCmdQuicktime")
            if ExecutablePath:
                QtCore.QProcess.startDetached(ExecutablePath, [Path])
                return

        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(Path))

    def RequiresFfmpeg(self):
        return self._ContainerFormat != "Image"

    def ValidateFfmpeg(self):
        if not self._FfmpegPath:
            self.LogError("ffmpeg executable path not set")
            return False
        elif not os.path.exists(self._FfmpegPath):
            self.LogError("ffmpeg executable path does not exist: {0}".format(self._FfmpegPath))
            return False
        elif os.path.isdir(self._FfmpegPath):
            self.LogError("Invalid ffmpeg path: {0}".format(self._FfmpegPath))
            return False

        return True

    def InitializeFfmpegProcess(self):
        self._FfmpegProcess = QtCore.QProcess()
        self._FfmpegProcess.readyReadStandardError.connect(self.ProcessFfmpegOutput)

    def ExecuteFfmpegCommand(self, Command):
        self._FfmpegProcess.start(Command)
        if self._FfmpegProcess.waitForStarted():
            while self._FfmpegProcess.state() != QtCore.QProcess.NotRunning:
                QtCore.QCoreApplication.processEvents()
                QtCore.QThread.usleep(10)

    def ProcessFfmpegOutput(self):
        ByteArrayOutput = self._FfmpegProcess.readAllStandardError()

        if sys.version_info.major < 3:
            Output = str(ByteArrayOutput)
        else:
            Output = str(ByteArrayOutput, "utf-8")

        self.LogOutput(Output)

    def Encodeh264(self, SourcePath, OutputPath, StartFrame):
        Framerate = self.GetFrameRate()

        AudioFilePath, AudioFrameOffset = self.GetAudioAttributes()
        if AudioFilePath:
            AudioOffset = self.GetAudioOffsetInSec(StartFrame, AudioFrameOffset, Framerate)

        Crf = GeterosisPlayblast.H264_QUALITIES[self._h264Quality]
        Preset = self._h264Preset

        FfmpegCmd = self._FfmpegPath
        FfmpegCmd += ' -y -framerate {0} -i "{1}"'.format(Framerate, SourcePath)

        if AudioFilePath:
            FfmpegCmd += ' -ss {0} -i "{1}"'.format(AudioOffset, AudioFilePath)

        FfmpegCmd += ' -c:v libx264 -crf:v {0} -preset:v {1} -profile high -level 4.0 -pix_fmt yuv420p'.format(Crf, Preset)

        if AudioFilePath:
            FfmpegCmd += ' -filter_complex "[1:0] apad" -shortest'

        FfmpegCmd += ' "{0}"'.format(OutputPath)

        self.LogOutput(FfmpegCmd)

        self.ExecuteFfmpegCommand(FfmpegCmd)

    def GetFrameRate(self):
        RateStr = cmds.currentUnit(q=True, time=True)

        if RateStr == "game":
            FrameRate = 15.0
        elif RateStr == "film":
            FrameRate = 24.0
        elif RateStr == "pal":
            FrameRate = 25.0
        elif RateStr == "ntsc":
            FrameRate = 30.0
        elif RateStr == "show":
            FrameRate = 48.0
        elif RateStr == "palf":
            FrameRate = 50.0
        elif RateStr == "ntscf":
            FrameRate = 60.0
        elif RateStr.endswith("fps"):
            FrameRate = float(RateStr[0:-3])
        else:
            raise RuntimeError("Unsupported frame rate: {0}".format(RateStr))

        return FrameRate

    def GetAudioAttributes(self):
        SoundNode = mel.eval("timeControl -q -sound $gPlayBackSlider;")
        if SoundNode:
            FilePath = cmds.getAttr("{0}.filename".format(SoundNode))
            FileInfo = QtCore.QFileInfo(FilePath)
            if FileInfo.exists():
                Offset = cmds.getAttr("{0}.offset".format(SoundNode))

                return (FilePath, Offset)

        return (None, None)

    def GetAudioOffsetInSec(self, StartFrame, AudioFrameOffset, FrameRate):
        return (StartFrame - AudioFrameOffset) / FrameRate

    def ResolveOutputDirectoryPath(self, DirPath):
        if "{project}" in DirPath:
            DirPath = DirPath.replace("{project}", self.GetProjectDirPath())

        return DirPath

    def ResolveOutputFilename(self, FileName):
        if "{scene}" in FileName:
            FileName = FileName.replace("{scene}", self.GetSceneName())

        return FileName

    def GetProjectDirPath(self):
        return cmds.workspace(q=True, rootDirectory=True)

    def GetSceneName(self):
        SceneName = cmds.file(q=True, sceneName=True, shortName=True)
        if SceneName:
            SceneName = os.path.splitext(SceneName)[0]
        else:
            SceneName = "untitled"

        return SceneName

    def GetViewportPanel(self):
        ModelPanel = cmds.getPanel(withFocus=True)
        try:
            cmds.modelPanel(ModelPanel, q=True, modelEditor=True)
        except:
            self.LogError("Failed to get active view.")
            return None

        return ModelPanel

    def GetActiveCamera(self):
        ModelPanel = self.GetViewportPanel()
        if not ModelPanel:
            self.LogError("Failed to get active camera. A viewport is not active.")
            return None

        return cmds.modelPanel(ModelPanel, q=True, camera=True)

    def SetActiveCamera(self, camera):
        ModelPanel = self.GetViewportPanel()
        if ModelPanel:
            mel.eval("lookThroughModelPanel {0} {1}".format(camera, ModelPanel))
        else:
            self.LogError("Failed to set active camera. A viewport is not active.")

    def LogError(self, Text):
        if self._LogToMaya:
            om.MGlobal.displayError("[GeterosisPlayblast] {0}".format(Text))

        self.OutputLogged.emit("[ERROR] {0}".format(Text)) # pylint: disable=E1101

    def LogWarning(self, Text):
        if self._LogToMaya:
            om.MGlobal.displayWarning("[GeterosisPlayblast] {0}".format(Text))

        self.OutputLogged.emit("[WARNING] {0}".format(Text)) # pylint: disable=E1101

    def LogOutput(self, Text):
        if self._LogToMaya:
            om.MGlobal.displayInfo(Text)

        self.OutputLogged.emit(Text) # pylint: disable=E1101


class GeterosisPlayblastSettingsDialog(QtWidgets.QDialog):

    def __init__(self, Parent):
        super(GeterosisPlayblastSettingsDialog, self).__init__(Parent)

        self.setWindowTitle("Settings")
        self.setWindowFlags(self.windowFlags() ^ QtCore.Qt.WindowContextHelpButtonHint)
        self.setMinimumWidth(360)
        self.setModal(True)

        self.FfmpegPathLe = QtWidgets.QLineEdit()
        self.FfmpegPathSelectBtn = QtWidgets.QPushButton("...")
        self.FfmpegPathSelectBtn.setFixedSize(24, 19)
        self.FfmpegPathSelectBtn.clicked.connect(self.SelectFfmpegExecutable)

        FfmpegLayout = QtWidgets.QHBoxLayout()
        FfmpegLayout.setSpacing(4)
        FfmpegLayout.addWidget(self.FfmpegPathLe)
        FfmpegLayout.addWidget(self.FfmpegPathSelectBtn)

        FfmpegGrp = QtWidgets.QGroupBox("FFmpeg Path")
        FfmpegGrp.setLayout(FfmpegLayout)

        self.AcceptBtn = QtWidgets.QPushButton("Accept")
        self.AcceptBtn.clicked.connect(self.accept)

        self.CancelBtn = QtWidgets.QPushButton("Cancel")
        self.CancelBtn.clicked.connect(self.close)

        ButtonLayout = QtWidgets.QHBoxLayout()
        ButtonLayout.addStretch()
        ButtonLayout.addWidget(self.AcceptBtn)
        ButtonLayout.addWidget(self.CancelBtn)

        MainLayout = QtWidgets.QVBoxLayout(self)
        MainLayout.setContentsMargins(4, 4, 4, 4)
        MainLayout.setSpacing(4)
        MainLayout.addWidget(FfmpegGrp)
        MainLayout.addStretch()
        MainLayout.addLayout(ButtonLayout)

    def SetFfmpegPath(self, Path):
        self.FfmpegPathLe.setText(Path)

    def GetFfmpegPath(self):
        return self.FfmpegPathLe.text()

    def SelectFfmpegExecutable(self):
        CurrentPath = self.FfmpegPathLe.text()

        NewPath = QtWidgets.QFileDialog.getOpenFileName(self, "Select FFmpeg Executable", CurrentPath)[0]
        if NewPath:
            self.FfmpegPathLe.setText(NewPath)


class GeterosisPlayblastEncoderSettingsDialog(QtWidgets.QDialog):

    ENCODER_PAGES = {
        "h264": 0,
        "Image": 1,
    }

    H264_QUALITIES = [
        "Very High",
        "High",
        "Medium",
        "Low",
    ]


    def __init__(self, Parent):
        super(GeterosisPlayblastEncoderSettingsDialog, self).__init__(Parent)

        self.setWindowTitle("Encoder Settings")
        self.setWindowFlags(self.windowFlags() ^ QtCore.Qt.WindowContextHelpButtonHint)
        self.setModal(True)
        self.setMinimumWidth(220)

        self.CreateWidgets()
        self.CreateLayout()
        self.CreateConnections()

    def CreateWidgets(self):
        # h264
        self.h264QualityCombo = QtWidgets.QComboBox()
        self.h264QualityCombo.addItems(GeterosisPlayblastEncoderSettingsDialog.H264_QUALITIES)

        self.h264PresetCombo = QtWidgets.QComboBox()
        self.h264PresetCombo.addItems(GeterosisPlayblast.H264_PRESETS)

        h264Layout = QtWidgets.QFormLayout()
        h264Layout.addRow("Quality:", self.h264QualityCombo)
        h264Layout.addRow("Preset:", self.h264PresetCombo)

        h264SettingsWdg = QtWidgets.QGroupBox("h264 Options")
        h264SettingsWdg.setLayout(h264Layout)

        # image
        self.ImageQualitySpinBox = QtWidgets.QSpinBox()
        self.ImageQualitySpinBox.setMinimumWidth(40)
        self.ImageQualitySpinBox.setButtonSymbols(QtWidgets.QSpinBox.NoButtons)
        self.ImageQualitySpinBox.setMinimum(1)
        self.ImageQualitySpinBox.setMaximum(100)

        ImageLayout = QtWidgets.QFormLayout()
        ImageLayout.addRow("Quality:", self.ImageQualitySpinBox)

        ImageSettingsWdg = QtWidgets.QGroupBox("Image Options")
        ImageSettingsWdg.setLayout(ImageLayout)

        self.SettingsStackedWdg = QtWidgets.QStackedWidget()
        self.SettingsStackedWdg.addWidget(h264SettingsWdg)
        self.SettingsStackedWdg.addWidget(ImageSettingsWdg)

        self.AcceptBtn = QtWidgets.QPushButton("Accept")
        self.CancelBtn = QtWidgets.QPushButton("Cancel")

    def CreateLayout(self):
        ButtonLayout = QtWidgets.QHBoxLayout()
        ButtonLayout.addStretch()
        ButtonLayout.addWidget(self.AcceptBtn)
        ButtonLayout.addWidget(self.CancelBtn)

        MainLayout = QtWidgets.QVBoxLayout(self)
        MainLayout.setContentsMargins(2, 2, 2, 2)
        MainLayout.setSpacing(4)
        MainLayout.addWidget(self.SettingsStackedWdg)
        MainLayout.addLayout(ButtonLayout)

    def CreateConnections(self):
        self.AcceptBtn.clicked.connect(self.accept)
        self.CancelBtn.clicked.connect(self.close)


    def SetPage(self, Page):
        if not Page in GeterosisPlayblastEncoderSettingsDialog.ENCODER_PAGES:
            return False

        self.SettingsStackedWdg.setCurrentIndex(GeterosisPlayblastEncoderSettingsDialog.ENCODER_PAGES[Page])
        return True

    def Seth264Settings(self, Quality, Preset):
        self.h264QualityCombo.setCurrentText(Quality)
        self.h264PresetCombo.setCurrentText(Preset)

    def Geth264Settings(self):
        return {
            "quality": self.h264QualityCombo.currentText(),
            "preset": self.h264PresetCombo.currentText(),
        }

    def SetImageSettings(self, quality):
        self.ImageQualitySpinBox.setValue(quality)

    def GetImageSettings(self):
        return {
            "quality": self.ImageQualitySpinBox.value(),
        }


class GeterosisPlayblastVisibilityDialog(QtWidgets.QDialog):

    def __init__(self, Parent):
        super(GeterosisPlayblastVisibilityDialog, self).__init__(Parent)

        self.setWindowTitle("Customize Visibility")
        self.setWindowFlags(self.windowFlags() ^ QtCore.Qt.WindowContextHelpButtonHint)
        self.setModal(True)

        VisibilityLayout = QtWidgets.QGridLayout()

        Index = 0
        self.VisibilityCheckboxes = []

        for i in range(len(GeterosisPlayblast.VIEWPORT_VISIBILITY_LOOKUP)):
            Checkbox = QtWidgets.QCheckBox(GeterosisPlayblast.VIEWPORT_VISIBILITY_LOOKUP[i][0])

            VisibilityLayout.addWidget(Checkbox, Index / 3, Index % 3)
            self.VisibilityCheckboxes.append(Checkbox)

            Index += 1

        VisibilityGrp = QtWidgets.QGroupBox("")
        VisibilityGrp.setLayout(VisibilityLayout)

        ApplyBtn = QtWidgets.QPushButton("Apply")
        ApplyBtn.clicked.connect(self.accept)

        CancelBtn = QtWidgets.QPushButton("Cancel")
        CancelBtn.clicked.connect(self.close)

        ButtonLayout = QtWidgets.QHBoxLayout()
        ButtonLayout.addStretch()
        ButtonLayout.addWidget(ApplyBtn)
        ButtonLayout.addWidget(CancelBtn)

        MainLayout = QtWidgets.QVBoxLayout(self)
        MainLayout.setContentsMargins(4, 4, 4, 4)
        MainLayout.setSpacing(4)
        MainLayout.addWidget(VisibilityGrp)
        MainLayout.addStretch()
        MainLayout.addLayout(ButtonLayout)

    def GetVisibilityData(self):
        Data = []
        for Checkbox in self.VisibilityCheckboxes:
            Data.append(Checkbox.isChecked())

        return Data

    def SetVisibilityData(self, Data):
        if len(self.VisibilityCheckboxes) != len(Data):
            raise RuntimeError("Visibility property/data mismatch")

        for i in range(len(Data)):
            self.VisibilityCheckboxes[i].setChecked(Data[i])


class GeterosisPlayblastUi(QtWidgets.QDialog):

    TITLE = "Geterosis Playblast"

    CONTAINER_PRESETS = [
        "mov",
        "mp4",
        "Image",
    ]

    RESOLUTION_PRESETS = [
        "Render",
        "HD 1080",
        "HD 720",
        "HD 540",
    ]

    VISIBILITY_PRESETS = [
        "Viewport",
        "Geo",
        "Dynamics",
    ]

    DlgInstance = None


    @classmethod
    def ShowDialog(Class):
        if not Class.DlgInstance:
            Class.DlgInstance = GeterosisPlayblastUi()

        if Class.DlgInstance.isHidden():
            Class.DlgInstance.show()
        else:
            Class.DlgInstance.raise_()
            Class.DlgInstance.activateWindow()

    def __init__(self):
        if sys.version_info.major < 3:
            MayaMainWindow = wrapInstance(int(omui.MQtUtil.mainWindow()), QtWidgets.QWidget)
        else:
            MayaMainWindow = wrapInstance(int(omui.MQtUtil.mainWindow()), QtWidgets.QWidget)

        super(GeterosisPlayblastUi, self).__init__(MayaMainWindow)

        self.setWindowTitle(GeterosisPlayblastUi.TITLE)
        self.setWindowFlags(self.windowFlags() ^ QtCore.Qt.WindowContextHelpButtonHint)
        self.setMinimumWidth(500)

        self._Playblast = GeterosisPlayblast()

        self._SettingsDialog = None
        self._EncoderSettingsDialog = None
        self._VisibilityDialog = None

        self.LoadSettings()

        self.CreateActions()
        self.CreateMenus()
        self.CreateWidgets()
        self.CreateLayout()
        self.CreateConnections()

        self.LoadDefaults()

        self.AppendOutput("Geterosis Playblast v{0}".format(GeterosisPlayblast.VERSION))

    def CreateActions(self):
        self.SaveDefaultsAction = QtWidgets.QAction("Save Defaults", self)
        self.SaveDefaultsAction.triggered.connect(self.save_defaults)

        self.LoadDefaultsAction = QtWidgets.QAction("Load Defaults", self)
        self.LoadDefaultsAction.triggered.connect(self.LoadDefaults)

        self.ShowSettingsAction = QtWidgets.QAction("Settings...", self)
        self.ShowSettingsAction.triggered.connect(self.ShowSettingsDialog)

        self.ShowAboutAction = QtWidgets.QAction("About", self)
        self.ShowAboutAction.triggered.connect(self.ShowAboutDialog)

    def CreateMenus(self):
        self.MainMenu = QtWidgets.QMenuBar()

        EditMenu = self.MainMenu.addMenu("Edit")
        EditMenu.addAction(self.SaveDefaultsAction)
        EditMenu.addAction(self.LoadDefaultsAction)
        EditMenu.addSeparator()
        EditMenu.addAction(self.ShowSettingsAction)

        HelpMenu = self.MainMenu.addMenu("Help")
        HelpMenu.addAction(self.ShowAboutAction)

    def CreateWidgets(self):
        self.OutputDirPathLine = QtWidgets.QLineEdit()
        self.OutputDirPathLine.setPlaceholderText("{project}/movies")

        self.OutputDirPathSelectBtn = QtWidgets.QPushButton("...")
        self.OutputDirPathSelectBtn.setFixedSize(24, 19)
        self.OutputDirPathSelectBtn.setToolTip("Select Output Directory")

        self.OutputDirPathShowFolderBtn = QtWidgets.QPushButton(QtGui.QIcon(":fileOpen.png"), "")
        self.OutputDirPathShowFolderBtn.setFixedSize(24, 19)
        self.OutputDirPathShowFolderBtn.setToolTip("Show in Folder")

        self.OutputFilenameLine = QtWidgets.QLineEdit()
        self.OutputFilenameLine.setPlaceholderText("{scene}")
        self.OutputFilenameLine.setMaximumWidth(200)
        self.ForceOverwriteCheckBox = QtWidgets.QCheckBox("Force overwrite")

        self.ResolutionSelectComboBox = QtWidgets.QComboBox()
        self.ResolutionSelectComboBox.addItems(GeterosisPlayblastUi.RESOLUTION_PRESETS)
        self.ResolutionSelectComboBox.addItem("Custom")
        self.ResolutionSelectComboBox.setCurrentText(GeterosisPlayblast.DEFAULT_RESOLUTION)

        self.ResolutionWidthSpinBox = QtWidgets.QSpinBox()
        self.ResolutionWidthSpinBox.setButtonSymbols(QtWidgets.QSpinBox.NoButtons)
        self.ResolutionWidthSpinBox.setRange(1, 9999)
        self.ResolutionWidthSpinBox.setMinimumWidth(40)
        self.ResolutionWidthSpinBox.setAlignment(QtCore.Qt.AlignRight)
        self.ResolutionHeightSpineBox = QtWidgets.QSpinBox()
        self.ResolutionHeightSpineBox.setButtonSymbols(QtWidgets.QSpinBox.NoButtons)
        self.ResolutionHeightSpineBox.setRange(1, 9999)
        self.ResolutionHeightSpineBox.setMinimumWidth(40)
        self.ResolutionHeightSpineBox.setAlignment(QtCore.Qt.AlignRight)

        self.CameraSelectComboBox = QtWidgets.QComboBox()
        self.CameraSelectHideDefaultsCheckBox = QtWidgets.QCheckBox("Hide defaults")
        self.RefreshCameras()

        self.FrameRangeCombobox = QtWidgets.QComboBox()
        self.FrameRangeCombobox.addItems(GeterosisPlayblast.FRAME_RANGE_PRESETS)
        self.FrameRangeCombobox.addItem("Custom")
        self.FrameRangeCombobox.setCurrentText(GeterosisPlayblast.DEFAULT_FRAME_RANGE)

        self.FrameRangeStartSpineBox = QtWidgets.QSpinBox()
        self.FrameRangeStartSpineBox.setButtonSymbols(QtWidgets.QSpinBox.NoButtons)
        self.FrameRangeStartSpineBox.setRange(-9999, 9999)
        self.FrameRangeStartSpineBox.setMinimumWidth(40)
        self.FrameRangeStartSpineBox.setAlignment(QtCore.Qt.AlignRight)

        self.FrameRangeEndSpinBox = QtWidgets.QSpinBox()
        self.FrameRangeEndSpinBox.setButtonSymbols(QtWidgets.QSpinBox.NoButtons)
        self.FrameRangeEndSpinBox.setRange(-9999, 9999)
        self.FrameRangeEndSpinBox.setMinimumWidth(40)
        self.FrameRangeEndSpinBox.setAlignment(QtCore.Qt.AlignRight)

        self.EncodingContainerComboBox = QtWidgets.QComboBox()
        self.EncodingContainerComboBox.addItems(GeterosisPlayblastUi.CONTAINER_PRESETS)
        self.EncodingContainerComboBox.setCurrentText(GeterosisPlayblast.DEFAULT_CONTAINER)

        self.EncodingVideoCodecComboBox = QtWidgets.QComboBox()
        self.EncodingVideoCodecSettingsBtn = QtWidgets.QPushButton("Settings...")
        self.EncodingVideoCodecSettingsBtn.setFixedHeight(19)

        self.VisibilityComboBox = QtWidgets.QComboBox()
        self.VisibilityComboBox.addItems(GeterosisPlayblastUi.VISIBILITY_PRESETS)
        self.VisibilityComboBox.addItem("Custom")
        self.VisibilityComboBox.setCurrentText(GeterosisPlayblast.DEFAULT_VISIBILITY)

        self.VisibilityCustomizeBtn = QtWidgets.QPushButton("Customize...")
        self.VisibilityCustomizeBtn.setFixedHeight(19)
        
        self.OverscanCheckBox = QtWidgets.QCheckBox()
        self.OverscanCheckBox.setChecked(False)

        self.OrnamentsCheckBox = QtWidgets.QCheckBox()
        self.OrnamentsCheckBox.setChecked(True)

        self.ViewerCheckBox = QtWidgets.QCheckBox()
        self.ViewerCheckBox.setChecked(True)

        self.OutputEdit = QtWidgets.QPlainTextEdit()
        self.OutputEdit.setReadOnly(True)
        self.OutputEdit.setWordWrapMode(QtGui.QTextOption.NoWrap)

        self.RefreshBtn = QtWidgets.QPushButton("Refresh")
        self.ClearBtn = QtWidgets.QPushButton("Clear")
        self.PlayblastBtn = QtWidgets.QPushButton("Playblast")
        self.CloseBtn = QtWidgets.QPushButton("Close")

    def CreateLayout(self):
        OutputPathLayout = QtWidgets.QHBoxLayout()
        OutputPathLayout.setSpacing(4)
        OutputPathLayout.addWidget(self.OutputDirPathLine)
        OutputPathLayout.addWidget(self.OutputDirPathSelectBtn)
        OutputPathLayout.addWidget(self.OutputDirPathShowFolderBtn)

        OutputFileLayout = QtWidgets.QHBoxLayout()
        OutputFileLayout.setSpacing(4)
        OutputFileLayout.addWidget(self.OutputFilenameLine)
        OutputFileLayout.addWidget(self.ForceOverwriteCheckBox)

        OutputLayout = QtWidgets.QFormLayout()
        OutputLayout.setSpacing(4)
        OutputLayout.addRow("Directory:", OutputPathLayout)
        OutputLayout.addRow("Filename:", OutputFileLayout)

        OutputGrp = QtWidgets.QGroupBox("Output")
        OutputGrp.setLayout(OutputLayout)

        CameraOptionsLayout = QtWidgets.QHBoxLayout()
        CameraOptionsLayout.setSpacing(4)
        CameraOptionsLayout.addWidget(self.CameraSelectComboBox)
        CameraOptionsLayout.addWidget(self.CameraSelectHideDefaultsCheckBox)

        ResolutionLayout = QtWidgets.QHBoxLayout()
        ResolutionLayout.setSpacing(4)
        ResolutionLayout.addWidget(self.ResolutionSelectComboBox)
        ResolutionLayout.addWidget(self.ResolutionWidthSpinBox)
        ResolutionLayout.addWidget(QtWidgets.QLabel("x"))
        ResolutionLayout.addWidget(self.ResolutionHeightSpineBox)

        FrameRangeLayout = QtWidgets.QHBoxLayout()
        FrameRangeLayout.setSpacing(4)
        FrameRangeLayout.addWidget(self.FrameRangeCombobox)
        FrameRangeLayout.addWidget(self.FrameRangeStartSpineBox)
        FrameRangeLayout.addWidget(self.FrameRangeEndSpinBox)

        EncodingLayout = QtWidgets.QHBoxLayout()
        EncodingLayout.setSpacing(4)
        EncodingLayout.addWidget(self.EncodingContainerComboBox)
        EncodingLayout.addWidget(self.EncodingVideoCodecComboBox)
        EncodingLayout.addWidget(self.EncodingVideoCodecSettingsBtn)

        VisibilityLayout = QtWidgets.QHBoxLayout()
        VisibilityLayout.setSpacing(4)
        VisibilityLayout.addWidget(self.VisibilityComboBox)
        VisibilityLayout.addWidget(self.VisibilityCustomizeBtn)

        OptionsLayout = QtWidgets.QFormLayout()
        OptionsLayout.addRow("Camera:", CameraOptionsLayout)
        OptionsLayout.addRow("Resolution:", ResolutionLayout)
        OptionsLayout.addRow("Frame Range:", FrameRangeLayout)
        OptionsLayout.addRow("Encoding:", EncodingLayout)
        OptionsLayout.addRow("Visiblity:", VisibilityLayout)
        OptionsLayout.addRow("Overscan:", self.OverscanCheckBox)
        OptionsLayout.addRow("Ornaments:", self.OrnamentsCheckBox)
        OptionsLayout.addRow("Show in Viewer:", self.ViewerCheckBox)

        OptionsGrp = QtWidgets.QGroupBox("Options")
        OptionsGrp.setLayout(OptionsLayout)

        ButtonLayout = QtWidgets.QHBoxLayout()
        ButtonLayout.addWidget(self.RefreshBtn)
        ButtonLayout.addWidget(self.ClearBtn)
        ButtonLayout.addStretch()
        ButtonLayout.addWidget(self.PlayblastBtn)
        ButtonLayout.addWidget(self.CloseBtn)

        StatusBarLayout = QtWidgets.QHBoxLayout()
        StatusBarLayout.addStretch()
        StatusBarLayout.addWidget(QtWidgets.QLabel("v{0}".format(GeterosisPlayblast.VERSION)))

        MainLayout = QtWidgets.QVBoxLayout(self)
        MainLayout.setContentsMargins(4, 4, 4, 4)
        MainLayout.setSpacing(4)
        MainLayout.setMenuBar(self.MainMenu)
        MainLayout.addWidget(OutputGrp)
        MainLayout.addWidget(OptionsGrp)
        MainLayout.addWidget(self.OutputEdit)
        MainLayout.addLayout(ButtonLayout)
        MainLayout.addLayout(StatusBarLayout)

    def CreateConnections(self):
        self.OutputDirPathSelectBtn.clicked.connect(self.SelectOutputDirectory)
        self.OutputDirPathShowFolderBtn.clicked.connect(self.OpenOutputDirectory)

        self.CameraSelectComboBox.currentTextChanged.connect(self.OnCameraChanged)
        self.CameraSelectHideDefaultsCheckBox.toggled.connect(self.RefreshCameras)

        self.FrameRangeCombobox.currentTextChanged.connect(self.RefreshFrameRange)
        self.FrameRangeStartSpineBox.editingFinished.connect(self.OnFrameRangeChanged)
        self.FrameRangeEndSpinBox.editingFinished.connect(self.OnFrameRangeChanged)

        self.EncodingContainerComboBox.currentTextChanged.connect(self.RefreshVideoEncoders)
        self.EncodingVideoCodecComboBox.currentTextChanged.connect(self.OnVideoEncoderChanged)
        self.EncodingVideoCodecSettingsBtn.clicked.connect(self.ShowEncoderSettingsDialog)

        self.ResolutionSelectComboBox.currentTextChanged.connect(self.RefreshResolution)
        self.ResolutionWidthSpinBox.editingFinished.connect(self.OnResolutionChanged)
        self.ResolutionHeightSpineBox.editingFinished.connect(self.OnResolutionChanged)

        self.VisibilityComboBox.currentTextChanged.connect(self.OnVisibilityPresetChanged)
        self.VisibilityCustomizeBtn.clicked.connect(self.ShowVisibilityDialog)

        self.RefreshBtn.clicked.connect(self.Refresh)
        self.ClearBtn.clicked.connect(self.OutputEdit.clear)
        self.PlayblastBtn.clicked.connect(self.DoPlayblast)
        self.CloseBtn.clicked.connect(self.close)

        self._Playblast.OutputLogged.connect(self.AppendOutput) # pylint: disable=E1101

    def DoPlayblast(self):
        OutputDirPath = self.OutputDirPathLine.text()
        if not OutputDirPath:
            OutputDirPath = self.OutputDirPathLine.placeholderText()

        FileName = self.OutputFilenameLine.text()
        if not FileName:
            FileName = self.OutputFilenameLine.placeholderText()

        Padding = GeterosisPlayblast.DEFAULT_PADDING

        Overscan = self.OverscanCheckBox.isChecked()
        ShowOrnaments = self.OrnamentsCheckBox.isChecked()
        ShowInViewer = self.ViewerCheckBox.isChecked()
        overwrite = self.ForceOverwriteCheckBox.isChecked()

        self._Playblast.execute(OutputDirPath, FileName, Padding, Overscan, ShowOrnaments, ShowInViewer, overwrite)

    def SelectOutputDirectory(self):
        CurrentDirPath = self.OutputDirPathLine.text()
        if not CurrentDirPath:
            CurrentDirPath = ""

        CurrentDirPath = self._Playblast.ResolveOutputDirectoryPath(CurrentDirPath)

        FileInfo = QtCore.QFileInfo(CurrentDirPath)
        if not FileInfo.exists():
            CurrentDirPath = self._Playblast.GetProjectDirPath()

        NewDirPath = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Directory", CurrentDirPath)
        if NewDirPath:
            self.OutputDirPathLine.setText(NewDirPath)

    def OpenOutputDirectory(self):
        OutputDirPath = self.OutputDirPathLine.text()
        if not OutputDirPath:
            OutputDirPath = self.OutputDirPathLine.placeholderText()

        OutputDirPath = self._Playblast.ResolveOutputDirectoryPath(OutputDirPath)

        FileInfo = QtCore.QFileInfo(OutputDirPath)
        if FileInfo.isDir():
            QtGui.QDesktopServices.openUrl(OutputDirPath)
        else:
            self.AppendOutput("[ERROR] Invalid directory path: {0}".format(OutputDirPath))

    def Refresh(self):
        self.RefreshCameras()
        self.RefreshResolution()
        self.RefreshFrameRange()
        self.RefreshVideoEncoders()

    def RefreshCameras(self):
        CurrentCamera = self.CameraSelectComboBox.currentText()
        self.CameraSelectComboBox.clear()

        self.CameraSelectComboBox.addItem("<Active>")

        Cameras = cmds.listCameras()
        if self.CameraSelectHideDefaultsCheckBox.isChecked():
            for Camera in Cameras:
                if Camera not in ["front", "persp", "side", "top"]:
                    self.CameraSelectComboBox.addItem(Camera)
        else:
            self.CameraSelectComboBox.addItems(Cameras)

        self.CameraSelectComboBox.setCurrentText(CurrentCamera)

    def OnCameraChanged(self):
        Camera = self.CameraSelectComboBox.currentText()
        if Camera == "<Active>":
            Camera = None

        self._Playblast.SetCamera(Camera)

    def RefreshResolution(self):
        ResolutionPreset = self.ResolutionSelectComboBox.currentText()
        if ResolutionPreset != "Custom":
            self._Playblast.SetResolution(ResolutionPreset)

            Resolution = self._Playblast.GetResolutionWidthHeight()
            self.ResolutionWidthSpinBox.setValue(Resolution[0])
            self.ResolutionHeightSpineBox.setValue(Resolution[1])

    def OnResolutionChanged(self):
        Resolution = (self.ResolutionWidthSpinBox.value(), self.ResolutionHeightSpineBox.value())

        for key in GeterosisPlayblast.RESOLUTION_LOOKUP.keys():
            if GeterosisPlayblast.RESOLUTION_LOOKUP[key] == Resolution:
                self.ResolutionSelectComboBox.setCurrentText(key)
                return

        self.ResolutionSelectComboBox.setCurrentText("Custom")

        self._Playblast.SetResolution(Resolution)

    def RefreshFrameRange(self):
        FrameRangePreset = self.FrameRangeCombobox.currentText()
        if FrameRangePreset != "Custom":
            FrameRange = self._Playblast.PresetToFrameRange(FrameRangePreset)

            self.FrameRangeStartSpineBox.setValue(FrameRange[0])
            self.FrameRangeEndSpinBox.setValue(FrameRange[1])

            self._Playblast.SetFrameRange(FrameRangePreset)

    def OnFrameRangeChanged(self):
        self.FrameRangeCombobox.setCurrentText("Custom")

        FrameRange = (self.FrameRangeStartSpineBox.value(), self.FrameRangeEndSpinBox.value())
        self._Playblast.SetFrameRange(FrameRange)

    def RefreshVideoEncoders(self):
        self.EncodingVideoCodecComboBox.clear()

        Container = self.EncodingContainerComboBox.currentText()
        self.EncodingVideoCodecComboBox.addItems(GeterosisPlayblast.VIDEO_ENCODER_LOOKUP[Container])

    def OnVideoEncoderChanged(self):
        Container = self.EncodingContainerComboBox.currentText()
        Encoder = self.EncodingVideoCodecComboBox.currentText()

        if Container and Encoder:
            self._Playblast.SetEncoding(Container, Encoder)

    def ShowEncoderSettingsDialog(self):
        if not self._EncoderSettingsDialog:
            self._EncoderSettingsDialog = GeterosisPlayblastEncoderSettingsDialog(self)
            self._EncoderSettingsDialog.accepted.connect(self.OnEncoderSettingsDialogModified)

        if self.EncodingContainerComboBox.currentText() == "Image":
            self._EncoderSettingsDialog.SetPage("Image")

            image_settings = self._Playblast.GetImageSettings()
            self._EncoderSettingsDialog.SetImageSettings(image_settings["quality"])

        else:
            Encoder = self.EncodingVideoCodecComboBox.currentText()
            if Encoder == "h264":
                self._EncoderSettingsDialog.SetPage("h264")

                h264Settings = self._Playblast.Geth264Settings()
                self._EncoderSettingsDialog.Seth264Settings(h264Settings["quality"], h264Settings["preset"])
            else:
                self.AppendOutput("[ERROR] Settings page not found for encoder: {0}".format(Encoder))

        self._EncoderSettingsDialog.show()

    def OnEncoderSettingsDialogModified(self):
        if self.EncodingContainerComboBox.currentText() == "Image":
            ImageSettings = self._EncoderSettingsDialog.GetImageSettings()
            self._Playblast.SetImageSettings(ImageSettings["quality"])
        else:
            Encoder = self.EncodingVideoCodecComboBox.currentText()
            if Encoder == "h264":
                h264Settings = self._EncoderSettingsDialog.Geth264Settings()
                self._Playblast.Seth264Settings(h264Settings["quality"], h264Settings["preset"])
            else:
                self.AppendOutput("[ERROR] Failed to set encoder settings. Unknown encoder: {0}".format(Encoder))

    def OnVisibilityPresetChanged(self):
        VisibilityPreset = self.VisibilityComboBox.currentText()
        if VisibilityPreset != "Custom":
            self._Playblast.SetVisibility(VisibilityPreset)

    def ShowVisibilityDialog(self):
        if not self._VisibilityDialog:
            self._VisibilityDialog = GeterosisPlayblastVisibilityDialog(self)
            self._VisibilityDialog.accepted.connect(self.OnVisibilityDialogModified)

        self._VisibilityDialog.SetVisibilityData(self._Playblast.GetVisibility())

        self._VisibilityDialog.show()

    def OnVisibilityDialogModified(self):
        self.VisibilityComboBox.setCurrentText("Custom")
        self._Playblast.SetVisibility(self._VisibilityDialog.GetVisibilityData())

    def SaveSettings(self):
        cmds.optionVar(sv=("GeterosisPlayblastUiFFmpegPath", self._Playblast.GetFfmpegPath()))

    def LoadSettings(self):
        if cmds.optionVar(exists="GeterosisPlayblastUiFFmpegPath"):
            self._Playblast.SetFfmpegPath(cmds.optionVar(q="GeterosisPlayblastUiFFmpegPath"))

    def save_defaults(self):
        cmds.optionVar(sv=("GeterosisPlayblastUiOutputDir", self.OutputDirPathLine.text()))
        cmds.optionVar(sv=("GeterosisPlayblastUiOutputFilename", self.OutputFilenameLine.text()))
        cmds.optionVar(iv=("GeterosisPlayblastUiForceOverwrite", self.ForceOverwriteCheckBox.isChecked()))

        cmds.optionVar(sv=("GeterosisPlayblastUiCamera", self.CameraSelectComboBox.currentText()))
        cmds.optionVar(iv=("GeterosisPlayblastUiHideDefaultCameras", self.CameraSelectHideDefaultsCheckBox.isChecked()))

        cmds.optionVar(sv=("GeterosisPlayblastUiResolutionPreset", self.ResolutionSelectComboBox.currentText()))
        cmds.optionVar(iv=("GeterosisPlayblastUiResolutionWidth", self.ResolutionWidthSpinBox.value()))
        cmds.optionVar(iv=("GeterosisPlayblastUiResolutionHeight", self.ResolutionHeightSpineBox.value()))

        cmds.optionVar(sv=("GeterosisPlayblastUiFrameRangePreset", self.FrameRangeCombobox.currentText()))
        cmds.optionVar(iv=("GeterosisPlayblastUiFrameRangeStart", self.FrameRangeStartSpineBox.value()))
        cmds.optionVar(iv=("GeterosisPlayblastUiFrameRangeEnd", self.FrameRangeEndSpinBox.value()))

        cmds.optionVar(sv=("GeterosisPlayblastUiEncodingContainer", self.EncodingContainerComboBox.currentText()))
        cmds.optionVar(sv=("GeterosisPlayblastUiEncodingVideoCodec", self.EncodingVideoCodecComboBox.currentText()))

        h264Settings = self._Playblast.Geth264Settings()
        cmds.optionVar(sv=("GeterosisPlayblastUiH264Quality", h264Settings["quality"]))
        cmds.optionVar(sv=("GeterosisPlayblastUiH264Preset", h264Settings["preset"]))

        ImageSettings = self._Playblast.GetImageSettings()
        cmds.optionVar(iv=("GeterosisPlayblastUiImageQuality", ImageSettings["quality"]))

        cmds.optionVar(sv=("GeterosisPlayblastUiVisibilityPreset", self.VisibilityComboBox.currentText()))

        VisibilityData = self._Playblast.GetVisibility()
        VisibilityStr = ""
        for Item in VisibilityData:
            VisibilityStr = "{0} {1}".format(VisibilityStr, int(Item))
        cmds.optionVar(sv=("GeterosisPlayblastUiVisibilityData", VisibilityStr))

        cmds.optionVar(iv=("GeterosisPlayblastUiOverscan", self.OverscanCheckBox.isChecked()))
        cmds.optionVar(iv=("GeterosisPlayblastUiOrnaments", self.OrnamentsCheckBox.isChecked()))
        cmds.optionVar(iv=("GeterosisPlayblastUiViewer", self.ViewerCheckBox.isChecked()))

    def LoadDefaults(self):
        if cmds.optionVar(exists="GeterosisPlayblastUiOutputDir"):
            self.OutputDirPathLine.setText(cmds.optionVar(q="GeterosisPlayblastUiOutputDir"))
        if cmds.optionVar(exists="GeterosisPlayblastUiOutputFilename"):
            self.OutputFilenameLine.setText(cmds.optionVar(q="GeterosisPlayblastUiOutputFilename"))
        if cmds.optionVar(exists="GeterosisPlayblastUiForceOverwrite"):
            self.ForceOverwriteCheckBox.setChecked(cmds.optionVar(q="GeterosisPlayblastUiForceOverwrite"))

        if cmds.optionVar(exists="GeterosisPlayblastUiCamera"):
            self.CameraSelectComboBox.setCurrentText(cmds.optionVar(q="GeterosisPlayblastUiCamera"))
        if cmds.optionVar(exists="GeterosisPlayblastUiHideDefaultCameras"):
            self.CameraSelectHideDefaultsCheckBox.setChecked(cmds.optionVar(q="GeterosisPlayblastUiHideDefaultCameras"))

        if cmds.optionVar(exists="GeterosisPlayblastUiResolutionPreset"):
            self.ResolutionSelectComboBox.setCurrentText(cmds.optionVar(q="GeterosisPlayblastUiResolutionPreset"))
        if self.ResolutionSelectComboBox.currentText() == "Custom":
            if cmds.optionVar(exists="GeterosisPlayblastUiResolutionWidth"):
                self.ResolutionWidthSpinBox.setValue(cmds.optionVar(q="GeterosisPlayblastUiResolutionWidth"))
            if cmds.optionVar(exists="GeterosisPlayblastUiResolutionHeight"):
                self.ResolutionHeightSpineBox.setValue(cmds.optionVar(q="GeterosisPlayblastUiResolutionHeight"))
            self.OnResolutionChanged()

        if cmds.optionVar(exists="GeterosisPlayblastUiFrameRangePreset"):
            self.FrameRangeCombobox.setCurrentText(cmds.optionVar(q="GeterosisPlayblastUiFrameRangePreset"))
        if self.FrameRangeCombobox.currentText() == "Custom":
            if cmds.optionVar(exists="GeterosisPlayblastUiFrameRangeStart"):
                self.FrameRangeStartSpineBox.setValue(cmds.optionVar(q="GeterosisPlayblastUiFrameRangeStart"))
            if cmds.optionVar(exists="GeterosisPlayblastUiFrameRangeEnd"):
                self.FrameRangeEndSpinBox.setValue(cmds.optionVar(q="GeterosisPlayblastUiFrameRangeEnd"))
            self.OnFrameRangeChanged()

        if cmds.optionVar(exists="GeterosisPlayblastUiEncodingContainer"):
            self.EncodingContainerComboBox.setCurrentText(cmds.optionVar(q="GeterosisPlayblastUiEncodingContainer"))
        if cmds.optionVar(exists="GeterosisPlayblastUiEncodingVideoCodec"):
            self.EncodingVideoCodecComboBox.setCurrentText(cmds.optionVar(q="GeterosisPlayblastUiEncodingVideoCodec"))

        if cmds.optionVar(exists="GeterosisPlayblastUiH264Quality") and cmds.optionVar(exists="GeterosisPlayblastUiH264Preset"):
            self._Playblast.Seth264Settings(cmds.optionVar(q="GeterosisPlayblastUiH264Quality"), cmds.optionVar(q="GeterosisPlayblastUiH264Preset"))

        if cmds.optionVar(exists="GeterosisPlayblastUiImageQuality"):
            self._Playblast.SetImageSettings(cmds.optionVar(q="GeterosisPlayblastUiImageQuality"))

        if cmds.optionVar(exists="GeterosisPlayblastUiVisibilityPreset"):
            self.VisibilityComboBox.setCurrentText(cmds.optionVar(q="GeterosisPlayblastUiVisibilityPreset"))
        if self.VisibilityComboBox.currentText() == "Custom":
            if cmds.optionVar(exists="GeterosisPlayblastUiVisibilityData"):
                VisibilityStrList = cmds.optionVar(q="GeterosisPlayblastUiVisibilityData").split()
                VisibilityData = []
                for Item in VisibilityStrList:
                    if Item:
                        VisibilityData.append(bool(int(Item)))

                self._Playblast.SetVisibility(VisibilityData)

        if cmds.optionVar(exists="GeterosisPlayblastUiOverscan"):
            self.OverscanCheckBox.setChecked(cmds.optionVar(q="GeterosisPlayblastUiOverscan"))
        if cmds.optionVar(exists="GeterosisPlayblastUiOrnaments"):
            self.OrnamentsCheckBox.setChecked(cmds.optionVar(q="GeterosisPlayblastUiOrnaments"))
        if cmds.optionVar(exists="GeterosisPlayblastUiViewer"):
            self.ViewerCheckBox.setChecked(cmds.optionVar(q="GeterosisPlayblastUiViewer"))

    def ShowSettingsDialog(self):
        if not self._SettingsDialog:
            self._SettingsDialog = GeterosisPlayblastSettingsDialog(self)
            self._SettingsDialog.accepted.connect(self.OnSettingsDialogModified)

        self._SettingsDialog.SetFfmpegPath(self._Playblast.GetFfmpegPath())

        self._SettingsDialog.show()

    def OnSettingsDialogModified(self):
        FfmpegPath = self._SettingsDialog.GetFfmpegPath()
        self._Playblast.SetFfmpegPath(FfmpegPath)

        self.SaveSettings()

    def ShowAboutDialog(self):
        text = '<h2>{0}</h2>'.format(GeterosisPlayblastUi.TITLE)
        text += '<p>Version: {0}</p>'.format(GeterosisPlayblast.VERSION)
        text += '<p>Author: TacherB</p>'
        text += '<p>Repository: <a style="color:white;" href="https://github.com/TascherB/CustomPlayblast">CustomPlayblast</a></p><br>'

        QtWidgets.QMessageBox().about(self, "About", "{0}".format(text))

    def AppendOutput(self, Text):
        self.OutputEdit.appendPlainText(Text)

    def keyPressEvent(self, Event):
        super(GeterosisPlayblastUi, self).keyPressEvent(Event)

        Event.accept()

    def showEvent(self, Event):
        self.Refresh()


if __name__ == "__main__":

    try:
        GS_playblast_dialog.close() # pylint: disable=E0601
        GS_playblast_dialog.deleteLater()
    except:
        pass

    GS_playblast_dialog = GeterosisPlayblastUi()
    GS_playblast_dialog.show()






    
