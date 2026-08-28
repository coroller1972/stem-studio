# Third-party notices

This inventory covers the principal components intentionally shipped by Stem Studio. The generated
SBOM must be reviewed for the complete transitive inventory before redistribution.

| Component | Version/source | License status |
|---|---|---|
| FFmpeg | build supplied through `STEM_STUDIO_FFMPEG` | LGPL 2.1+ build required; GPL/nonfree/x264/x265 builds are rejected |
| PyTorch | 2.8.0 | BSD-3-Clause |
| torchaudio | 2.8.0 | BSD-family; verify bundled notice |
| Demucs | 4.1.0 | MIT |
| bs-roformer-infer | OpenMIRLab commit `b0f1386…` | MIT |
| Basic Pitch | 0.4.0 | Apache-2.0 upstream; verify bundled model notice |
| TorchCREPE | 0.0.24 | MIT |
| librosa | 0.11.0 | ISC |
| mido | 1.3.3 | MIT |
| scikit-learn | 1.5.1 | BSD-3-Clause |
| DrumScript | 0.2.1 | Apache-2.0 |
| PyInstaller | 6.22.2 | GPL-2.0-or-later with bootloader exception |

Model weights are not bundled. HTDemucs and BS-RoFormer are downloaded on first use. The
BS-RoFormer MUSDB18HQ checkpoint remains marked `not-reviewed` by the upstream registry; do not
redistribute that checkpoint until its provenance and license have been reviewed.

This file is an engineering inventory, not legal advice.
