# Local RPM for Stem Studio. Built by scripts/build-linux-rpm.sh from prebuilt
# artefacts (Tauri binary + PyInstaller engine) staged in the SOURCES directory.

%global appdir %{_prefix}/lib/Stem Studio

# The PyInstaller engine bundles its own Python, PyTorch and CUDA libraries:
# leave them untouched (no strip, no debuginfo, no bytecompile) and keep them
# out of RPM's automatic Provides/Requires. libcuda comes from the NVIDIA driver
# when present; without it the engine runs on CPU.
%global debug_package %{nil}
%global __os_install_post %{nil}
%global _build_id_links none
%global __provides_exclude_from ^%{appdir}/.*$
%global __requires_exclude_from ^%{appdir}/.*$
# Multithreaded zstd keeps packaging of several GB of CUDA libraries fast.
%global _binary_payload w3T0.zstdio

Name:           stem-studio
Version:        %{app_version}
Release:        1%{?dist}
Summary:        Separate and mix audio stems
License:        LicenseRef-Proprietary
ExclusiveArch:  x86_64

Requires:       /usr/bin/ffmpeg
Requires:       webkit2gtk4.1
Requires:       gtk3
Requires:       gstreamer1-plugins-base
Requires:       gstreamer1-plugins-good

%description
A synchronized four-stem audio workstation. Separates an MP3 or WAV into
vocals, drums, bass and other stems with Demucs or BS-RoFormer (CUDA when an
NVIDIA GPU is available), then transcribes bass and drums.

%prep

%build

%install
install -Dm0755 %{_sourcedir}/stem-studio %{buildroot}%{_bindir}/stem-studio
mkdir -p "%{buildroot}%{appdir}/binaries"
cp -a %{_sourcedir}/stem-engine "%{buildroot}%{appdir}/binaries/stem-engine"
install -Dm0644 %{_sourcedir}/stem-studio.desktop %{buildroot}%{_datadir}/applications/stem-studio.desktop
for size in 32 64 128 512; do
  install -Dm0644 %{_sourcedir}/icon-${size}.png \
    %{buildroot}%{_datadir}/icons/hicolor/${size}x${size}/apps/stem-studio.png
done

%files
%{_bindir}/stem-studio
"%{appdir}"
%{_datadir}/applications/stem-studio.desktop
%{_datadir}/icons/hicolor/*/apps/stem-studio.png
